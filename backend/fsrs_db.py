"""
FSRS-6 间隔重复算法 + SQLite 持久化（支持多用户）

基于官方 Py-FSRS 库 (pip install fsrs) 实现，用于句子/单词的复习调度。
Py-FSRS 提供了经过严格验证的 FSRS-6 算法实现，确保调度准确性。

核心设计：
- 使用 fsrs.Scheduler 作为调度引擎（替代手写公式）
- 使用 fsrs.Card / fsrs.Rating / fsrs.State 作为核心数据结构
- 保留自定义参数拟合（Py-FSRS 未内置拟合功能）
- 新卡片的 due 设为远过去（确保可被查询）
- LEARNING/RELEARNING 卡片不参与练习选择（避免短间隔重复）
- 新词70% + 复习30% 的混合策略

Rating: 1=Again, 2=Hard, 3=Good, 4=Easy
State:  Learning=1, Review=2, Relearning=3 (NEW=0 自定义)

多用户支持：cards 和 review_log 表均包含 user_id 字段。
"""

import sqlite3
import time
import math
import json
import random
import copy
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Tuple

from fsrs import Card as PyFSCard, Rating, State, Scheduler, ReviewLog

logger = logging.getLogger(__name__)

# ============================================================
# 默认配置
# ============================================================

DEFAULT_DESIRED_RETENTION = 0.9
DEFAULT_LEARNING_STEPS = [1, 10]       # 分钟
DEFAULT_RELEARNING_STEPS = [10]        # 分钟
DEFAULT_MAXIMUM_INTERVAL = 36500       # 天
DEFAULT_NEW_PER_DAY = 5

DB_PATH = Path(__file__).parent / "phonos_fsrs.db"

# State 常量（兼容旧代码）
NEW = 0
LEARNING = 1
REVIEW = 2
RELEARNING = 3

STATE_NAMES = ["new", "learning", "review", "relearning"]


# ============================================================
# 辅助：Py-FSRS Card 与 DB 互转
# ============================================================

def _pyfsrs_state_to_int(state) -> int:
    """将 Py-FSRS State 枚举转为整数（0=NEW 自定义, 1=Learning, 2=Review, 3=Relearning）"""
    if state == State.Learning:
        return LEARNING
    elif state == State.Review:
        return REVIEW
    elif state == State.Relearning:
        return RELEARNING
    return NEW


def _int_to_pyfsrs_state(state_int: int):
    """将整数状态转为 Py-FSRS State 枚举"""
    mapping = {NEW: State.Learning, LEARNING: State.Learning,
               REVIEW: State.Review, RELEARNING: State.Relearning}
    return mapping.get(state_int, State.Learning)


def _datetime_to_ts(dt) -> float:
    """datetime 转为 Unix 时间戳（秒）"""
    if dt is None:
        return 0.0
    return dt.timestamp()


def _ts_to_datetime(ts: float):
    """Unix 时间戳转为 UTC datetime"""
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _card_to_dict(card: PyFSCard, card_id: str = None) -> dict:
    """将 Py-FSRS Card 转为可序列化字典"""
    return {
        "card_id": card_id or str(card.card_id),
        "difficulty": card.difficulty if card.difficulty is not None else 0.0,
        "stability": card.stability if card.stability is not None else 0.0,
        "state": _pyfsrs_state_to_int(card.state),
        "due": _datetime_to_ts(card.due),
        "last_review": _datetime_to_ts(card.last_review),
        "scheduled_days": 0.0,  # 需要额外计算
        "step": card.step,
    }


def _make_pyfsrs_card(state_int: int = NEW, difficulty: float = 0.0,
                       stability: float = 0.0, due_ts: float = 0.0,
                       last_review_ts: float = 0.0, step: int = None) -> PyFSCard:
    """根据存储的数据重建 Py-FSRS Card 对象"""
    card = PyFSCard()
    if state_int != NEW:
        card.state = _int_to_pyfsrs_state(state_int)
        card.difficulty = difficulty
        card.stability = stability
        card.due = _ts_to_datetime(due_ts) or datetime.now(timezone.utc)
        card.last_review = _ts_to_datetime(last_review_ts)
        if step is not None:
            card.step = step
    else:
        # NEW card - Py-FSRS 默认 State.Learning, 需要特殊处理
        card.state = State.Learning
        card.difficulty = None
        card.stability = None
        card.due = datetime.now(timezone.utc)
    return card


# ============================================================
# 参数拟合（保留自定义实现，Py-FSRS 未内置）
# ============================================================

# FSRS-6 默认参数（21个）
DEFAULT_FSRS_PARAMS = list(Scheduler().parameters)

PARAM_BOUNDS = [
    (0.01, 10.0), (0.01, 10.0), (0.01, 10.0), (0.01, 30.0),  # w[0-3] S0
    (1.0, 10.0), (0.01, 5.0), (0.01, 10.0), (0.001, 1.0),     # w[4-7] D0 + difficulty
    (0.01, 10.0), (0.01, 1.0), (0.01, 5.0),                     # w[8-10] recall stability
    (0.01, 10.0), (0.001, 1.0), (0.01, 2.0), (0.01, 5.0),      # w[11-14] forget stability
    (0.01, 5.0), (0.5, 5.0),                                      # w[15-16] hard/easy
    (0.01, 5.0), (0.01, 2.0), (0.001, 1.0), (0.01, 1.0),       # w[17-20] short-term + decay
]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _binary_cross_entropy(predicted: float, actual: float) -> float:
    eps = 1e-7
    predicted = _clamp(predicted, eps, 1.0 - eps)
    if actual >= 1:
        return -math.log(predicted)
    else:
        return -math.log(1.0 - predicted)


def _simulate_and_evaluate(w_tuple: tuple, reviews: List[dict]) -> float:
    """使用 Py-FSRS Scheduler 模拟复习序列，计算 BCE 损失"""
    try:
        w = list(w_tuple)
        scheduler = Scheduler(parameters=w, desired_retention=0.9)
    except Exception:
        return 999.0

    total_loss = 0.0
    count = 0

    for card_id, card_reviews in reviews.items():
        card = PyFSCard()
        prev_review_time = None

        for rev in card_reviews:
            rating_val = rev['rating']
            elapsed_days = rev.get('elapsed_days', 0)

            try:
                rating_enum = Rating(rating_val)
            except ValueError:
                continue

            if prev_review_time is not None and card.stability is not None and elapsed_days > 0:
                ret = scheduler.get_card_retrievability(card, prev_review_time + timedelta(days=elapsed_days))
                actual = 1.0 if rating_val > 1 else 0.0
                total_loss += _binary_cross_entropy(ret, actual)
                count += 1

            review_dt = datetime.now(timezone.utc)
            if prev_review_time is not None and elapsed_days > 0:
                review_dt = prev_review_time + timedelta(days=elapsed_days)

            try:
                card, _ = scheduler.review_card(card, rating_enum, review_dt)
            except Exception:
                break

            prev_review_time = review_dt

    return total_loss / max(count, 1)


def fit_fsrs_params(w: List[float], reviews_raw: List[dict],
                    epochs: int = 5, lr: float = 0.01) -> Tuple[List[float], List[float]]:
    """使用有限差分梯度下降拟合 FSRS 参数"""
    # 按 card_id 分组
    card_reviews: Dict[str, List[dict]] = {}
    for rev in reviews_raw:
        cid = rev.get('card_id', 'unknown')
        if cid not in card_reviews:
            card_reviews[cid] = []
        card_reviews[cid].append(rev)

    if not card_reviews:
        return w.copy(), []

    w_current = w.copy()
    loss_history = []
    eps = 0.001

    for epoch in range(epochs):
        base_loss = _simulate_and_evaluate(tuple(w_current), card_reviews)
        loss_history.append(base_loss)

        gradients = [0.0] * len(w_current)
        for i in range(len(w_current)):
            w_plus = w_current.copy()
            w_minus = w_current.copy()
            w_plus[i] += eps
            w_minus[i] -= eps
            loss_plus = _simulate_and_evaluate(tuple(w_plus), card_reviews)
            loss_minus = _simulate_and_evaluate(tuple(w_minus), card_reviews)
            gradients[i] = (loss_plus - loss_minus) / (2 * eps)

        for i in range(len(w_current)):
            grad = _clamp(gradients[i], -1.0, 1.0)
            w_current[i] -= lr * grad
            low, high = PARAM_BOUNDS[i]
            w_current[i] = _clamp(w_current[i], low, high)

    return w_current, loss_history


# ============================================================
# FSRS 数据库（SQLite）— 使用 Py-FSRS 调度引擎
# ============================================================

class FSRSDatabase:
    """FSRS SQLite 数据库（支持多用户，基于 Py-FSRS 调度引擎）"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cards (
                card_id TEXT NOT NULL,
                card_type TEXT NOT NULL DEFAULT 'sentence',
                user_id TEXT NOT NULL DEFAULT 'default',
                difficulty REAL NOT NULL DEFAULT 0,
                stability REAL NOT NULL DEFAULT 0,
                state INTEGER NOT NULL DEFAULT 0,
                step INTEGER,
                due REAL NOT NULL DEFAULT 0,
                last_review REAL NOT NULL DEFAULT 0,
                reps INTEGER NOT NULL DEFAULT 0,
                lapses INTEGER NOT NULL DEFAULT 0,
                scheduled_days REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (card_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS review_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT 'default',
                rating INTEGER NOT NULL,
                state INTEGER NOT NULL,
                due REAL NOT NULL,
                review_time REAL NOT NULL,
                elapsed_days REAL NOT NULL DEFAULT 0,
                review_duration REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_fsrs_params (
                user_id TEXT PRIMARY KEY,
                params_json TEXT NOT NULL,
                fit_count INTEGER NOT NULL DEFAULT 0,
                last_fit_time REAL NOT NULL DEFAULT 0,
                desired_retention REAL NOT NULL DEFAULT 0.9,
                learning_steps TEXT NOT NULL DEFAULT '[1,10]',
                relearning_steps TEXT NOT NULL DEFAULT '[10]',
                maximum_interval REAL NOT NULL DEFAULT 36500,
                new_per_day INTEGER NOT NULL DEFAULT 5
            );

            CREATE TABLE IF NOT EXISTS study_streaks (
                user_id TEXT PRIMARY KEY,
                current_streak INTEGER NOT NULL DEFAULT 0,
                longest_streak INTEGER NOT NULL DEFAULT 0,
                last_study_date TEXT NOT NULL DEFAULT '',
                total_study_days INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS daily_goals (
                user_id TEXT NOT NULL,
                date TEXT NOT NULL,
                target_reviews INTEGER NOT NULL DEFAULT 20,
                completed_reviews INTEGER NOT NULL DEFAULT 0,
                target_new INTEGER NOT NULL DEFAULT 5,
                completed_new INTEGER NOT NULL DEFAULT 0,
                target_minutes INTEGER NOT NULL DEFAULT 15,
                actual_minutes REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, date)
            );

            CREATE TABLE IF NOT EXISTS word_bookmarks (
                user_id TEXT NOT NULL,
                word TEXT NOT NULL,
                added_at REAL NOT NULL,
                notes TEXT DEFAULT '',
                PRIMARY KEY (user_id, word)
            );

            CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due);
            CREATE INDEX IF NOT EXISTS idx_cards_state ON cards(state);
            CREATE INDEX IF NOT EXISTS idx_cards_user ON cards(user_id);
            CREATE INDEX IF NOT EXISTS idx_cards_user_type ON cards(user_id, card_type);
            CREATE INDEX IF NOT EXISTS idx_review_card ON review_log(card_id);
            CREATE INDEX IF NOT EXISTS idx_review_user ON review_log(user_id);
            CREATE INDEX IF NOT EXISTS idx_review_time ON review_log(user_id, review_time);
        """)

        # 迁移
        self._migrate_add_user_id(conn)
        self._migrate_fix_new_card_due(conn)
        self._migrate_add_review_duration(conn)
        self._migrate_add_step_column(conn)

        conn.commit()
        conn.close()

    def _migrate_add_user_id(self, conn):
        cards_cols = [row[1] for row in conn.execute("PRAGMA table_info(cards)").fetchall()]
        if 'user_id' not in cards_cols:
            conn.execute("ALTER TABLE cards ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'")
            conn.executescript("""
                CREATE TABLE cards_new (
                    card_id TEXT NOT NULL, card_type TEXT NOT NULL DEFAULT 'sentence',
                    user_id TEXT NOT NULL DEFAULT 'default',
                    difficulty REAL NOT NULL DEFAULT 0, stability REAL NOT NULL DEFAULT 0,
                    state INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL DEFAULT 0,
                    last_review REAL NOT NULL DEFAULT 0, reps INTEGER NOT NULL DEFAULT 0,
                    lapses INTEGER NOT NULL DEFAULT 0, scheduled_days REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (card_id, user_id)
                );
                INSERT INTO cards_new SELECT * FROM cards;
                DROP TABLE cards; ALTER TABLE cards_new RENAME TO cards;
            """)
        review_cols = [row[1] for row in conn.execute("PRAGMA table_info(review_log)").fetchall()]
        if 'user_id' not in review_cols:
            conn.execute("ALTER TABLE review_log ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'")
        conn.commit()

    def _migrate_fix_new_card_due(self, conn):
        try:
            conn.execute("UPDATE cards SET due = 0 WHERE state = 0 AND reps = 0 AND due != 0")
            conn.commit()
        except Exception:
            pass

    def _migrate_add_review_duration(self, conn):
        review_cols = [row[1] for row in conn.execute("PRAGMA table_info(review_log)").fetchall()]
        if 'review_duration' not in review_cols:
            try:
                conn.execute("ALTER TABLE review_log ADD COLUMN review_duration REAL NOT NULL DEFAULT 0")
                conn.commit()
            except Exception:
                pass

    def _migrate_add_step_column(self, conn):
        """迁移：添加 step 列（Py-FSRS 需要）"""
        cards_cols = [row[1] for row in conn.execute("PRAGMA table_info(cards)").fetchall()]
        if 'step' not in cards_cols:
            try:
                conn.execute("ALTER TABLE cards ADD COLUMN step INTEGER")
                conn.commit()
            except Exception:
                pass

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    # ============================================================
    # Scheduler 管理
    # ============================================================

    def _get_scheduler(self, user_id: str = "default") -> Scheduler:
        """获取用户的 Py-FSRS Scheduler"""
        user_params = self.get_user_params(user_id)
        learning_steps = tuple(timedelta(minutes=m) for m in user_params["learning_steps"])
        relearning_steps = tuple(timedelta(minutes=m) for m in user_params["relearning_steps"])

        return Scheduler(
            parameters=user_params["params"],
            desired_retention=user_params["desired_retention"],
            learning_steps=learning_steps,
            relearning_steps=relearning_steps,
            maximum_interval=user_params["maximum_interval"],
            enable_fuzzing=True,
        )

    # ============================================================
    # 用户参数管理
    # ============================================================

    def get_user_params(self, user_id: str = "default") -> dict:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT params_json, fit_count, last_fit_time, desired_retention, "
            "learning_steps, relearning_steps, maximum_interval, new_per_day "
            "FROM user_fsrs_params WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.close()

        if row:
            return {
                "params": json.loads(row[0]),
                "fit_count": row[1],
                "last_fit_time": row[2],
                "desired_retention": row[3],
                "learning_steps": json.loads(row[4]),
                "relearning_steps": json.loads(row[5]),
                "maximum_interval": row[6],
                "new_per_day": row[7],
            }
        else:
            return {
                "params": list(DEFAULT_FSRS_PARAMS),
                "fit_count": 0,
                "last_fit_time": 0,
                "desired_retention": DEFAULT_DESIRED_RETENTION,
                "learning_steps": list(DEFAULT_LEARNING_STEPS),
                "relearning_steps": list(DEFAULT_RELEARNING_STEPS),
                "maximum_interval": DEFAULT_MAXIMUM_INTERVAL,
                "new_per_day": DEFAULT_NEW_PER_DAY,
            }

    def set_user_params(self, user_id: str, params_dict: dict):
        current = self.get_user_params(user_id)
        for key in ["params", "desired_retention", "learning_steps", "relearning_steps",
                     "maximum_interval", "new_per_day"]:
            if key in params_dict:
                current[key] = params_dict[key]

        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO user_fsrs_params
            (user_id, params_json, fit_count, last_fit_time, desired_retention,
             learning_steps, relearning_steps, maximum_interval, new_per_day)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, json.dumps(current["params"]), current["fit_count"],
              current["last_fit_time"], current["desired_retention"],
              json.dumps(current["learning_steps"]), json.dumps(current["relearning_steps"]),
              current["maximum_interval"], current["new_per_day"]))
        conn.commit()
        conn.close()

    def get_scheduler(self, user_id: str = "default"):
        """兼容旧接口"""
        return self._get_scheduler(user_id)

    def fit_params(self, user_id: str = "default") -> dict:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT card_id, rating, elapsed_days, review_time "
            "FROM review_log WHERE user_id = ? ORDER BY card_id, review_time ASC",
            (user_id,)
        ).fetchall()
        conn.close()

        if len(rows) < 30:
            return {"success": False, "fit_count": 0, "loss_before": 0, "loss_after": 0,
                    "epochs": 0, "message": f"复习记录不足30条（当前{len(rows)}条），无法拟合"}

        # 构建复习序列
        reviews = [{"card_id": r[0], "rating": r[1], "elapsed_days": r[2], "review_time": r[3]} for r in rows]

        user_params = self.get_user_params(user_id)
        w_init = user_params["params"]

        try:
            base_loss = _simulate_and_evaluate(tuple(w_init),
                                                {cid: [r for r in reviews if r['card_id'] == cid]
                                                 for cid in set(r['card_id'] for r in reviews)})
            w_fitted, loss_history = fit_fsrs_params(w_init, reviews, epochs=5, lr=0.01)
            loss_after = loss_history[-1] if loss_history else base_loss
        except Exception as e:
            return {"success": False, "fit_count": user_params["fit_count"],
                    "loss_before": 0, "loss_after": 0, "epochs": 0,
                    "message": f"拟合失败: {str(e)}"}

        user_params["params"] = w_fitted
        user_params["fit_count"] += 1
        user_params["last_fit_time"] = time.time()

        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO user_fsrs_params
            (user_id, params_json, fit_count, last_fit_time, desired_retention,
             learning_steps, relearning_steps, maximum_interval, new_per_day)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, json.dumps(user_params["params"]), user_params["fit_count"],
              user_params["last_fit_time"], user_params["desired_retention"],
              json.dumps(user_params["learning_steps"]), json.dumps(user_params["relearning_steps"]),
              user_params["maximum_interval"], user_params["new_per_day"]))
        conn.commit()
        conn.close()

        return {"success": True, "fit_count": user_params["fit_count"],
                "loss_before": round(base_loss, 4), "loss_after": round(loss_after, 4),
                "epochs": 5, "message": f"拟合完成，损失从 {base_loss:.4f} 降至 {loss_after:.4f}"}

    # ============================================================
    # 卡片管理
    # ============================================================

    def ensure_card(self, card_id: str, card_type: str = "sentence", user_id: str = "default"):
        conn = self._get_conn()
        row = conn.execute(
            "SELECT card_id FROM cards WHERE card_id = ? AND user_id = ?",
            (card_id, user_id)
        ).fetchone()
        if not row:
            now = time.time()
            conn.execute(
                "INSERT INTO cards (card_id, card_type, user_id, due, created_at) VALUES (?, ?, ?, 0, ?)",
                (card_id, card_type, user_id, now)
            )
            conn.commit()
        conn.close()

    def get_card(self, card_id: str, user_id: str = "default") -> Optional[dict]:
        """获取卡片（返回 dict，兼容旧接口）"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT card_id, difficulty, stability, state, step, due, last_review, reps, lapses, scheduled_days, created_at "
            "FROM cards WHERE card_id = ? AND user_id = ?",
            (card_id, user_id)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "card_id": row[0], "difficulty": row[1], "stability": row[2],
            "state": row[3], "step": row[4], "due": row[5], "last_review": row[6],
            "reps": row[7], "lapses": row[8], "scheduled_days": row[9], "created_at": row[10],
            "state_name": STATE_NAMES[row[3]] if 0 <= row[3] <= 3 else "unknown",
        }

    def get_card_info(self, card_id: str, user_id: str = "default") -> Optional[dict]:
        """获取卡片详细信息（含可回忆率）"""
        card_data = self.get_card(card_id, user_id)
        if not card_data:
            return None

        scheduler = self._get_scheduler(user_id)
        ret = 0.0
        if card_data["state"] != NEW and card_data["stability"] and card_data["stability"] > 0:
            try:
                pyfsrs_card = _make_pyfsrs_card(
                    state_int=card_data["state"],
                    difficulty=card_data["difficulty"],
                    stability=card_data["stability"],
                    due_ts=card_data["due"],
                    last_review_ts=card_data["last_review"],
                    step=card_data.get("step")
                )
                now = datetime.now(timezone.utc)
                ret = scheduler.get_card_retrievability(pyfsrs_card, now)
            except Exception:
                ret = 0.0

        return {
            "card_id": card_data["card_id"],
            "state": card_data["state"],
            "state_name": card_data["state_name"],
            "difficulty": round(card_data["difficulty"], 2),
            "stability": round(card_data["stability"], 2),
            "retrievability": round(ret, 4),
            "due": card_data["due"],
            "scheduled_days": round(card_data["scheduled_days"], 1),
            "reps": card_data["reps"],
            "lapses": card_data["lapses"],
            "last_review": card_data["last_review"],
        }

    def review_card(self, card_id: str, rating: int, card_type: str = "sentence",
                    user_id: str = "default", review_duration: float = 0) -> dict:
        """复习卡片 — 使用 Py-FSRS Scheduler"""
        self.ensure_card(card_id, card_type, user_id)
        card_data = self.get_card(card_id, user_id)
        now = time.time()
        now_dt = datetime.now(timezone.utc)

        old_state = card_data["state"]

        # 构建 Py-FSRS Card
        if card_data["state"] == NEW:
            # 新卡片
            pyfsrs_card = PyFSCard()
        else:
            pyfsrs_card = _make_pyfsrs_card(
                state_int=card_data["state"],
                difficulty=card_data["difficulty"],
                stability=card_data["stability"],
                due_ts=card_data["due"],
                last_review_ts=card_data["last_review"],
                step=card_data.get("step")
            )

        # 使用 Py-FSRS Scheduler 评分
        scheduler = self._get_scheduler(user_id)
        rating_enum = Rating(rating)
        new_card, review_log = scheduler.review_card(pyfsrs_card, rating_enum, now_dt)

        # 计算新状态和间隔
        new_state = _pyfsrs_state_to_int(new_card.state)
        new_due = _datetime_to_ts(new_card.due)
        new_last_review = _datetime_to_ts(new_card.last_review)

        # 计算实际间隔天数
        if new_last_review > 0 and card_data["last_review"] > 0:
            elapsed_days = (new_last_review - card_data["last_review"]) / 86400.0
        else:
            elapsed_days = 0.0

        # 计算调度间隔
        if new_state == LEARNING or new_state == RELEARNING:
            # LEARNING/RELEARNING: 间隔很短（分钟级）
            scheduled_days = (new_due - now) / 86400.0 if new_due > now else 0.0
        else:
            scheduled_days = (new_due - now) / 86400.0 if new_due > now else 0.0

        # 更新 lapses
        new_lapses = card_data["lapses"]
        if rating == 1 and old_state in (REVIEW,):
            new_lapses += 1

        new_reps = card_data["reps"] + 1

        # 写入数据库
        conn = self._get_conn()
        conn.execute("""
            UPDATE cards SET difficulty=?, stability=?, state=?, step=?, due=?, last_review=?,
            reps=?, lapses=?, scheduled_days=? WHERE card_id=? AND user_id=?
        """, (new_card.difficulty or 0, new_card.stability or 0, new_state,
              new_card.step, new_due, new_last_review,
              new_reps, new_lapses, scheduled_days, card_id, user_id))

        conn.execute("""
            INSERT INTO review_log (card_id, user_id, rating, state, due, review_time, elapsed_days, review_duration)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (card_id, user_id, rating, old_state, new_due, now, elapsed_days, review_duration))

        conn.commit()
        conn.close()

        # 更新连续天数
        self._update_streak(user_id)

        # 更新每日目标
        self._update_daily_goal(user_id, is_new=(old_state == NEW))

        # 检查自动拟合
        self._check_auto_fit(user_id)

        # 计算可回忆率
        ret = 0.0
        if new_card.stability:
            try:
                ret = scheduler.get_card_retrievability(new_card, now_dt)
            except Exception:
                pass

        due_dt = _ts_to_datetime(new_due)
        return {
            "card_id": card_id,
            "rating": rating,
            "state": new_state,
            "state_name": STATE_NAMES[new_state],
            "difficulty": round(new_card.difficulty or 0, 2),
            "stability": round(new_card.stability or 0, 2),
            "retrievability": round(ret, 4),
            "scheduled_days": round(scheduled_days, 1),
            "due": due_dt.isoformat() if due_dt else "",
            "reps": new_reps,
            "lapses": new_lapses,
            "next_review_hint": self._format_interval_hint(scheduled_days),
        }

    def _format_interval_hint(self, days: float) -> str:
        """格式化下次复习时间提示"""
        if days < 1/60:
            return "不到1分钟"
        elif days < 1:
            minutes = int(days * 1440)
            if minutes < 60:
                return f"{minutes}分钟后"
            else:
                return f"{minutes // 60}小时后"
        elif days < 30:
            return f"{int(days)}天后"
        elif days < 365:
            return f"{int(days / 30)}个月后"
        else:
            return f"{int(days / 365)}年后"

    def _check_auto_fit(self, user_id: str = "default"):
        try:
            conn = self._get_conn()
            total_reviews = conn.execute(
                "SELECT COUNT(*) FROM review_log WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            conn.close()

            fit_interval = 30
            try:
                from auth_service import get_auth_service
                auth = get_auth_service()
                profile = auth.get_profile(user_id)
                if profile and profile.get("settings"):
                    fit_interval = profile["settings"].get("fsrs_fit_interval", 30)
            except Exception:
                pass

            if total_reviews > 0 and total_reviews % fit_interval == 0:
                user_params = self.get_user_params(user_id)
                if user_params["last_fit_time"] > 0:
                    if time.time() - user_params["last_fit_time"] < 3600:
                        return
                try:
                    self.fit_params(user_id)
                except Exception:
                    pass
        except Exception:
            pass

    # ============================================================
    # 卡片查询
    # ============================================================

    def get_due_cards(self, card_type: str = "sentence", user_id: str = "default",
                      limit: int = 20, exclude_card_ids: List[str] = None) -> List[dict]:
        now = time.time()
        conn = self._get_conn()

        query = ("SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
                 "FROM cards WHERE card_type=? AND user_id=? AND state != 0 AND due <= ? AND due > 0 ")
        params = [card_type, user_id, now]

        if exclude_card_ids:
            placeholders = ','.join(['?'] * len(exclude_card_ids))
            query += f"AND card_id NOT IN ({placeholders}) "
            params.extend(exclude_card_ids)

        query += "ORDER BY due ASC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, tuple(params)).fetchall()
        conn.close()

        return [{"card_id": r[0], "state": r[1],
                 "state_name": STATE_NAMES[r[1]] if 0 <= r[1] <= 3 else "unknown",
                 "due": r[2], "scheduled_days": r[3], "reps": r[4],
                 "difficulty": round(r[5], 2), "stability": round(r[6], 2)} for r in rows]

    def get_due_count(self, card_type: str = "sentence", user_id: str = "default") -> int:
        now = time.time()
        conn = self._get_conn()
        count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type=? AND user_id=? AND state != 0 AND due <= ? AND due > 0",
            (card_type, user_id, now)
        ).fetchone()[0]
        conn.close()
        return count

    def get_pending_review_count(self, card_type: str = "word", user_id: str = "default") -> int:
        now = time.time()
        conn = self._get_conn()
        total = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type=? AND user_id=?", (card_type, user_id)
        ).fetchone()[0]
        new_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type=? AND user_id=? AND state=0", (card_type, user_id)
        ).fetchone()[0]
        mastered_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type=? AND user_id=? AND state=2 AND due > ? AND scheduled_days >= 3",
            (card_type, user_id, now)
        ).fetchone()[0]
        conn.close()
        return max(0, total - new_count - mastered_count)

    def get_total_reviewable_count(self, card_type: str = "word", user_id: str = "default") -> int:
        now = time.time()
        conn = self._get_conn()
        total = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type=? AND user_id=?", (card_type, user_id)
        ).fetchone()[0]
        mastered_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type=? AND user_id=? AND state=2 AND due > ? AND scheduled_days >= 3",
            (card_type, user_id, now)
        ).fetchone()[0]
        conn.close()
        return max(0, total - mastered_count)

    def get_next_word_for_practice(self, user_id: str = "default", new_ratio: float = 0.7,
                                    exclude_card_ids: List[str] = None) -> Optional[dict]:
        """获取下一个练习单词（FSRS驱动，新词优先，穿插到期复习）
        
        策略（参考 Anki 调度 + Py-FSRS）：
        - 新词占约 70%，到期复习占约 30%
        - LEARNING/RELEARNING 不参与选择（Py-FSRS 的 learning_steps 导致极短间隔）
        - 只有真正到期的 REVIEW 卡片才作为复习候选
        - 已掌握的不推荐
        """
        now = time.time()
        conn = self._get_conn()

        query = ("SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
                 "FROM cards WHERE card_type='word' AND user_id=? "
                 "AND NOT (state=2 AND due > ? AND scheduled_days >= 3) "
                 "AND state NOT IN (1, 3) ")
        params = [user_id, now]

        if exclude_card_ids:
            placeholders = ','.join(['?'] * len(exclude_card_ids))
            query += f"AND card_id NOT IN ({placeholders}) "
            params.extend(exclude_card_ids)

        query += ("ORDER BY CASE WHEN state=0 THEN 0 ELSE 1 END, "
                  "CASE WHEN state != 0 AND due <= ? THEN 0 ELSE 1 END, "
                  "difficulty DESC, reps ASC")
        params.append(now)

        rows = conn.execute(query, tuple(params)).fetchall()
        conn.close()

        if not rows:
            return None

        new_cards = [r for r in rows if r[1] == 0]
        due_review_cards = [r for r in rows if r[1] == 2 and r[2] <= now and r[2] > 0]
        unmastered_future_cards = [r for r in rows if r[1] == 2 and r[2] > now and r[3] < 3]

        candidates = []
        weights = []
        for r in new_cards:
            candidates.append(r)
            weights.append(7.0)
        for r in due_review_cards:
            candidates.append(r)
            weights.append(3.0)
        for r in unmastered_future_cards:
            candidates.append(r)
            weights.append(1.0)

        if not candidates:
            return None

        total_weight = sum(weights)
        rand = random.random() * total_weight
        cumulative = 0
        chosen = candidates[0]
        for c, w in zip(candidates, weights):
            cumulative += w
            if rand <= cumulative:
                chosen = c
                break

        state = chosen[1]
        return {
            "card_id": chosen[0],
            "type": "new" if state == 0 else "review",
            "state": state,
            "state_name": STATE_NAMES[state] if 0 <= state <= 3 else "unknown",
            "due": chosen[2],
            "scheduled_days": chosen[3],
            "reps": chosen[4],
            "difficulty": round(chosen[5], 2),
            "stability": round(chosen[6], 2),
        }

    def get_new_cards(self, card_type: str = "sentence", user_id: str = "default", limit: int = 10) -> List[str]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT card_id FROM cards WHERE card_type=? AND user_id=? AND state=0 ORDER BY created_at ASC LIMIT ?",
            (card_type, user_id, limit)
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]

    def get_new_card_count(self, card_type: str = "sentence", user_id: str = "default") -> int:
        conn = self._get_conn()
        count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type=? AND user_id=? AND state=0",
            (card_type, user_id)
        ).fetchone()[0]
        conn.close()
        return count

    def get_review_queue(self, card_type: str = "sentence", user_id: str = "default",
                         new_per_day: int = 5, review_limit: int = 50,
                         exclude_card_ids: List[str] = None) -> List[dict]:
        now = time.time()
        conn = self._get_conn()

        review_query = ("SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
                        "FROM cards WHERE card_type=? AND user_id=? AND state != 0 AND due <= ? AND due > 0 ")
        review_params = [card_type, user_id, now]
        if exclude_card_ids:
            placeholders = ','.join(['?'] * len(exclude_card_ids))
            review_query += f"AND card_id NOT IN ({placeholders}) "
            review_params.extend(exclude_card_ids)
        review_query += "ORDER BY due ASC LIMIT ?"
        review_params.append(review_limit)

        review_rows = conn.execute(review_query, tuple(review_params)).fetchall()
        new_rows = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type=? AND user_id=? AND state = 0 ORDER BY created_at ASC LIMIT ?",
            (card_type, user_id, new_per_day)
        ).fetchall()
        conn.close()

        queue = []
        for r in review_rows:
            queue.append({"card_id": r[0], "type": "review", "state": r[1],
                          "state_name": STATE_NAMES[r[1]] if 0 <= r[1] <= 3 else "unknown",
                          "due": r[2], "scheduled_days": r[3], "reps": r[4]})
        for r in new_rows:
            queue.append({"card_id": r[0], "type": "new", "state": 0,
                          "state_name": "new", "due": r[2], "scheduled_days": r[3], "reps": r[4]})
        return queue

    def get_next_word_for_review(self, user_id: str = "default") -> Optional[dict]:
        now = time.time()
        conn = self._get_conn()

        # 1. 到期复习
        row = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type='word' AND user_id=? AND state != 0 AND due <= ? AND due > 0 "
            "ORDER BY due ASC, difficulty DESC LIMIT 1", (user_id, now)
        ).fetchone()
        if row:
            conn.close()
            return {"card_id": row[0], "type": "review", "state": row[1],
                    "state_name": STATE_NAMES[row[1]] if 0 <= row[1] <= 3 else "unknown",
                    "due": row[2], "scheduled_days": row[3], "reps": row[4],
                    "difficulty": round(row[5], 2), "stability": round(row[6], 2)}

        # 2. 未掌握 REVIEW
        row = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type='word' AND user_id=? AND state = 2 "
            "AND NOT (due > ? AND scheduled_days >= 3) ORDER BY scheduled_days ASC, difficulty DESC LIMIT 1",
            (user_id, now)
        ).fetchone()
        if row:
            conn.close()
            return {"card_id": row[0], "type": "review", "state": row[1],
                    "state_name": STATE_NAMES[row[1]] if 0 <= row[1] <= 3 else "unknown",
                    "due": row[2], "scheduled_days": row[3], "reps": row[4],
                    "difficulty": round(row[5], 2), "stability": round(row[6], 2)}

        # 3. 新词
        row = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type='word' AND user_id=? AND state = 0 ORDER BY created_at ASC LIMIT 1",
            (user_id,)
        ).fetchone()
        conn.close()
        if row:
            return {"card_id": row[0], "type": "new", "state": 0,
                    "state_name": "new", "due": row[2], "scheduled_days": row[3],
                    "reps": row[4], "difficulty": round(row[5], 2), "stability": round(row[6], 2)}
        return None

    # ============================================================
    # 统计
    # ============================================================

    def get_word_review_stats(self, user_id: str = "default") -> dict:
        now = time.time()
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM cards WHERE card_type='word' AND user_id=?", (user_id,)).fetchone()[0]
        new_count = conn.execute("SELECT COUNT(*) FROM cards WHERE card_type='word' AND user_id=? AND state=0", (user_id,)).fetchone()[0]
        mastered_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type='word' AND user_id=? AND state=2 AND due > ? AND scheduled_days >= 3",
            (user_id, now)).fetchone()[0]
        learning_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type='word' AND user_id=? AND state IN (1, 3)", (user_id,)).fetchone()[0]
        due_now_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type='word' AND user_id=? AND state != 0 AND due <= ? AND due > 0",
            (user_id, now)).fetchone()[0]
        conn.close()
        due_count = max(0, total - mastered_count - new_count)
        return {"total": total, "new": new_count, "due": due_count,
                "due_now": due_now_count, "learning": learning_count, "mastered": mastered_count}

    def get_stats(self, user_id: str = "default") -> dict:
        conn = self._get_conn()
        now = time.time()

        total = conn.execute("SELECT COUNT(*) FROM cards WHERE user_id=?", (user_id,)).fetchone()[0]
        new = conn.execute("SELECT COUNT(*) FROM cards WHERE user_id=? AND state=0", (user_id,)).fetchone()[0]
        learning = conn.execute("SELECT COUNT(*) FROM cards WHERE user_id=? AND state=1", (user_id,)).fetchone()[0]
        review = conn.execute("SELECT COUNT(*) FROM cards WHERE user_id=? AND state=2", (user_id,)).fetchone()[0]
        relearning = conn.execute("SELECT COUNT(*) FROM cards WHERE user_id=? AND state=3", (user_id,)).fetchone()[0]
        due_now = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE user_id=? AND state != 0 AND due <= ? AND due > 0",
            (user_id, now)).fetchone()[0]

        total_reviews = conn.execute("SELECT COUNT(*) FROM review_log WHERE user_id=?", (user_id,)).fetchone()[0]
        today_start = now - (now % 86400)
        today_reviews = conn.execute(
            "SELECT COUNT(*) FROM review_log WHERE user_id=? AND review_time >= ?", (user_id, today_start)
        ).fetchone()[0]
        avg_rating = conn.execute(
            "SELECT AVG(rating) FROM review_log WHERE user_id=? AND review_time >= ?", (user_id, today_start)
        ).fetchone()[0] or 0

        user_params = self.get_user_params(user_id)
        conn.close()

        return {
            "total_cards": total, "new": new, "learning": learning,
            "review": review, "relearning": relearning, "due_now": due_now,
            "total_reviews": total_reviews, "today_reviews": today_reviews,
            "today_avg_rating": round(avg_rating, 2),
            "fsrs_version": "6.0", "fsrs_engine": "Py-FSRS",
            "fsrs_params_count": len(user_params["params"]),
            "fsrs_fit_count": user_params["fit_count"],
            "fsrs_last_fit_time": user_params["last_fit_time"],
            "fsrs_desired_retention": user_params["desired_retention"],
        }

    # ============================================================
    # 学习连续天数（Streak）
    # ============================================================

    def _update_streak(self, user_id: str = "default"):
        """更新用户的学习连续天数"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn = self._get_conn()

        row = conn.execute(
            "SELECT current_streak, longest_streak, last_study_date, total_study_days "
            "FROM study_streaks WHERE user_id=?", (user_id,)
        ).fetchone()

        if not row:
            conn.execute(
                "INSERT INTO study_streaks (user_id, current_streak, longest_streak, last_study_date, total_study_days) "
                "VALUES (?, 1, 1, ?, 1)", (user_id, today)
            )
        else:
            current_streak, longest_streak, last_date, total_days = row
            if last_date == today:
                # 今天已记录，不更新
                pass
            elif last_date == (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"):
                # 连续
                current_streak += 1
                longest_streak = max(longest_streak, current_streak)
                conn.execute(
                    "UPDATE study_streaks SET current_streak=?, longest_streak=?, last_study_date=?, total_study_days=? "
                    "WHERE user_id=?", (current_streak, longest_streak, today, total_days + 1, user_id)
                )
            else:
                # 断了
                current_streak = 1
                conn.execute(
                    "UPDATE study_streaks SET current_streak=?, last_study_date=?, total_study_days=? "
                    "WHERE user_id=?", (1, today, total_days + 1, user_id)
                )

        conn.commit()
        conn.close()

    def get_streak(self, user_id: str = "default") -> dict:
        """获取连续天数信息"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT current_streak, longest_streak, last_study_date, total_study_days "
            "FROM study_streaks WHERE user_id=?", (user_id,)
        ).fetchone()
        conn.close()

        if not row:
            return {"current": 0, "longest": 0, "last_date": "", "total_days": 0}

        return {"current": row[0], "longest": row[1], "last_date": row[2], "total_days": row[3]}

    # ============================================================
    # 每日目标
    # ============================================================

    def _update_daily_goal(self, user_id: str = "default", is_new: bool = False):
        """更新每日目标进度"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn = self._get_conn()

        row = conn.execute(
            "SELECT completed_reviews, completed_new FROM daily_goals WHERE user_id=? AND date=?",
            (user_id, today)
        ).fetchone()

        if not row:
            # 获取用户目标设置
            target_reviews = 20
            target_new = 5
            target_minutes = 15
            try:
                from auth_service import get_auth_service
                auth = get_auth_service()
                profile = auth.get_profile(user_id)
                if profile and profile.get("settings"):
                    s = profile["settings"]
                    target_reviews = s.get("daily_review_target", 20)
                    target_new = s.get("daily_new_target", 5)
                    target_minutes = s.get("daily_minute_target", 15)
            except Exception:
                pass

            conn.execute(
                "INSERT INTO daily_goals (user_id, date, target_reviews, completed_reviews, "
                "target_new, completed_new, target_minutes, actual_minutes) "
                "VALUES (?, ?, ?, 1, ?, 0, ?, 0)",
                (user_id, today, target_reviews, target_new, target_minutes)
            )
        else:
            completed_reviews = row[0] + 1
            completed_new = row[1] + (1 if is_new else 0)
            conn.execute(
                "UPDATE daily_goals SET completed_reviews=?, completed_new=? WHERE user_id=? AND date=?",
                (completed_reviews, completed_new, user_id, today)
            )

        conn.commit()
        conn.close()

    def get_daily_goal(self, user_id: str = "default", date: str = None) -> dict:
        """获取每日目标进度"""
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn = self._get_conn()
        row = conn.execute(
            "SELECT target_reviews, completed_reviews, target_new, completed_new, target_minutes, actual_minutes "
            "FROM daily_goals WHERE user_id=? AND date=?", (user_id, date)
        ).fetchone()
        conn.close()

        if not row:
            return {"date": date, "target_reviews": 20, "completed_reviews": 0,
                    "target_new": 5, "completed_new": 0, "target_minutes": 15,
                    "actual_minutes": 0, "review_progress": 0.0, "new_progress": 0.0}

        return {"date": date, "target_reviews": row[0], "completed_reviews": row[1],
                "target_new": row[2], "completed_new": row[3], "target_minutes": row[4],
                "actual_minutes": row[5],
                "review_progress": round(min(1.0, row[1] / max(row[0], 1)), 2),
                "new_progress": round(min(1.0, row[3] / max(row[2], 1)), 2)}

    # ============================================================
    # 单词收藏/生词本
    # ============================================================

    def bookmark_word(self, user_id: str, word: str, notes: str = "") -> dict:
        conn = self._get_conn()
        now = time.time()
        conn.execute(
            "INSERT OR REPLACE INTO word_bookmarks (user_id, word, added_at, notes) VALUES (?, ?, ?, ?)",
            (user_id, word, now, notes)
        )
        conn.commit()
        conn.close()
        return {"word": word, "bookmarked": True}

    def unbookmark_word(self, user_id: str, word: str) -> dict:
        conn = self._get_conn()
        conn.execute("DELETE FROM word_bookmarks WHERE user_id=? AND word=?", (user_id, word))
        conn.commit()
        conn.close()
        return {"word": word, "bookmarked": False}

    def get_bookmarked_words(self, user_id: str = "default") -> List[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT word, added_at, notes FROM word_bookmarks WHERE user_id=? ORDER BY added_at DESC",
            (user_id,)
        ).fetchall()
        conn.close()
        return [{"word": r[0], "added_at": r[1], "notes": r[2]} for r in rows]

    def is_word_bookmarked(self, user_id: str, word: str) -> bool:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT 1 FROM word_bookmarks WHERE user_id=? AND word=?", (user_id, word)
        ).fetchone()
        conn.close()
        return row is not None

    # ============================================================
    # 复习预报（Forecast）
    # ============================================================

    def get_forecast(self, user_id: str = "default", days: int = 30) -> List[dict]:
        """获取未来 N 天的复习预报"""
        now = time.time()
        conn = self._get_conn()

        # 获取所有非新卡片
        rows = conn.execute(
            "SELECT card_id, state, due, scheduled_days FROM cards "
            "WHERE user_id=? AND state != 0 AND due > 0",
            (user_id,)
        ).fetchall()
        conn.close()

        # 按天统计
        forecast = {}
        for day_offset in range(days):
            day_start = now + day_offset * 86400
            day_end = day_start + 86400
            date_str = datetime.fromtimestamp(day_start, tz=timezone.utc).strftime("%Y-%m-%d")

            count = 0
            new_count = 0
            review_count = 0
            for r in rows:
                if day_start <= r[2] < day_end:
                    count += 1
                    if r[1] == 0:
                        new_count += 1
                    else:
                        review_count += 1

            forecast[date_str] = {"date": date_str, "total": count,
                                   "new": new_count, "review": review_count}

        return list(forecast.values())

    # ============================================================
    # 数据导出
    # ============================================================

    def export_user_data(self, user_id: str = "default") -> dict:
        """导出用户所有学习数据"""
        conn = self._get_conn()

        cards = conn.execute(
            "SELECT card_id, card_type, difficulty, stability, state, due, last_review, "
            "reps, lapses, scheduled_days, created_at FROM cards WHERE user_id=?",
            (user_id,)
        ).fetchall()

        reviews = conn.execute(
            "SELECT card_id, rating, state, due, review_time, elapsed_days, review_duration "
            "FROM review_log WHERE user_id=? ORDER BY review_time ASC",
            (user_id,)
        ).fetchall()

        bookmarks = conn.execute(
            "SELECT word, added_at, notes FROM word_bookmarks WHERE user_id=?",
            (user_id,)
        ).fetchall()

        streak = conn.execute(
            "SELECT current_streak, longest_streak, last_study_date, total_study_days "
            "FROM study_streaks WHERE user_id=?", (user_id,)
        ).fetchone()

        params = self.get_user_params(user_id)

        conn.close()

        return {
            "export_time": time.time(),
            "export_date": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "fsrs_params": params,
            "streak": {"current": streak[0], "longest": streak[1],
                       "last_date": streak[2], "total_days": streak[3]} if streak else None,
            "cards": [{"card_id": c[0], "card_type": c[1], "difficulty": c[2],
                        "stability": c[3], "state": c[4], "due": c[5],
                        "last_review": c[6], "reps": c[7], "lapses": c[8],
                        "scheduled_days": c[9], "created_at": c[10]} for c in cards],
            "reviews": [{"card_id": r[0], "rating": r[1], "state": r[2],
                          "due": r[3], "review_time": r[4], "elapsed_days": r[5],
                          "review_duration": r[6]} for r in reviews],
            "bookmarks": [{"word": b[0], "added_at": b[1], "notes": b[2]} for b in bookmarks],
        }

    def import_user_data(self, user_id: str, data: dict) -> dict:
        """导入用户学习数据"""
        conn = self._get_conn()
        imported_cards = 0
        imported_reviews = 0

        # 导入卡片
        for card in data.get("cards", []):
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO cards (card_id, card_type, user_id, difficulty, stability,
                    state, due, last_review, reps, lapses, scheduled_days, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (card["card_id"], card.get("card_type", "sentence"), user_id,
                      card.get("difficulty", 0), card.get("stability", 0),
                      card.get("state", 0), card.get("due", 0), card.get("last_review", 0),
                      card.get("reps", 0), card.get("lapses", 0), card.get("scheduled_days", 0),
                      card.get("created_at", 0)))
                imported_cards += 1
            except Exception:
                pass

        # 导入复习记录
        for review in data.get("reviews", []):
            try:
                conn.execute("""
                    INSERT INTO review_log (card_id, user_id, rating, state, due, review_time, elapsed_days, review_duration)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (review["card_id"], user_id, review["rating"], review.get("state", 0),
                      review.get("due", 0), review["review_time"], review.get("elapsed_days", 0),
                      review.get("review_duration", 0)))
                imported_reviews += 1
            except Exception:
                pass

        # 导入书签
        for bm in data.get("bookmarks", []):
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO word_bookmarks (user_id, word, added_at, notes) VALUES (?, ?, ?, ?)",
                    (user_id, bm["word"], bm.get("added_at", time.time()), bm.get("notes", ""))
                )
            except Exception:
                pass

        # 导入参数
        if "fsrs_params" in data:
            self.set_user_params(user_id, data["fsrs_params"])

        conn.commit()
        conn.close()

        return {"imported_cards": imported_cards, "imported_reviews": imported_reviews,
                "success": True}


# ============================================================
# 全局实例（单例模式）
# ============================================================

_fsrs_db: Optional[FSRSDatabase] = None


def get_fsrs_db() -> FSRSDatabase:
    global _fsrs_db
    if _fsrs_db is None:
        _fsrs_db = FSRSDatabase()
    return _fsrs_db
