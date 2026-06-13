"""
FSRS 间隔重复算法 + SQLite 持久化（支持多用户）

基于 FSRS-4.5 算法实现，用于句子/单词的复习调度。
Rating: 1=Again, 2=Hard, 3=Good, 4=Easy

关键设计：
- 新卡片的 due 设为 0（远在过去），确保可以被新卡片查询找到
- 但 get_due_cards 和 get_review_queue 区分"真正到期的复习卡片"和"新卡片"
- 到期复习 = state != NEW 且 due <= now
- 新卡片 = state == NEW（due=0 不算到期复习）
- 顺序模式：不因 FSRS 复习打断顺序，FSRS 复习嵌入顺序进度中

多用户支持：cards 和 review_log 表均包含 user_id 字段，
所有查询均按 user_id 过滤。向后兼容：默认 user_id='default'。
"""

import sqlite3
import time
import math
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict

# FSRS 默认参数 (w[0]~w[17])
DEFAULT_FSRS_PARAMS = [
    0.4072, 1.1829, 3.1262, 15.4722, 7.2102, 0.5316, 1.0651, 0.0589,
    0.3498, 1.1168, 0.5772, 0.1140, 0.4985, 0.2928, 2.1207, 0.0,
    0.4506, 0.8500
]

DB_PATH = Path(__file__).parent / "phonos_fsrs.db"


class Card:
    """FSRS 卡片"""
    __slots__ = [
        'card_id', 'difficulty', 'stability', 'retrievability',
        'state', 'due', 'last_review', 'reps', 'lapses',
        'elapsed_days', 'scheduled_days', 'created_at'
    ]

    # State
    NEW = 0
    LEARNING = 1
    REVIEW = 2
    RELEARNING = 3

    def __init__(self, card_id: str):
        self.card_id = card_id
        self.difficulty = 0.0
        self.stability = 0.0
        self.retrievability = 0.0
        self.state = self.NEW
        # 关键修复：新卡片的 due 设为 0，不再用 time.time()
        # 这样 get_due_cards(到期复习) 不会把新卡片算进去
        # 新卡片通过 state=0 来识别，而不是 due 时间
        self.due = 0.0
        self.last_review = 0.0
        self.reps = 0
        self.lapses = 0
        self.elapsed_days = 0
        self.scheduled_days = 0
        self.created_at = time.time()


def _init_decay(w):
    return max(0.01, w[17])


def _init_stability(w, rating: int) -> float:
    return max(0.1, w[rating - 1])


def _init_difficulty(w, rating: int) -> float:
    return min(max(1.0, w[4] - w[5] * (rating - 3)), 10.0)


def _next_difficulty(w, d: float, rating: int) -> float:
    delta = w[5] * (rating - 3)
    new_d = d - delta
    # Mean revert
    w6 = w[6]
    new_d = w6 * _init_difficulty(w, 4) + (1 - w6) * new_d
    return min(max(1.0, new_d), 10.0)


def _next_recall_stability(w, d: float, s: float, r: float, rating: int) -> float:
    hard_penalty = w[15] if rating == 2 else 1.0
    easy_bonus = w[16] if rating == 4 else 1.0
    new_s = s * (1 + math.exp(w[7]) * (11 - d) * (s ** (-w[8])) *
                 (math.exp(w[9] * (1 - r)) - 1) * hard_penalty * easy_bonus)
    return max(0.1, min(new_s, 36500.0))


def _next_forget_stability(w, d: float, s: float, r: float) -> float:
    new_s = w[10] * (d ** (-w[11])) * ((s + 1) ** w[12] - 1) * math.exp(w[13] * (1 - r))
    return max(0.1, min(new_s, s))


def _retrievability(elapsed_days: float, stability: float, decay: float) -> float:
    return (1 + elapsed_days / (9 * stability)) ** (-1 / decay)


def _next_interval(s: float, r: float, decay: float) -> float:
    """计算下次复习间隔（天）"""
    if r <= 0:
        return 1.0
    # 目标可回忆率 0.9
    return max(1.0, 9 * s * (r ** decay - 1))


class FSRSScheduler:
    """FSRS 调度器"""

    def __init__(self, params=None):
        self.w = params or DEFAULT_FSRS_PARAMS
        self.decay = _init_decay(self.w)

    def review(self, card: Card, rating: int, now: float = None) -> Card:
        """对卡片进行复习评分"""
        if now is None:
            now = time.time()

        if card.state == Card.NEW:
            card.stability = _init_stability(self.w, rating)
            card.difficulty = _init_difficulty(self.w, rating)
            # FSRS-4.5: 根据评级设置不同的初始状态
            # Again(1)/Hard(2) → LEARNING, Good(3)/Easy(4) → REVIEW
            if rating >= 3:
                card.state = Card.REVIEW
            else:
                card.state = Card.LEARNING
        else:
            elapsed = max(0, (now - card.last_review) / 86400.0) if card.last_review > 0 else 0
            card.elapsed_days = elapsed

            if card.stability > 0:
                card.retrievability = _retrievability(elapsed, card.stability, self.decay)
            else:
                card.retrievability = 0

            if rating >= 3:  # Good / Easy
                card.stability = _next_recall_stability(
                    self.w, card.difficulty, card.stability, card.retrievability, rating)
                card.difficulty = _next_difficulty(self.w, card.difficulty, rating)
                if card.state == Card.RELEARNING:
                    card.state = Card.REVIEW
                else:
                    card.state = Card.REVIEW
            else:  # Again / Hard
                if rating == 1:
                    card.lapses += 1
                    card.stability = _next_forget_stability(
                        self.w, card.difficulty, card.stability, card.retrievability)
                    card.state = Card.RELEARNING
                else:  # Hard
                    card.stability = _next_recall_stability(
                        self.w, card.difficulty, card.stability, card.retrievability, rating)
                    card.difficulty = _next_difficulty(self.w, card.difficulty, rating)

        card.reps += 1
        card.last_review = now
        card.retrievability = _retrievability(0, card.stability, self.decay)
        card.scheduled_days = _next_interval(card.stability, card.retrievability, self.decay)
        card.due = now + card.scheduled_days * 86400

        return card


class FSRSDatabase:
    """FSRS SQLite 数据库（支持多用户）"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self.scheduler = FSRSScheduler()
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
                elapsed_days REAL NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due);
            CREATE INDEX IF NOT EXISTS idx_cards_state ON cards(state);
            CREATE INDEX IF NOT EXISTS idx_cards_user ON cards(user_id);
            CREATE INDEX IF NOT EXISTS idx_cards_user_type ON cards(user_id, card_type);
            CREATE INDEX IF NOT EXISTS idx_review_card ON review_log(card_id);
            CREATE INDEX IF NOT EXISTS idx_review_user ON review_log(user_id);
        """)
        conn.commit()

        # Migration: add user_id columns if they don't exist
        self._migrate_add_user_id(conn)

        # Migration: 修复旧数据 - 把 due=创建时间 且 state=0 的卡片 due 改为 0
        self._migrate_fix_new_card_due(conn)

        conn.close()

    def _migrate_add_user_id(self, conn):
        """迁移：为旧表添加 user_id 列"""
        # Check cards table
        cards_cols = [row[1] for row in conn.execute("PRAGMA table_info(cards)").fetchall()]
        if 'user_id' not in cards_cols:
            conn.execute("ALTER TABLE cards ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'")
            # Recreate primary key by recreating table
            conn.executescript("""
                CREATE TABLE cards_new (
                    card_id TEXT NOT NULL,
                    card_type TEXT NOT NULL DEFAULT 'sentence',
                    user_id TEXT NOT NULL DEFAULT 'default',
                    difficulty REAL NOT NULL DEFAULT 0,
                    stability REAL NOT NULL DEFAULT 0,
                    state INTEGER NOT NULL DEFAULT 0,
                    due REAL NOT NULL DEFAULT 0,
                    last_review REAL NOT NULL DEFAULT 0,
                    reps INTEGER NOT NULL DEFAULT 0,
                    lapses INTEGER NOT NULL DEFAULT 0,
                    scheduled_days REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (card_id, user_id)
                );
                INSERT INTO cards_new SELECT * FROM cards;
                DROP TABLE cards;
                ALTER TABLE cards_new RENAME TO cards;
                CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due);
                CREATE INDEX IF NOT EXISTS idx_cards_state ON cards(state);
                CREATE INDEX IF NOT EXISTS idx_cards_user ON cards(user_id);
                CREATE INDEX IF NOT EXISTS idx_cards_user_type ON cards(user_id, card_type);
            """)

        # Check review_log table
        review_cols = [row[1] for row in conn.execute("PRAGMA table_info(review_log)").fetchall()]
        if 'user_id' not in review_cols:
            conn.execute("ALTER TABLE review_log ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_review_user ON review_log(user_id)")

        conn.commit()

    def _migrate_fix_new_card_due(self, conn):
        """修复旧数据：新卡片(state=0)的 due 应为 0，不是创建时间
        
        旧版本 ensure_card 没有显式设置 due，导致 SQLite 默认值 0，
        但旧版 Card.__init__ 里 due=time.time()，如果通过 review_card 创建
        的卡片可能导致 state=0 但 due!=0。
        
        统一修复：state=0 且 reps=0 的卡片，due 设为 0。
        """
        try:
            conn.execute(
                "UPDATE cards SET due = 0 WHERE state = 0 AND reps = 0 AND due != 0"
            )
            conn.commit()
        except Exception:
            pass

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def ensure_card(self, card_id: str, card_type: str = "sentence", user_id: str = "default"):
        """确保卡片存在"""
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

    def get_card(self, card_id: str, user_id: str = "default") -> Optional[Card]:
        """获取卡片"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT card_id, difficulty, stability, state, due, last_review, reps, lapses, scheduled_days, created_at "
            "FROM cards WHERE card_id = ? AND user_id = ?",
            (card_id, user_id)
        ).fetchone()
        conn.close()
        if not row:
            return None
        card = Card(row[0])
        card.difficulty = row[1]
        card.stability = row[2]
        card.state = row[3]
        card.due = row[4]
        card.last_review = row[5]
        card.reps = row[6]
        card.lapses = row[7]
        card.scheduled_days = row[8]
        card.created_at = row[9]
        return card

    def get_card_info(self, card_id: str, user_id: str = "default") -> Optional[dict]:
        """获取卡片详细信息（含可回忆率）"""
        card = self.get_card(card_id, user_id)
        if not card:
            return None
        now = time.time()
        elapsed = max(0, (now - card.last_review) / 86400.0) if card.last_review > 0 else 0
        if card.stability > 0 and card.state != Card.NEW:
            ret = _retrievability(elapsed, card.stability, self.scheduler.decay)
        else:
            ret = 0

        return {
            "card_id": card.card_id,
            "state": card.state,
            "state_name": ["new", "learning", "review", "relearning"][card.state],
            "difficulty": round(card.difficulty, 2),
            "stability": round(card.stability, 2),
            "retrievability": round(ret, 4),
            "due": card.due,
            "scheduled_days": round(card.scheduled_days, 1),
            "reps": card.reps,
            "lapses": card.lapses,
            "last_review": card.last_review,
        }

    def review_card(self, card_id: str, rating: int, card_type: str = "sentence", user_id: str = "default") -> dict:
        """复习卡片并返回结果"""
        self.ensure_card(card_id, card_type, user_id)
        card = self.get_card(card_id, user_id)
        now = time.time()

        old_state = card.state
        card = self.scheduler.review(card, rating, now)

        conn = self._get_conn()
        conn.execute("""
            UPDATE cards SET difficulty=?, stability=?, state=?, due=?, last_review=?,
            reps=?, lapses=?, scheduled_days=? WHERE card_id=? AND user_id=?
        """, (card.difficulty, card.stability, card.state, card.due,
              card.last_review, card.reps, card.lapses, card.scheduled_days, card_id, user_id))

        conn.execute("""
            INSERT INTO review_log (card_id, user_id, rating, state, due, review_time, elapsed_days)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (card_id, user_id, rating, old_state, card.due, now, card.elapsed_days))

        conn.commit()
        conn.close()

        due_dt = datetime.fromtimestamp(card.due)
        return {
            "card_id": card_id,
            "rating": rating,
            "state": card.state,
            "state_name": ["new", "learning", "review", "relearning"][card.state],
            "difficulty": round(card.difficulty, 2),
            "stability": round(card.stability, 2),
            "retrievability": round(card.retrievability, 4),
            "scheduled_days": round(card.scheduled_days, 1),
            "due": due_dt.isoformat(),
            "reps": card.reps,
            "lapses": card.lapses,
        }

    def get_due_cards(self, card_type: str = "sentence", user_id: str = "default", limit: int = 20) -> List[dict]:
        """获取真正到期的复习卡片（state != NEW 且 due <= now）
        
        关键：只返回已经学习过、现在到期的卡片，不包括新卡片。
        """
        now = time.time()
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type=? AND user_id=? AND state != 0 AND due <= ? AND due > 0 ORDER BY due ASC LIMIT ?",
            (card_type, user_id, now, limit)
        ).fetchall()
        conn.close()

        result = []
        for r in rows:
            result.append({
                "card_id": r[0],
                "state": r[1],
                "state_name": ["new", "learning", "review", "relearning"][r[1]],
                "due": r[2],
                "scheduled_days": r[3],
                "reps": r[4],
                "difficulty": round(r[5], 2),
                "stability": round(r[6], 2),
            })
        return result

    def get_due_count(self, card_type: str = "sentence", user_id: str = "default") -> int:
        """获取到期复习卡片数量（不含新卡片）"""
        now = time.time()
        conn = self._get_conn()
        count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type=? AND user_id=? AND state != 0 AND due <= ? AND due > 0",
            (card_type, user_id, now)
        ).fetchone()[0]
        conn.close()
        return count

    def get_pending_review_count(self, card_type: str = "word", user_id: str = "default") -> int:
        """获取待复习卡片数量（不含新词，用于"待复习"徽章）"""
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
        pending = total - new_count - mastered_count
        return max(0, pending)

    def get_total_reviewable_count(self, card_type: str = "word", user_id: str = "default") -> int:
        """获取可练习卡片数量（新词+待复习，不含已掌握，用于练习模式总数）"""
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

    def get_next_word_for_practice(self, user_id: str = "default", new_ratio: float = 0.7) -> Optional[dict]:
        """获取下一个练习单词（FSRS驱动，新词优先，穿插到期复习）
        
        策略（区别于 get_next_word_for_review）：
        - 新词占约 70%，到期复习占约 30%
        - 随机混合，避免全是新词或全是复习
        - 已掌握的（REVIEW + 未到期 + 间隔>=3天）不推荐
        - 错误次数多的词优先级提升
        """
        import random
        now = time.time()
        conn = self._get_conn()

        # 获取所有未掌握的卡片
        # NEW + LEARNING + RELEARNING + REVIEW到期/间隔<3天
        rows = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type='word' AND user_id=? "
            "AND NOT (state=2 AND due > ? AND scheduled_days >= 3) "
            "ORDER BY CASE WHEN state=0 THEN 0 ELSE 1 END, "
            "CASE WHEN state != 0 AND due <= ? THEN 0 ELSE 1 END, "
            "difficulty DESC, reps ASC",
            (user_id, now, now)
        ).fetchall()
        conn.close()

        if not rows:
            return None

        # 分类
        new_cards = [r for r in rows if r[1] == 0]
        due_review_cards = [r for r in rows if r[1] != 0 and r[2] <= now and r[2] > 0]
        learning_cards = [r for r in rows if r[1] in (1, 3)]
        # REVIEW 但未掌握（due > now 但 scheduled_days < 3）——之前遗漏的关键分类
        # r[3] = scheduled_days（SELECT: card_id(0), state(1), due(2), scheduled_days(3), reps(4), difficulty(5), stability(6)）
        unmastered_review_cards = [r for r in rows if r[1] == 2 and not (r[2] > now and r[3] >= 3)]

        # 优先级：到期复习 > 学习中 > 未掌握复习 > 新词
        # 使用加权随机
        candidates = []
        weights = []

        for r in due_review_cards:
            candidates.append(r)
            weights.append(3.0)  # 到期复习权重最高
        for r in learning_cards:
            candidates.append(r)
            weights.append(2.5)  # 学习中权重次之
        for r in unmastered_review_cards:
            candidates.append(r)
            weights.append(2.0)  # 未掌握复习权重再次之
        for r in new_cards:
            candidates.append(r)
            weights.append(1.0)  # 新词权重基础

        if not candidates:
            return None

        # 加权随机选择
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
            "state_name": ["new", "learning", "review", "relearning"][state],
            "due": chosen[2],
            "scheduled_days": chosen[3],
            "reps": chosen[4],
            "difficulty": round(chosen[5], 2),
            "stability": round(chosen[6], 2),
        }

    def get_new_cards(self, card_type: str = "sentence", user_id: str = "default", limit: int = 10) -> List[str]:
        """获取新卡片ID"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT card_id FROM cards WHERE card_type=? AND user_id=? AND state=0 ORDER BY created_at ASC LIMIT ?",
            (card_type, user_id, limit)
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]

    def get_new_card_count(self, card_type: str = "sentence", user_id: str = "default") -> int:
        """获取新卡片数量"""
        conn = self._get_conn()
        count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type=? AND user_id=? AND state=0",
            (card_type, user_id)
        ).fetchone()[0]
        conn.close()
        return count

    def get_review_queue(self, card_type: str = "sentence", user_id: str = "default", new_per_day: int = 5, review_limit: int = 50) -> List[dict]:
        """
        获取复习队列：混合到期复习卡片和新卡片
        策略：先返回到期复习卡片，再补新卡片
        
        关键：到期复习 = state != 0 且 due <= now 且 due > 0
        新卡片 = state == 0
        """
        now = time.time()
        conn = self._get_conn()

        # 到期的复习卡片（真正学过且到期了）
        review_rows = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type=? AND user_id=? AND state != 0 AND due <= ? AND due > 0 ORDER BY due ASC LIMIT ?",
            (card_type, user_id, now, review_limit)
        ).fetchall()

        # 新卡片
        new_rows = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type=? AND user_id=? AND state = 0 ORDER BY created_at ASC LIMIT ?",
            (card_type, user_id, new_per_day)
        ).fetchall()

        conn.close()

        queue = []
        for r in review_rows:
            queue.append({
                "card_id": r[0],
                "type": "review",
                "state": r[1],
                "state_name": ["new", "learning", "review", "relearning"][r[1]],
                "due": r[2],
                "scheduled_days": r[3],
                "reps": r[4],
            })

        for r in new_rows:
            queue.append({
                "card_id": r[0],
                "type": "new",
                "state": 0,
                "state_name": "new",
                "due": r[2],
                "scheduled_days": r[3],
                "reps": r[4],
            })

        return queue

    def get_next_word_for_review(self, user_id: str = "default") -> Optional[dict]:
        """获取下一个需要复习的单词（FSRS 优先）
        
        策略：
        1. 优先返回到期的复习单词（state != NEW, due <= now）
        2. 如果没有到期复习，返回 LEARNING/RELEARNING 的单词
        3. 如果还没有，返回 REVIEW 但未掌握的单词（due > now 但 scheduled_days < 3）
        4. 如果还没有，返回新单词（state = NEW）
        5. 已掌握的（REVIEW + due > now + scheduled_days >= 3）不推荐
        
        关键修复：之前遗漏了第3步，导致 REVIEW 状态但间隔不够的单词
        （即"待复习"但未到期的单词）永远不会被推荐复习，
        造成"0/17 复习完成"但实际有待复习单词的 bug。
        """
        now = time.time()
        conn = self._get_conn()

        # 1. 到期的复习单词（按 due 排序，最早的优先）
        review_row = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type='word' AND user_id=? AND state != 0 AND due <= ? AND due > 0 "
            "ORDER BY due ASC, difficulty DESC LIMIT 1",
            (user_id, now)
        ).fetchone()

        if review_row:
            conn.close()
            return {
                "card_id": review_row[0],
                "type": "review",
                "state": review_row[1],
                "state_name": ["new", "learning", "review", "relearning"][review_row[1]],
                "due": review_row[2],
                "scheduled_days": review_row[3],
                "reps": review_row[4],
                "difficulty": round(review_row[5], 2),
                "stability": round(review_row[6], 2),
            }

        # 2. LEARNING/RELEARNING 的单词（熟悉度还没过关）
        learning_row = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type='word' AND user_id=? AND state IN (1, 3) "
            "ORDER BY due ASC, difficulty DESC LIMIT 1",
            (user_id,)
        ).fetchone()

        if learning_row:
            conn.close()
            return {
                "card_id": learning_row[0],
                "type": "review",
                "state": learning_row[1],
                "state_name": ["new", "learning", "review", "relearning"][learning_row[1]],
                "due": learning_row[2],
                "scheduled_days": learning_row[3],
                "reps": learning_row[4],
                "difficulty": round(learning_row[5], 2),
                "stability": round(learning_row[6], 2),
            }

        # 3. REVIEW 但未掌握的单词（due > now 但 scheduled_days < 3，间隔还不够稳固）
        # 这些单词虽然还没到期，但间隔太短说明熟悉度还不够，应该继续复习
        unmastered_review_row = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type='word' AND user_id=? AND state = 2 "
            "AND NOT (due > ? AND scheduled_days >= 3) "
            "ORDER BY scheduled_days ASC, difficulty DESC LIMIT 1",
            (user_id, now)
        ).fetchone()

        if unmastered_review_row:
            conn.close()
            return {
                "card_id": unmastered_review_row[0],
                "type": "review",
                "state": unmastered_review_row[1],
                "state_name": ["new", "learning", "review", "relearning"][unmastered_review_row[1]],
                "due": unmastered_review_row[2],
                "scheduled_days": unmastered_review_row[3],
                "reps": unmastered_review_row[4],
                "difficulty": round(unmastered_review_row[5], 2),
                "stability": round(unmastered_review_row[6], 2),
            }

        # 4. 新单词（按创建时间排序，最早的优先）
        new_row = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type='word' AND user_id=? AND state = 0 "
            "ORDER BY created_at ASC LIMIT 1",
            (user_id,)
        ).fetchone()

        conn.close()

        if new_row:
            return {
                "card_id": new_row[0],
                "type": "new",
                "state": 0,
                "state_name": "new",
                "due": new_row[2],
                "scheduled_days": new_row[3],
                "reps": new_row[4],
                "difficulty": round(new_row[5], 2),
                "stability": round(new_row[6], 2),
            }

        return None

    def get_word_review_stats(self, user_id: str = "default") -> dict:
        """获取单词复习统计
        
        掌握度分类（用户视角）：
        - mastered (已掌握): state=REVIEW 且 due > now 且 scheduled_days >= 3 
          （已复习且未到期，间隔>=3天说明短期记忆稳固）
        - due (待复习): 所有非NEW且非已掌握的卡片 = LEARNING + RELEARNING + REVIEW到期 + REVIEW间隔<3天
          （只要熟悉度没过关就需要复习）
        - learning (学习中): state=LEARNING 或 RELEARNING
        - new (新词): state=NEW (从未复习过)
        
        关键变更：待复习 = 总数 - 已掌握 - 新词
        这样只要FSRS还没判定为"已掌握"，就都算待复习
        """
        now = time.time()
        conn = self._get_conn()

        total = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type='word' AND user_id=?", (user_id,)
        ).fetchone()[0]

        new_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type='word' AND user_id=? AND state=0", (user_id,)
        ).fetchone()[0]

        # 已掌握：REVIEW状态 + 未到期 + 间隔>=3天（短期记忆稳固）
        mastered_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type='word' AND user_id=? AND state=2 AND due > ? AND scheduled_days >= 3", 
            (user_id, now)
        ).fetchone()[0]

        # 待复习 = 总数 - 已掌握 - 新词
        due_count = total - mastered_count - new_count
        if due_count < 0:
            due_count = 0

        learning_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type='word' AND user_id=? AND state IN (1, 3)", (user_id,)
        ).fetchone()[0]

        # 到期复习数（严格FSRS到期，用于复习队列调度）
        due_now_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type='word' AND user_id=? AND state != 0 AND due <= ? AND due > 0",
            (user_id, now)
        ).fetchone()[0]

        conn.close()

        return {
            "total": total,
            "new": new_count,
            "due": due_count,
            "due_now": due_now_count,
            "learning": learning_count,
            "mastered": mastered_count,
        }

    def get_stats(self, user_id: str = "default") -> dict:
        """获取学习统计"""
        conn = self._get_conn()
        now = time.time()

        total = conn.execute("SELECT COUNT(*) FROM cards WHERE user_id=?", (user_id,)).fetchone()[0]
        new = conn.execute("SELECT COUNT(*) FROM cards WHERE user_id=? AND state=0", (user_id,)).fetchone()[0]
        learning = conn.execute("SELECT COUNT(*) FROM cards WHERE user_id=? AND state=1", (user_id,)).fetchone()[0]
        review = conn.execute("SELECT COUNT(*) FROM cards WHERE user_id=? AND state=2", (user_id,)).fetchone()[0]
        relearning = conn.execute("SELECT COUNT(*) FROM cards WHERE user_id=? AND state=3", (user_id,)).fetchone()[0]
        # 只算真正到期的复习卡片（不含新卡片）
        due_now = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE user_id=? AND state != 0 AND due <= ? AND due > 0",
            (user_id, now)
        ).fetchone()[0]

        total_reviews = conn.execute("SELECT COUNT(*) FROM review_log WHERE user_id=?", (user_id,)).fetchone()[0]
        today_start = now - (now % 86400)
        today_reviews = conn.execute(
            "SELECT COUNT(*) FROM review_log WHERE user_id=? AND review_time >= ?", (user_id, today_start)
        ).fetchone()[0]

        avg_rating = conn.execute(
            "SELECT AVG(rating) FROM review_log WHERE user_id=? AND review_time >= ?", (user_id, today_start)
        ).fetchone()[0] or 0

        conn.close()

        return {
            "total_cards": total,
            "new": new,
            "learning": learning,
            "review": review,
            "relearning": relearning,
            "due_now": due_now,
            "total_reviews": total_reviews,
            "today_reviews": today_reviews,
            "today_avg_rating": round(avg_rating, 2),
        }


# 全局实例
_fsrs_db: Optional[FSRSDatabase] = None


def get_fsrs_db() -> FSRSDatabase:
    global _fsrs_db
    if _fsrs_db is None:
        _fsrs_db = FSRSDatabase()
    return _fsrs_db
