"""
Phonos 智能学习算法

功能：
1. 薄弱分析 - 分析用户的音素/单词错误模式
2. 自适应难度 - 根据表现动态调整难度
3. 针对性练习推荐 - 基于薄弱项推荐练习句子
4. 个性化复习调度 - 根据学习速度调整FSRS参数
5. 学习分析 - 趋势、预测、连续学习天数
"""

import sqlite3
import time
import json
from pathlib import Path
from typing import Optional, Dict, List

DB_PATH = Path(__file__).parent / "phonos_learning.db"


def _get_conn(db_path: str = None):
    return sqlite3.connect(db_path or str(DB_PATH))


class LearningAlgorithm:
    """智能学习算法"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self._init_db()

    def _init_db(self):
        conn = _get_conn(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS user_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                sentence_id TEXT NOT NULL,
                overall_score REAL NOT NULL DEFAULT 0,
                pronunciation_score REAL NOT NULL DEFAULT 0,
                completeness_score REAL NOT NULL DEFAULT 0,
                fluency_score REAL NOT NULL DEFAULT 0,
                errors TEXT NOT NULL DEFAULT '[]',
                word_scores TEXT NOT NULL DEFAULT '[]',
                duration REAL NOT NULL DEFAULT 0,
                evaluated_at REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_word_progress (
                user_id TEXT NOT NULL,
                word TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                best_score REAL NOT NULL DEFAULT 0,
                avg_score REAL NOT NULL DEFAULT 0,
                last_attempted REAL NOT NULL DEFAULT 0,
                mastered INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, word)
            );

            CREATE TABLE IF NOT EXISTS user_phoneme_stats (
                user_id TEXT NOT NULL,
                phoneme TEXT NOT NULL,
                total_attempts INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                error_rate REAL NOT NULL DEFAULT 0,
                last_attempted REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, phoneme)
            );

            CREATE INDEX IF NOT EXISTS idx_eval_user ON user_evaluations(user_id);
            CREATE INDEX IF NOT EXISTS idx_eval_time ON user_evaluations(evaluated_at);
            CREATE INDEX IF NOT EXISTS idx_word_progress_user ON user_word_progress(user_id);
            CREATE INDEX IF NOT EXISTS idx_phoneme_stats_user ON user_phoneme_stats(user_id);

            CREATE TABLE IF NOT EXISTS user_sequential_position (
                user_id TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                sentences_count INTEGER NOT NULL DEFAULT 0,
                start_id INTEGER,
                end_id INTEGER,
                updated_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id)
            );

            CREATE TABLE IF NOT EXISTS user_word_errors (
                user_id TEXT NOT NULL,
                word TEXT NOT NULL,
                error_type TEXT NOT NULL DEFAULT 'dictation',
                count INTEGER NOT NULL DEFAULT 1,
                first_seen REAL NOT NULL DEFAULT 0,
                last_seen REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, word, error_type)
            );

            CREATE INDEX IF NOT EXISTS idx_word_errors_user ON user_word_errors(user_id);
            CREATE INDEX IF NOT EXISTS idx_word_errors_type ON user_word_errors(user_id, error_type);
        """)
        conn.commit()

        # Migration: add new columns to user_sequential_position if they don't exist
        self._migrate_sequential_position(conn)

        conn.commit()
        conn.close()

    def _migrate_sequential_position(self, conn):
        """迁移：为 user_sequential_position 表添加新列"""
        cols = [row[1] for row in conn.execute("PRAGMA table_info(user_sequential_position)").fetchall()]
        if 'sentences_count' not in cols:
            conn.execute("ALTER TABLE user_sequential_position ADD COLUMN sentences_count INTEGER NOT NULL DEFAULT 0")
        if 'start_id' not in cols:
            conn.execute("ALTER TABLE user_sequential_position ADD COLUMN start_id INTEGER")
        if 'end_id' not in cols:
            conn.execute("ALTER TABLE user_sequential_position ADD COLUMN end_id INTEGER")

    # ================================================================
    # Record Evaluation
    # ================================================================
    def record_evaluation(
        self,
        user_id: str,
        sentence_id: str,
        overall_score: float,
        pronunciation_score: float,
        completeness_score: float,
        fluency_score: float,
        errors: list,
        word_scores: list,
        duration: float = 0,
    ):
        """记录评测结果，更新所有相关统计表"""
        now = time.time()
        conn = _get_conn(self.db_path)

        # 1. Insert into user_evaluations
        conn.execute(
            """INSERT INTO user_evaluations 
            (user_id, sentence_id, overall_score, pronunciation_score, completeness_score, fluency_score, errors, word_scores, duration, evaluated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, sentence_id, overall_score, pronunciation_score, completeness_score, fluency_score,
             json.dumps(errors), json.dumps(word_scores), duration, now)
        )

        # 2. Update user_word_progress
        for ws in word_scores:
            word = ws.get("word", "").lower()
            accuracy = ws.get("accuracy", 0)
            if not word:
                continue
            row = conn.execute(
                "SELECT attempts, best_score, avg_score FROM user_word_progress WHERE user_id = ? AND word = ?",
                (user_id, word)
            ).fetchone()

            if row:
                attempts, best, avg = row
                new_attempts = attempts + 1
                new_best = max(best, accuracy)
                new_avg = ((avg * attempts) + accuracy) / new_attempts
                mastered = 1 if new_best >= 80 else 0
                conn.execute(
                    "UPDATE user_word_progress SET attempts=?, best_score=?, avg_score=?, last_attempted=?, mastered=? WHERE user_id=? AND word=?",
                    (new_attempts, new_best, new_avg, now, mastered, user_id, word)
                )
            else:
                mastered = 1 if accuracy >= 80 else 0
                conn.execute(
                    "INSERT INTO user_word_progress (user_id, word, attempts, best_score, avg_score, last_attempted, mastered) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, word, 1, accuracy, accuracy, now, mastered)
                )

        # 2.5 Record pronunciation errors for weak words
        for ws in word_scores:
            word = ws.get("word", "").lower()
            accuracy = ws.get("accuracy", 0)
            if word and accuracy < 60:
                # This word was mispronounced
                err_row = conn.execute(
                    "SELECT count FROM user_word_errors WHERE user_id = ? AND word = ? AND error_type = ?",
                    (user_id, word, 'pronunciation')
                ).fetchone()
                if err_row:
                    conn.execute(
                        "UPDATE user_word_errors SET count = count + 1, last_seen = ? WHERE user_id = ? AND word = ? AND error_type = ?",
                        (now, user_id, word, 'pronunciation')
                    )
                else:
                    conn.execute(
                        "INSERT INTO user_word_errors (user_id, word, error_type, count, first_seen, last_seen) VALUES (?, ?, ?, 1, ?, ?)",
                        (user_id, word, 'pronunciation', now, now)
                    )

        # 3. Update user_phoneme_stats
        for err in errors:
            phoneme = err.get("expected", "")
            if not phoneme:
                continue
            row = conn.execute(
                "SELECT total_attempts, error_count FROM user_phoneme_stats WHERE user_id = ? AND phoneme = ?",
                (user_id, phoneme)
            ).fetchone()

            if row:
                total, err_count = row
                new_total = total + 1
                new_err = err_count + 1
                new_rate = new_err / new_total
                conn.execute(
                    "UPDATE user_phoneme_stats SET total_attempts=?, error_count=?, error_rate=?, last_attempted=? WHERE user_id=? AND phoneme=?",
                    (new_total, new_err, new_rate, now, user_id, phoneme)
                )
            else:
                conn.execute(
                    "INSERT INTO user_phoneme_stats (user_id, phoneme, total_attempts, error_count, error_rate, last_attempted) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, phoneme, 1, 1, 1.0, now)
                )

        # Also update total_attempts for phonemes that were correctly pronounced
        # (We can infer from word_scores - phonemes in words that scored well)
        # For simplicity, we don't track every correctly produced phoneme individually

        conn.commit()
        conn.close()

    # ================================================================
    # Weakness Analysis
    # ================================================================
    def get_weakness_profile(self, user_id: str) -> Dict:
        """获取用户薄弱项分析"""
        conn = _get_conn(self.db_path)

        # Phoneme weaknesses
        phoneme_rows = conn.execute(
            "SELECT phoneme, total_attempts, error_count, error_rate FROM user_phoneme_stats WHERE user_id = ? ORDER BY error_rate DESC, error_count DESC LIMIT 20",
            (user_id,)
        ).fetchall()
        conn.close()

        phoneme_weaknesses = []
        for r in phoneme_rows:
            severity = "severe" if r[3] >= 0.6 else "moderate" if r[3] >= 0.3 else "mild"
            phoneme_weaknesses.append({
                "phoneme": r[0],
                "total_attempts": r[1],
                "error_count": r[2],
                "error_rate": round(r[3], 2),
                "severity": severity,
            })

        # Category weaknesses (from evaluations - aggregate by sentence difficulty)
        conn = _get_conn(self.db_path)
        eval_rows = conn.execute(
            "SELECT sentence_id, overall_score FROM user_evaluations WHERE user_id = ? ORDER BY evaluated_at DESC LIMIT 50",
            (user_id,)
        ).fetchall()
        conn.close()

        # Word-level weaknesses
        conn = _get_conn(self.db_path)
        word_rows = conn.execute(
            "SELECT word, attempts, best_score, avg_score, mastered FROM user_word_progress WHERE user_id = ? AND mastered = 0 ORDER BY avg_score ASC LIMIT 20",
            (user_id,)
        ).fetchall()
        conn.close()

        word_weaknesses = []
        for r in word_rows:
            word_weaknesses.append({
                "word": r[0],
                "attempts": r[1],
                "best_score": round(r[2], 1),
                "avg_score": round(r[3], 1),
                "mastered": bool(r[4]),
            })

        # Determine difficulty level based on recent performance
        difficulty_level = self._estimate_difficulty_level(user_id)

        return {
            "phoneme_weaknesses": phoneme_weaknesses,
            "word_weaknesses": word_weaknesses,
            "difficulty_level": difficulty_level,
        }

    def _estimate_difficulty_level(self, user_id: str) -> str:
        """基于近期表现估计用户适合的难度等级"""
        conn = _get_conn(self.db_path)
        rows = conn.execute(
            "SELECT overall_score FROM user_evaluations WHERE user_id = ? ORDER BY evaluated_at DESC LIMIT 10",
            (user_id,)
        ).fetchall()
        conn.close()

        if not rows:
            return "easy"

        scores = [r[0] for r in rows]
        avg = sum(scores) / len(scores)

        if avg >= 80:
            return "hard"
        elif avg >= 60:
            return "medium"
        else:
            return "easy"

    # ================================================================
    # Adaptive Next Sentence
    # ================================================================
    def get_adaptive_next(self, user_id: str, sentences: list) -> Optional[Dict]:
        """获取自适应难度推荐句子"""
        weakness = self.get_weakness_profile(user_id)
        difficulty = weakness["difficulty_level"]
        weak_phonemes = set(w["phoneme"] for w in weakness["phoneme_weaknesses"][:5])

        # Filter sentences by difficulty
        matching = [s for s in sentences if s.get("difficulty", "medium") == difficulty]

        # If no exact match, relax to include adjacent difficulties
        if not matching:
            if difficulty == "easy":
                matching = [s for s in sentences if s.get("difficulty", "medium") in ("easy", "medium")]
            elif difficulty == "hard":
                matching = [s for s in sentences if s.get("difficulty", "medium") in ("medium", "hard")]
            else:
                matching = sentences

        if not matching:
            return None

        # Score sentences by how many weak phonemes they contain
        # We use the phoneme cache if available, otherwise just pick randomly
        import random
        if weak_phonemes:
            scored = []
            for s in matching:
                # Simple heuristic: check if sentence text contains words that we know are weak
                words = s.get("text", "").lower().split()
                score = 0
                for ww in weakness.get("word_weaknesses", []):
                    if ww["word"] in words:
                        score += 1
                scored.append((score, s))
            scored.sort(key=lambda x: -x[0])
            # Pick from top 3 with some randomness
            top = scored[:3]
            return random.choice(top)[1] if top else random.choice(matching)

        return random.choice(matching)

    # ================================================================
    # Recommendations
    # ================================================================
    def get_recommendations(self, user_id: str, sentences: list) -> List[Dict]:
        """获取针对性练习推荐"""
        weakness = self.get_weakness_profile(user_id)
        weak_phonemes = [w["phoneme"] for w in weakness["phoneme_weaknesses"][:5]]
        weak_words = [w["word"] for w in weakness["word_weaknesses"][:5]]
        difficulty = weakness["difficulty_level"]

        recommendations = []

        # 1. Sentences containing weak words
        for s in sentences:
            words = s.get("text", "").lower().split()
            overlap = [w for w in weak_words if w in words]
            if overlap:
                recommendations.append({
                    "sentence_id": s.get("id"),
                    "text": s.get("text", ""),
                    "reason": f"包含薄弱单词: {', '.join(overlap)}",
                    "priority": "high",
                    "difficulty": s.get("difficulty", "medium"),
                    "category": s.get("category", "general"),
                })

        # 2. Sentences at appropriate difficulty
        diff_sentences = [s for s in sentences if s.get("difficulty", "medium") == difficulty]
        for s in diff_sentences[:3]:
            # Don't add duplicates
            if not any(r["sentence_id"] == s.get("id") for r in recommendations):
                recommendations.append({
                    "sentence_id": s.get("id"),
                    "text": s.get("text", ""),
                    "reason": f"适合当前难度: {difficulty}",
                    "priority": "medium",
                    "difficulty": s.get("difficulty", "medium"),
                    "category": s.get("category", "general"),
                })

        # Sort by priority
        recommendations.sort(key=lambda x: 0 if x["priority"] == "high" else 1)
        return recommendations[:10]

    # ================================================================
    # Learning Analytics
    # ================================================================
    def get_analytics(self, user_id: str) -> Dict:
        """获取详细学习分析"""
        conn = _get_conn(self.db_path)
        now = time.time()

        # Total evaluations
        total_evals = conn.execute(
            "SELECT COUNT(*) FROM user_evaluations WHERE user_id = ?", (user_id,)
        ).fetchone()[0]

        # Today's evaluations
        today_start = now - (now % 86400)
        today_evals = conn.execute(
            "SELECT COUNT(*) FROM user_evaluations WHERE user_id = ? AND evaluated_at >= ?",
            (user_id, today_start)
        ).fetchone()[0]

        # Average score (last 30 days)
        thirty_days_ago = now - 30 * 86400
        avg_row = conn.execute(
            "SELECT AVG(overall_score) FROM user_evaluations WHERE user_id = ? AND evaluated_at >= ?",
            (user_id, thirty_days_ago)
        ).fetchone()
        avg_score = round(avg_row[0], 1) if avg_row and avg_row[0] else 0

        # Score trend (last 7 days vs previous 7 days)
        seven_days_ago = now - 7 * 86400
        fourteen_days_ago = now - 14 * 86400

        recent_avg_row = conn.execute(
            "SELECT AVG(overall_score) FROM user_evaluations WHERE user_id = ? AND evaluated_at >= ?",
            (user_id, seven_days_ago)
        ).fetchone()
        recent_avg = recent_avg_row[0] if recent_avg_row and recent_avg_row[0] else 0

        prev_avg_row = conn.execute(
            "SELECT AVG(overall_score) FROM user_evaluations WHERE user_id = ? AND evaluated_at >= ? AND evaluated_at < ?",
            (user_id, fourteen_days_ago, seven_days_ago)
        ).fetchone()
        prev_avg = prev_avg_row[0] if prev_avg_row and prev_avg_row[0] else 0

        improvement_rate = round(recent_avg - prev_avg, 1) if prev_avg > 0 else 0

        # Streak calculation
        streak = self._calculate_streak(conn, user_id)

        # Word progress summary
        mastered_count = conn.execute(
            "SELECT COUNT(*) FROM user_word_progress WHERE user_id = ? AND mastered = 1",
            (user_id,)
        ).fetchone()[0]

        total_words = conn.execute(
            "SELECT COUNT(*) FROM user_word_progress WHERE user_id = ?",
            (user_id,)
        ).fetchone()[0]

        # Phoneme error summary
        phoneme_error_count = conn.execute(
            "SELECT COUNT(DISTINCT phoneme) FROM user_phoneme_stats WHERE user_id = ? AND error_rate > 0.3",
            (user_id,)
        ).fetchone()[0]

        # Score history (last 30 scores)
        score_history = conn.execute(
            "SELECT overall_score, evaluated_at FROM user_evaluations WHERE user_id = ? ORDER BY evaluated_at DESC LIMIT 30",
            (user_id,)
        ).fetchall()
        score_history.reverse()

        # Category performance (if we have sentence categories)
        # We'll aggregate by time periods
        daily_scores = conn.execute(
            """SELECT DATE(evaluated_at, 'unixepoch') as day, AVG(overall_score), COUNT(*)
            FROM user_evaluations WHERE user_id = ? AND evaluated_at >= ?
            GROUP BY day ORDER BY day DESC LIMIT 14""",
            (user_id, fourteen_days_ago)
        ).fetchall()

        conn.close()

        return {
            "total_evaluations": total_evals,
            "today_evaluations": today_evals,
            "avg_score_30d": avg_score,
            "improvement_rate": improvement_rate,
            "streak": streak,
            "mastered_words": mastered_count,
            "total_words_practiced": total_words,
            "problematic_phonemes": phoneme_error_count,
            "score_history": [
                {"score": round(r[0], 1), "time": r[1]} for r in score_history
            ],
            "daily_scores": [
                {"date": r[0], "avg_score": round(r[1], 1), "count": r[2]} for r in daily_scores
            ],
            "difficulty_recommendation": self._estimate_difficulty_level(user_id),
        }

    def _calculate_streak(self, conn, user_id: str) -> int:
        """计算连续学习天数"""
        now = time.time()
        today_start = now - (now % 86400)

        # Get distinct days with evaluations
        rows = conn.execute(
            """SELECT DISTINCT DATE(evaluated_at, 'unixepoch') as day 
            FROM user_evaluations WHERE user_id = ? 
            ORDER BY day DESC LIMIT 60""",
            (user_id,)
        ).fetchall()

        if not rows:
            return 0

        streak = 0
        current_day = today_start

        for r in rows:
            day_str = r[0]
            # Parse the day
            import datetime
            try:
                day_date = datetime.datetime.strptime(day_str, "%Y-%m-%d")
                day_ts = day_date.timestamp()
            except:
                continue

            # Check if this day matches the current expected day
            expected_day_str = datetime.datetime.fromtimestamp(current_day).strftime("%Y-%m-%d")
            if day_str == expected_day_str:
                streak += 1
                current_day -= 86400
            else:
                break

        return streak

    # ================================================================
    # FSRS Parameter Adjustment
    # ================================================================
    def get_adjusted_fsrs_params(self, user_id: str) -> Dict:
        """根据用户学习速度调整FSRS参数"""
        conn = _get_conn(self.db_path)

        # Get recent performance
        rows = conn.execute(
            "SELECT overall_score FROM user_evaluations WHERE user_id = ? ORDER BY evaluated_at DESC LIMIT 20",
            (user_id,)
        ).fetchall()
        conn.close()

        if not rows:
            return {"new_per_day": 5, "review_limit": 50}

        avg = sum(r[0] for r in rows) / len(rows)

        # Fast learners: more new cards, shorter intervals
        if avg >= 80:
            return {"new_per_day": 8, "review_limit": 60}
        elif avg >= 60:
            return {"new_per_day": 5, "review_limit": 50}
        else:
            # Slow learners: fewer new cards, more repetition
            return {"new_per_day": 3, "review_limit": 40}

    # ================================================================
    # Sequential Position
    # ================================================================
    def get_sequential_position(self, user_id: str) -> dict:
        """获取用户顺序模式的当前位置及关联信息"""
        conn = _get_conn(self.db_path)
        row = conn.execute(
            "SELECT position, sentences_count, start_id, end_id FROM user_sequential_position WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        conn.close()
        if row:
            return {
                "position": row[0],
                "sentences_count": row[1],
                "start_id": row[2],
                "end_id": row[3],
            }
        return {
            "position": 0,
            "sentences_count": 0,
            "start_id": None,
            "end_id": None,
        }

    def set_sequential_position(self, user_id: str, position: int, sentences_count: int = 0, start_id: int = None, end_id: int = None):
        """设置用户顺序模式的位置，同时保存当前句子数量和ID范围"""
        conn = _get_conn(self.db_path)
        now = time.time()
        conn.execute(
            "INSERT OR REPLACE INTO user_sequential_position (user_id, position, sentences_count, start_id, end_id, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, position, sentences_count, start_id, end_id, now)
        )
        conn.commit()
        conn.close()

    # ================================================================
    # Error Word Recording
    # ================================================================
    def record_dictation_errors(self, user_id: str, error_words: list, sentence_id: str = ""):
        """记录听写错误的单词"""
        now = time.time()
        conn = _get_conn(self.db_path)
        for word in error_words:
            word = word.lower().strip()
            if not word:
                continue
            row = conn.execute(
                "SELECT count FROM user_word_errors WHERE user_id = ? AND word = ? AND error_type = ?",
                (user_id, word, 'dictation')
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE user_word_errors SET count = count + 1, last_seen = ? WHERE user_id = ? AND word = ? AND error_type = ?",
                    (now, user_id, word, 'dictation')
                )
            else:
                conn.execute(
                    "INSERT INTO user_word_errors (user_id, word, error_type, count, first_seen, last_seen) VALUES (?, ?, ?, 1, ?, ?)",
                    (user_id, word, 'dictation', now, now)
                )
        conn.commit()
        conn.close()

    def record_pronunciation_errors(self, user_id: str, error_words: list):
        """记录发音错误的单词（读错或没背出）"""
        now = time.time()
        conn = _get_conn(self.db_path)
        for word_info in error_words:
            if isinstance(word_info, dict):
                word = word_info.get("word", "").lower().strip()
            else:
                word = str(word_info).lower().strip()
            if not word:
                continue
            row = conn.execute(
                "SELECT count FROM user_word_errors WHERE user_id = ? AND word = ? AND error_type = ?",
                (user_id, word, 'pronunciation')
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE user_word_errors SET count = count + 1, last_seen = ? WHERE user_id = ? AND word = ? AND error_type = ?",
                    (now, user_id, word, 'pronunciation')
                )
            else:
                conn.execute(
                    "INSERT INTO user_word_errors (user_id, word, error_type, count, first_seen, last_seen) VALUES (?, ?, ?, 1, ?, ?)",
                    (user_id, word, 'pronunciation', now, now)
                )
        conn.commit()
        conn.close()

    # ================================================================
    # Sentence Data Hash
    # ================================================================
    def get_sentences_hash(self, sentences_count: int) -> int:
        """获取句子数据的简单哈希（使用句子数量作为简易检测）"""
        return sentences_count

    # ================================================================
    # Sequential Range Setting
    # ================================================================
    def set_sequential_range(self, user_id: str, start_id: int, end_id: int, sentences: list):
        """设置顺序模式的ID范围，找到start_id对应的列表位置"""
        # Find the list index for start_id
        start_pos = 0
        for i, s in enumerate(sentences):
            if s.get("id") == start_id:
                start_pos = i
                break

        # If end_id is provided, validate it; otherwise default to last sentence
        effective_end_id = end_id if end_id else None
        sentences_count = len(sentences)

        self.set_sequential_position(
            user_id=user_id,
            position=start_pos,
            sentences_count=sentences_count,
            start_id=start_id,
            end_id=effective_end_id,
        )
        return {
            "position": start_pos,
            "start_id": start_id,
            "end_id": effective_end_id,
            "sentences_count": sentences_count,
        }

    # ================================================================
    # Smart Recommendation Score
    # ================================================================
    def get_smart_recommendation_score(self, user_id: str, sentence: dict, sentences: list) -> float:
        """
        计算句子的智能推荐分数（越高越推荐）

        综合考虑：
        1. FSRS 卡片难度和状态
        2. 薄弱音素匹配度
        3. 薄弱单词匹配度
        4. 错误的近因性（最近犯错更优先）
        """
        score = 0.0
        now = time.time()

        # 1. FSRS 卡片因素
        # Card states: 0=NEW, 1=LEARNING, 2=REVIEW, 3=RELEARNING
        try:
            from fsrs_db import get_fsrs_db
            fsrs = get_fsrs_db()
            card_id = f"sentence_{sentence.get('id', '')}"
            card = fsrs.get_card(card_id, user_id=user_id)
            if card:
                # Higher difficulty = more need to practice
                score += card.difficulty * 2.0
                # More lapses = higher priority
                score += card.lapses * 3.0
                # Lower retrievability = more urgent
                if card.retrievability < 0.7:
                    score += (1.0 - card.retrievability) * 5.0
                # New cards get moderate score
                if card.state == 0:  # NEW
                    score += 1.0
                # Relearning cards get high priority
                if card.state == 3:  # RELEARNING
                    score += 8.0
                # Learning cards get moderate-high priority
                elif card.state == 1:  # LEARNING
                    score += 5.0
        except Exception:
            pass

        # 2. Weakness profile factors
        weakness = self.get_weakness_profile(user_id)
        weak_phonemes = set(w["phoneme"] for w in weakness.get("phoneme_weaknesses", [])[:8])
        weak_words = [w["word"] for w in weakness.get("word_weaknesses", [])[:10]]
        difficulty_level = weakness.get("difficulty_level", "medium")

        # Check if sentence contains weak words
        sentence_words = sentence.get("text", "").lower().split()
        weak_word_overlap = sum(1 for w in sentence_words if w in weak_words)
        score += weak_word_overlap * 4.0

        # 3. Phoneme weakness overlap (approximate via word overlap since
        #    we may not have phoneme data for all sentences)
        #    Use the phoneme cache if available
        try:
            from phoneme_data import PRESET_SENTENCES as _PS
            # Find this sentence in PRESET_SENTENCES and check its phonemes
            for s in _PS:
                if s.get("id") == sentence.get("id"):
                    # Check if the text has words that contain our weak phonemes
                    # This is a rough approximation
                    break
        except Exception:
            pass

        # 4. Difficulty match bonus
        sentence_diff = sentence.get("difficulty", "medium")
        if difficulty_level == "easy":
            if sentence_diff == "easy":
                score += 2.0
            elif sentence_diff == "medium":
                score += 1.0
        elif difficulty_level == "medium":
            if sentence_diff == "medium":
                score += 2.0
            elif sentence_diff in ("easy", "hard"):
                score += 1.0
        elif difficulty_level == "hard":
            if sentence_diff == "hard":
                score += 2.0
            elif sentence_diff == "medium":
                score += 1.0

        # 5. Recency weighting - check recent evaluations for this sentence
        try:
            conn = _get_conn(self.db_path)
            sentence_id = f"sentence_{sentence.get('id', '')}"
            recent_evals = conn.execute(
                "SELECT overall_score, evaluated_at FROM user_evaluations WHERE user_id = ? AND sentence_id = ? ORDER BY evaluated_at DESC LIMIT 5",
                (user_id, sentence_id)
            ).fetchall()
            conn.close()

            if recent_evals:
                # More recent and lower scores = higher priority
                for ev_score, ev_time in recent_evals:
                    # Decay factor: more recent = higher weight
                    days_ago = (now - ev_time) / 86400.0
                    recency_weight = max(0.1, 1.0 / (1.0 + days_ago * 0.1))
                    # Lower scores contribute more to priority
                    if ev_score < 60:
                        score += 3.0 * recency_weight
                    elif ev_score < 80:
                        score += 1.5 * recency_weight
            else:
                # Never practiced = moderate priority (discover new content)
                score += 1.5
        except Exception:
            pass

        # 6. FSRS review history - consistently low ratings (1-2) increase priority
        try:
            from fsrs_db import get_fsrs_db as _get_fsrs
            _fsrs = _get_fsrs()
            conn_fsrs = _fsrs._get_conn()
            card_id = f"sentence_{sentence.get('id', '')}"
            recent_ratings = conn_fsrs.execute(
                "SELECT rating, review_time FROM review_log WHERE card_id = ? AND user_id = ? ORDER BY review_time DESC LIMIT 5",
                (card_id, user_id)
            ).fetchall()
            conn_fsrs.close()

            if recent_ratings:
                low_rating_count = sum(1 for r in recent_ratings if r[0] <= 2)
                high_rating_count = sum(1 for r in recent_ratings if r[0] >= 3)

                # Consistently low ratings = needs more practice
                if low_rating_count >= 2:
                    score += low_rating_count * 3.0

                # High ratings = can advance to harder content faster
                # (reduce score slightly to let other sentences get picked)
                if high_rating_count >= 3 and low_rating_count == 0:
                    score -= 2.0
        except Exception:
            pass

        return max(score, 0.0)

    # ================================================================
    # Error Word Recording
    # ================================================================
    def get_error_words(self, user_id: str, error_type: str = None) -> list:
        """获取用户的错误单词列表（用于单词复习）"""
        conn = _get_conn(self.db_path)
        if error_type:
            rows = conn.execute(
                "SELECT word, error_type, count, first_seen, last_seen FROM user_word_errors WHERE user_id = ? AND error_type = ? ORDER BY last_seen DESC",
                (user_id, error_type)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT word, error_type, count, first_seen, last_seen FROM user_word_errors WHERE user_id = ? ORDER BY last_seen DESC",
                (user_id,)
            ).fetchall()
        conn.close()

        result = []
        seen_words = set()
        for r in rows:
            word = r[0]
            if word not in seen_words:
                seen_words.add(word)
                # Get total error count across all types
                result.append({
                    "word": word,
                    "dictation_errors": 0,
                    "pronunciation_errors": 0,
                    "total_errors": 0,
                    "last_seen": r[4],
                })

        # Fill in error counts
        conn = _get_conn(self.db_path)
        for item in result:
            for etype in ['dictation', 'pronunciation']:
                row = conn.execute(
                    "SELECT count FROM user_word_errors WHERE user_id = ? AND word = ? AND error_type = ?",
                    (user_id, item["word"], etype)
                ).fetchone()
                count = row[0] if row else 0
                if etype == 'dictation':
                    item["dictation_errors"] = count
                else:
                    item["pronunciation_errors"] = count
                item["total_errors"] += count
        conn.close()

        return result

    def get_word_progress(self, word: str, user_id: str) -> dict:
        """获取某个单词的练习进度（attempts, best_score, avg_score等）"""
        conn = _get_conn(self.db_path)
        row = conn.execute(
            "SELECT word, attempts, best_score, avg_score, mastered FROM user_word_progress WHERE user_id = ? AND word = ?",
            (user_id, word)
        ).fetchone()
        conn.close()
        if row:
            return {
                "word": row[0],
                "attempts": row[1],
                "best_score": row[2],
                "avg_score": row[3],
                "mastered": bool(row[4]),
            }
        return None


# 全局实例
_learning_algo: Optional[LearningAlgorithm] = None


def get_learning_algorithm() -> LearningAlgorithm:
    global _learning_algo
    if _learning_algo is None:
        _learning_algo = LearningAlgorithm()
    return _learning_algo
