"""
FSRS 间隔重复算法 + SQLite 持久化

基于 FSRS-4.5 算法实现，用于句子/单词的复习调度。
Rating: 1=Again, 2=Hard, 3=Good, 4=Easy
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
        self.due = time.time()
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
            if rating == 1:
                card.state = Card.LEARNING
            elif rating == 2:
                card.state = Card.LEARNING
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
    """FSRS SQLite 数据库"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self.scheduler = FSRSScheduler()
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cards (
                card_id TEXT PRIMARY KEY,
                card_type TEXT NOT NULL DEFAULT 'sentence',
                difficulty REAL NOT NULL DEFAULT 0,
                stability REAL NOT NULL DEFAULT 0,
                state INTEGER NOT NULL DEFAULT 0,
                due REAL NOT NULL DEFAULT 0,
                last_review REAL NOT NULL DEFAULT 0,
                reps INTEGER NOT NULL DEFAULT 0,
                lapses INTEGER NOT NULL DEFAULT 0,
                scheduled_days REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS review_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id TEXT NOT NULL,
                rating INTEGER NOT NULL,
                state INTEGER NOT NULL,
                due REAL NOT NULL,
                review_time REAL NOT NULL,
                elapsed_days REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (card_id) REFERENCES cards(card_id)
            );

            CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due);
            CREATE INDEX IF NOT EXISTS idx_cards_state ON cards(state);
            CREATE INDEX IF NOT EXISTS idx_review_card ON review_log(card_id);
        """)
        conn.commit()
        conn.close()

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def ensure_card(self, card_id: str, card_type: str = "sentence"):
        """确保卡片存在"""
        conn = self._get_conn()
        row = conn.execute("SELECT card_id FROM cards WHERE card_id = ?", (card_id,)).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO cards (card_id, card_type, created_at) VALUES (?, ?, ?)",
                (card_id, card_type, time.time())
            )
            conn.commit()
        conn.close()

    def get_card(self, card_id: str) -> Optional[Card]:
        """获取卡片"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT card_id, difficulty, stability, state, due, last_review, reps, lapses, scheduled_days, created_at "
            "FROM cards WHERE card_id = ?", (card_id,)
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

    def review_card(self, card_id: str, rating: int, card_type: str = "sentence") -> dict:
        """复习卡片并返回结果"""
        self.ensure_card(card_id, card_type)
        card = self.get_card(card_id)
        now = time.time()

        old_state = card.state
        card = self.scheduler.review(card, rating, now)

        conn = self._get_conn()
        conn.execute("""
            UPDATE cards SET difficulty=?, stability=?, state=?, due=?, last_review=?,
            reps=?, lapses=?, scheduled_days=? WHERE card_id=?
        """, (card.difficulty, card.stability, card.state, card.due,
              card.last_review, card.reps, card.lapses, card.scheduled_days, card_id))

        conn.execute("""
            INSERT INTO review_log (card_id, rating, state, due, review_time, elapsed_days)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (card_id, rating, old_state, card.due, now, card.elapsed_days))

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

    def get_due_cards(self, card_type: str = "sentence", limit: int = 20) -> List[dict]:
        """获取到期卡片"""
        now = time.time()
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type=? AND due <= ? ORDER BY due ASC LIMIT ?",
            (card_type, now, limit)
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

    def get_new_cards(self, card_type: str = "sentence", limit: int = 10) -> List[str]:
        """获取新卡片ID"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT card_id FROM cards WHERE card_type=? AND state=0 ORDER BY created_at ASC LIMIT ?",
            (card_type, limit)
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]

    def get_review_queue(self, card_type: str = "sentence", new_per_day: int = 5, review_limit: int = 50) -> List[dict]:
        """
        获取复习队列：混合到期复习卡片和新卡片
        策略：先返回到期复习卡片，再补新卡片
        """
        now = time.time()
        conn = self._get_conn()

        # 到期的复习卡片
        review_rows = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type=? AND state != 0 AND due <= ? ORDER BY due ASC LIMIT ?",
            (card_type, now, review_limit)
        ).fetchall()

        # 新卡片
        new_rows = conn.execute(
            "SELECT card_id, state, due, scheduled_days, reps, difficulty, stability "
            "FROM cards WHERE card_type=? AND state = 0 ORDER BY created_at ASC LIMIT ?",
            (card_type, new_per_day)
        ).fetchall()

        # 尚未创建卡片的句子（需要在前端句子列表中查找）
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

    def get_stats(self) -> dict:
        """获取学习统计"""
        conn = self._get_conn()
        now = time.time()

        total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        new = conn.execute("SELECT COUNT(*) FROM cards WHERE state=0").fetchone()[0]
        learning = conn.execute("SELECT COUNT(*) FROM cards WHERE state=1").fetchone()[0]
        review = conn.execute("SELECT COUNT(*) FROM cards WHERE state=2").fetchone()[0]
        relearning = conn.execute("SELECT COUNT(*) FROM cards WHERE state=3").fetchone()[0]
        due_now = conn.execute("SELECT COUNT(*) FROM cards WHERE due <= ?", (now,)).fetchone()[0]

        total_reviews = conn.execute("SELECT COUNT(*) FROM review_log").fetchone()[0]
        today_start = now - (now % 86400)
        today_reviews = conn.execute(
            "SELECT COUNT(*) FROM review_log WHERE review_time >= ?", (today_start,)
        ).fetchone()[0]

        avg_rating = conn.execute(
            "SELECT AVG(rating) FROM review_log WHERE review_time >= ?", (today_start,)
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
