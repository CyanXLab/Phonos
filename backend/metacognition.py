"""
Phonos 元认知层 (Metacognition Layer) — 教学生「如何学习」

核心功能：
1. 认知镜像 (Cognitive Mirror) — 实时用户学习路径画像
   - 分类用户为五种学习原型
   - 计算速度、保持率、覆盖面、信心准确度差距等指标

2. 预测校准 (Prediction Calibration) — 针对过度自信用户
   - 练习前后对比预测分数与实际分数
   - 追踪校准历史，计算校准分数
   - 自动为「高自信低准确型」用户启用

3. 策略推荐 (Strategy Recommendation) — 基于认知画像
   - 为每种原型提供个性化学习策略
   - 输出 FSRS 参数调整建议

4. 学习质量评估 (Learning Session Quality)
   - 追踪每次学习会话的指标
   - 检测「僵尸学习」模式（低参与度）
   - 评估会话质量

数据源：
- fsrs_db: 复习记录、卡片状态、用户参数
- learning_algorithm: 评测成绩、薄弱项分析

设计原则：
- 使用懒加载导入 fsrs_db 和 learning_algorithm，避免循环依赖
- 所有方法均有完整的错误处理，不会因外部数据缺失而崩溃
- 中文文档，生产级代码质量
"""

import sqlite3
import time
import json
import math
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime

# ============================================================
# 数据库路径
# ============================================================
DB_PATH = Path(__file__).parent / "phonos_metacognition.db"

# ============================================================
# 学习原型常量
# ============================================================
ARCHETYPE_SPEED_EATER = "囫囵吞枣型"        # 高速度，低保持率
ARCHETYPE_PERFECTIONIST = "完美主义型"       # 高准确率，低覆盖面
ARCHETYPE_STEADY = "稳健进步型"              # 均衡的速度与保持率
ARCHETYPE_OVERCONFIDENT = "高自信低准确型"   # 高信心评级但实际得分低
ARCHETYPE_ANXIOUS = "焦虑型"                 # 高 Again 率，低 Easy 使用

# 所有原型列表
ALL_ARCHETYPES = [
    ARCHETYPE_SPEED_EATER,
    ARCHETYPE_PERFECTIONIST,
    ARCHETYPE_STEADY,
    ARCHETYPE_OVERCONFIDENT,
    ARCHETYPE_ANXIOUS,
]

# 原型描述映射
ARCHETYPE_DESCRIPTIONS = {
    ARCHETYPE_SPEED_EATER: "你学习速度很快，但很多内容没有真正记住。快速刷完不等于掌握，需要放慢节奏、加深印象。",
    ARCHETYPE_PERFECTIONIST: "你对每张卡片都追求完美，但这导致你覆盖的内容较少。学习需要广度与深度的平衡。",
    ARCHETYPE_STEADY: "你的学习节奏很好，速度和保持率比较均衡。继续保持，可以适当增加挑战。",
    ARCHETYPE_OVERCONFIDENT: "你倾向于高估自己的掌握程度，实际表现往往低于预期。需要更客观地评估自己的水平。",
    ARCHETYPE_ANXIOUS: "你对学习内容缺乏信心，即使是简单的内容也容易标记为「不会」。需要从简单内容开始建立信心。",
}

# 原型优势映射
ARCHETYPE_STRENGTHS = {
    ARCHETYPE_SPEED_EATER: ["学习动力强", "接触面广", "不畏惧新内容"],
    ARCHETYPE_PERFECTIONIST: ["掌握扎实", "注重细节", "学习质量高"],
    ARCHETYPE_STEADY: ["节奏稳定", "兼顾广度与深度", "可持续的学习习惯"],
    ARCHETYPE_OVERCONFIDENT: ["学习自信", "敢于尝试", "复习意愿强"],
    ARCHETYPE_ANXIOUS: ["谨慎认真", "不轻易放过疑点", "对错误敏感"],
}

# 原型劣势映射
ARCHETYPE_WEAKNESSES = {
    ARCHETYPE_SPEED_EATER: ["保持率低", "浅层记忆", "需要反复重学"],
    ARCHETYPE_PERFECTIONIST: ["进度缓慢", "覆盖面窄", "容易卡在少数卡片"],
    ARCHETYPE_STEADY: ["缺乏突破", "可能错过薄弱项", "需要适度增加强度"],
    ARCHETYPE_OVERCONFIDENT: ["自我评估不准", "实际掌握低于预期", "容易忽视薄弱项"],
    ARCHETYPE_ANXIOUS: ["效率低", "信心不足", "过度复习简单内容"],
}

# ============================================================
# 策略配置
# ============================================================
ARCHETYPE_STRATEGIES = {
    ARCHETYPE_SPEED_EATER: [
        "慢下来，每张卡片至少思考5秒再评级",
        "使用预测校准功能，在评级前预估自己的掌握程度",
        "评级时更严格，只有真正记住才给 Good/Easy",
        "定期回顾「Again」卡片，确认是否真的掌握了",
        "减少每日新卡片数，把精力放在巩固上",
    ],
    ARCHETYPE_PERFECTIONIST: [
        "扩大覆盖面，不要反复刷同一批卡片",
        "允许自己犯错，Again 不丢人，是学习的一部分",
        "增加每日新卡片数，接触更多内容",
        "对得分 70+ 的卡片可以给 Good，不必追求 90+",
        "设定时间限制，避免单张卡片停留过久",
    ],
    ARCHETYPE_OVERCONFIDENT: [
        "强制开启预测校准，在评级前评估自己的确定程度",
        "评级前先在心里默念答案，确认真的会了再评级",
        "记录自己给 Easy 但实际出错的卡片，反思原因",
        "对不确定的内容降低评级，宁可 Hard 也不要盲目 Easy",
        "每周回顾预测校准数据，调整自我认知",
    ],
    ARCHETYPE_ANXIOUS: [
        "从简单内容开始，建立信心",
        "给自己更多 Easy 评级，认可自己的进步",
        "降低每日目标，完成比完美更重要",
        "使用短时高频的学习方式，避免长时间疲劳",
        "记录进步轨迹，看到自己的成长",
    ],
    ARCHETYPE_STEADY: [
        "保持节奏，当前方法很好",
        "可以适当增加每日新卡片数，挑战自己",
        "关注薄弱音素，进行针对性练习",
        "尝试更难的内容，突破舒适区",
        "定期检查学习分析，优化学习计划",
    ],
}

# ============================================================
# 原型分类阈值
# ============================================================
# 速度（reviews_per_day）阈值
SPEED_HIGH = 0.8    # 高速度（归一化后）
SPEED_LOW = 5.0      # 低速度

# 保持率阈值
RETENTION_HIGH = 0.85   # 高保持率
RETENTION_LOW = 0.6     # 低保持率

# 覆盖面阈值
COVERAGE_HIGH = 0.6   # 高覆盖面
COVERAGE_LOW = 0.2    # 低覆盖面

# Again 率阈值
AGAIN_RATE_HIGH = 0.35   # 高 Again 率
AGAIN_RATE_LOW = 0.10    # 低 Again 率

# Easy 率阈值
EASY_RATE_LOW = 0.10   # 低 Easy 率

# 信心-准确度差距阈值（正值 = 过度自信）
CONFIDENCE_GAP_HIGH = 0.15   # 高过度自信


# ============================================================
# 数据库初始化与辅助函数
# ============================================================

def _get_conn(db_path: str = None) -> sqlite3.Connection:
    """获取数据库连接"""
    return sqlite3.connect(db_path or str(DB_PATH))


def _safe_float(value, default: float = 0.0) -> float:
    """安全转换为浮点数"""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    """安全转换为整数"""
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


# ============================================================
# 元认知引擎
# ============================================================

class MetacognitionEngine:
    """元认知引擎 — 教学生「如何学习」

    核心职责：
    1. 分析用户学习行为，识别学习原型
    2. 追踪预测校准，帮助过度自信用户
    3. 推荐个性化学习策略
    4. 评估学习会话质量
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self._init_db()

    def _init_db(self):
        """初始化数据库表结构"""
        conn = _get_conn(self.db_path)
        conn.executescript("""
            -- 认知画像表：存储用户的学习原型和核心指标
            CREATE TABLE IF NOT EXISTS cognitive_profiles (
                user_id TEXT PRIMARY KEY,
                archetype TEXT NOT NULL DEFAULT '稳健进步型',
                speed REAL NOT NULL DEFAULT 0,
                retention REAL NOT NULL DEFAULT 0,
                coverage REAL NOT NULL DEFAULT 0,
                confidence_accuracy_gap REAL NOT NULL DEFAULT 0,
                again_rate REAL NOT NULL DEFAULT 0,
                easy_rate REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL DEFAULT 0
            );

            -- 预测校准表：记录用户预测分数与实际分数的对比
            CREATE TABLE IF NOT EXISTS prediction_calibrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                card_id TEXT NOT NULL,
                card_type TEXT NOT NULL DEFAULT 'sentence',
                predicted_score REAL NOT NULL,
                actual_score REAL NOT NULL,
                delta REAL NOT NULL,
                created_at REAL NOT NULL DEFAULT 0
            );

            -- 学习会话表：记录每次学习会话的指标
            CREATE TABLE IF NOT EXISTS learning_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                cards_reviewed INTEGER NOT NULL DEFAULT 0,
                avg_rating REAL NOT NULL DEFAULT 0,
                score_variance REAL NOT NULL DEFAULT 0,
                quality_score REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL DEFAULT 0
            );

            -- 策略历史表：记录向用户推荐过的策略
            CREATE TABLE IF NOT EXISTS strategy_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                archetype TEXT NOT NULL,
                strategies_applied TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL DEFAULT 0
            );

            -- 索引
            CREATE INDEX IF NOT EXISTS idx_calibration_user ON prediction_calibrations(user_id);
            CREATE INDEX IF NOT EXISTS idx_calibration_time ON prediction_calibrations(created_at);
            CREATE INDEX IF NOT EXISTS idx_session_user ON learning_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_session_time ON learning_sessions(start_time);
            CREATE INDEX IF NOT EXISTS idx_strategy_user ON strategy_history(user_id);
            CREATE INDEX IF NOT EXISTS idx_strategy_time ON strategy_history(created_at);
        """)
        conn.commit()
        conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        """获取当前数据库连接"""
        return _get_conn(self.db_path)

    # ================================================================
    # 懒加载外部依赖
    # ================================================================

    def _get_fsrs_db(self):
        """懒加载 fsrs_db 模块，避免循环依赖"""
        try:
            from fsrs_db import get_fsrs_db
            return get_fsrs_db()
        except Exception:
            return None

    def _get_learning_algorithm(self):
        """懒加载 learning_algorithm 模块，避免循环依赖"""
        try:
            from learning_algorithm import get_learning_algorithm
            return get_learning_algorithm()
        except Exception:
            return None

    # ================================================================
    # 1. 认知镜像 (Cognitive Mirror)
    # ================================================================

    def _compute_speed(self, user_id: str) -> float:
        """计算速度指标：最近7天平均每日复习数的归一化值

        归一化方式：reviews_per_day / 20（每日20次以上复习视为速度满分）
        这样返回值在 [0, 1] 范围内，更合理地表示学习速度。

        Returns:
            speed (float): 速度指标 [0, 1]
        """
        fsrs = self._get_fsrs_db()
        if not fsrs:
            return 0.0

        try:
            conn = fsrs._get_conn()
            seven_days_ago = time.time() - 7 * 86400
            count = conn.execute(
                "SELECT COUNT(*) FROM review_log WHERE user_id = ? AND review_time >= ?",
                (user_id, seven_days_ago)
            ).fetchone()[0]
            conn.close()

            if count == 0:
                return 0.0

            # 计算实际活跃天数
            active_days = max(1, min(7, count))  # 估算活跃天数
            reviews_per_day = count / active_days

            # 归一化：每日20次以上视为速度满分1.0
            speed = min(1.0, reviews_per_day / 20.0)
            return round(speed, 4)
        except Exception:
            return 0.0

    def _compute_retention(self, user_id: str) -> float:
        """计算保持率指标：最近30次复习中 rating>=3 的比例

        FSRS 评级: 1=Again, 2=Hard, 3=Good, 4=Easy
        rating >= 3 表示成功回忆。

        Returns:
            retention (float): 保持率 [0, 1]
        """
        fsrs = self._get_fsrs_db()
        if not fsrs:
            return 0.0

        try:
            conn = fsrs._get_conn()
            rows = conn.execute(
                "SELECT rating FROM review_log WHERE user_id = ? ORDER BY review_time DESC LIMIT 30",
                (user_id,)
            ).fetchall()
            conn.close()

            if not rows:
                return 0.0

            good_or_above = sum(1 for r in rows if r[0] >= 3)
            return round(good_or_above / len(rows), 4)
        except Exception:
            return 0.0

    def _compute_coverage(self, user_id: str) -> float:
        """计算覆盖面指标：用户尝试过的不同句子卡片占所有可用句子卡片的比例

        只计算 sentence 类型卡片，不包含 word 类型（word 数量太多会严重拉低覆盖率）

        Returns:
            coverage (float): 覆盖率 [0, 1]
        """
        fsrs = self._get_fsrs_db()
        if not fsrs:
            return 0.0

        try:
            conn = fsrs._get_conn()
            # 用户尝试过的句子卡片数（state != NEW 表示已学过）
            attempted = conn.execute(
                "SELECT COUNT(*) FROM cards WHERE user_id = ? AND card_type = 'sentence' AND state != 0",
                (user_id,)
            ).fetchone()[0]

            # 总可用句子卡片数
            total = conn.execute(
                "SELECT COUNT(*) FROM cards WHERE user_id = ? AND card_type = 'sentence'",
                (user_id,)
            ).fetchone()[0]
            conn.close()

            if total == 0:
                return 0.0

            return round(attempted / total, 4)
        except Exception:
            return 0.0

    def _compute_confidence_accuracy_gap(self, user_id: str) -> float:
        """计算信心-准确度差距

        信心 = 用户 FSRS 评级中 Good/Easy 的比例（代表自认为掌握了）
        准确度 = learning_algorithm 中最近评测的平均得分 / 100

        正值 = 过度自信（高自信低准确）
        负值 = 低自信（实际比自认为的好）

        Returns:
            confidence_accuracy_gap (float): 差距值，正=过度自信
        """
        # 信心：FSRS 评级中 >= 3 的比例
        fsrs = self._get_fsrs_db()
        confidence = 0.0
        if fsrs:
            try:
                conn = fsrs._get_conn()
                rows = conn.execute(
                    "SELECT rating FROM review_log WHERE user_id = ? ORDER BY review_time DESC LIMIT 30",
                    (user_id,)
                ).fetchall()
                conn.close()
                if rows:
                    confidence = sum(1 for r in rows if r[0] >= 3) / len(rows)
            except Exception:
                pass

        # 准确度：最近评测的平均得分 / 100
        algo = self._get_learning_algorithm()
        accuracy = 0.0
        if algo:
            try:
                conn_algo = _get_conn(algo.db_path)
                avg_row = conn_algo.execute(
                    "SELECT AVG(overall_score) FROM user_evaluations WHERE user_id = ? ORDER BY evaluated_at DESC LIMIT 20",
                    (user_id,)
                ).fetchone()
                conn_algo.close()
                if avg_row and avg_row[0]:
                    accuracy = avg_row[0] / 100.0
            except Exception:
                pass

        return round(confidence - accuracy, 4)

    def _compute_again_rate(self, user_id: str) -> float:
        """计算 Again 率：最近30次复习中 rating=1 的比例

        Returns:
            again_rate (float): Again 率 [0, 1]
        """
        fsrs = self._get_fsrs_db()
        if not fsrs:
            return 0.0

        try:
            conn = fsrs._get_conn()
            rows = conn.execute(
                "SELECT rating FROM review_log WHERE user_id = ? ORDER BY review_time DESC LIMIT 30",
                (user_id,)
            ).fetchall()
            conn.close()

            if not rows:
                return 0.0

            again_count = sum(1 for r in rows if r[0] == 1)
            return round(again_count / len(rows), 4)
        except Exception:
            return 0.0

    def _compute_easy_rate(self, user_id: str) -> float:
        """计算 Easy 率：最近30次复习中 rating=4 的比例

        Returns:
            easy_rate (float): Easy 率 [0, 1]
        """
        fsrs = self._get_fsrs_db()
        if not fsrs:
            return 0.0

        try:
            conn = fsrs._get_conn()
            rows = conn.execute(
                "SELECT rating FROM review_log WHERE user_id = ? ORDER BY review_time DESC LIMIT 30",
                (user_id,)
            ).fetchall()
            conn.close()

            if not rows:
                return 0.0

            easy_count = sum(1 for r in rows if r[0] == 4)
            return round(easy_count / len(rows), 4)
        except Exception:
            return 0.0

    def _classify_archetype(self, metrics: Dict) -> str:
        """根据指标分类用户原型

        分类规则（按优先级从高到低）：
        1. 高自信低准确型: confidence_accuracy_gap > 0.15
        2. 囫囵吞枣型: speed > 15 且 retention < 0.6 且 again_rate > 0.35
        3. 焦虑型: again_rate > 0.35 且 easy_rate < 0.10
        4. 完美主义型: retention > 0.85 且 coverage < 0.2
        5. 稳健进步型: 默认（不满足以上任何条件）

        Args:
            metrics: 包含 speed, retention, coverage, confidence_accuracy_gap,
                     again_rate, easy_rate 的字典

        Returns:
            archetype (str): 原型名称
        """
        speed = metrics.get("speed", 0)
        retention = metrics.get("retention", 0)
        coverage = metrics.get("coverage", 0)
        confidence_gap = metrics.get("confidence_accuracy_gap", 0)
        again_rate = metrics.get("again_rate", 0)
        easy_rate = metrics.get("easy_rate", 0)

        # 1. 高自信低准确型（优先级最高，因为这种误判危害最大）
        if confidence_gap > CONFIDENCE_GAP_HIGH:
            return ARCHETYPE_OVERCONFIDENT

        # 2. 囫囵吞枣型：高速度 + 低保持率 + 高 Again 率
        if speed > SPEED_HIGH and retention < RETENTION_LOW and again_rate > AGAIN_RATE_HIGH:
            return ARCHETYPE_SPEED_EATER

        # 3. 焦虑型：高 Again 率 + 低 Easy 使用（即使简单内容也不放心）
        if again_rate > AGAIN_RATE_HIGH and easy_rate < EASY_RATE_LOW:
            return ARCHETYPE_ANXIOUS

        # 4. 完美主义型：高保持率 + 低覆盖面
        if retention > RETENTION_HIGH and coverage < COVERAGE_LOW:
            return ARCHETYPE_PERFECTIONIST

        # 5. 稳健进步型：默认
        return ARCHETYPE_STEADY

    def _save_cognitive_profile(self, user_id: str, archetype: str, metrics: Dict):
        """将认知画像保存到数据库

        Args:
            user_id: 用户ID
            archetype: 原型名称
            metrics: 指标字典
        """
        try:
            conn = self._get_conn()
            now = time.time()
            conn.execute("""
                INSERT OR REPLACE INTO cognitive_profiles
                (user_id, archetype, speed, retention, coverage,
                 confidence_accuracy_gap, again_rate, easy_rate, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                archetype,
                metrics.get("speed", 0),
                metrics.get("retention", 0),
                metrics.get("coverage", 0),
                metrics.get("confidence_accuracy_gap", 0),
                metrics.get("again_rate", 0),
                metrics.get("easy_rate", 0),
                now,
            ))
            conn.commit()
            conn.close()
        except Exception:
            pass  # 保存失败不影响主流程

    def _get_cached_profile(self, user_id: str) -> Optional[Dict]:
        """获取缓存的认知画像（如果存在且不过期）

        缓存有效期：1小时

        Returns:
            dict 或 None
        """
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT archetype, speed, retention, coverage, confidence_accuracy_gap, "
                "again_rate, easy_rate, updated_at FROM cognitive_profiles WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            conn.close()

            if not row:
                return None

            # 检查是否过期（1小时）
            updated_at = row[7]
            if time.time() - updated_at > 3600:
                return None

            return {
                "archetype": row[0],
                "speed": row[1],
                "retention": row[2],
                "coverage": row[3],
                "confidence_accuracy_gap": row[4],
                "again_rate": row[5],
                "easy_rate": row[6],
                "updated_at": updated_at,
            }
        except Exception:
            return None

    def get_cognitive_profile(self, user_id: str, force_refresh: bool = False) -> Dict:
        """获取用户的认知画像

        实时计算用户的学习行为指标，分类学习原型，
        返回完整的画像信息。

        Args:
            user_id: 用户ID
            force_refresh: 是否强制刷新（忽略缓存）

        Returns:
            dict 包含:
            - archetype: 学习原型名称
            - metrics: 各项指标
            - description: 原型描述
            - strengths: 优势列表
            - weaknesses: 劣势列表
        """
        # 尝试使用缓存
        if not force_refresh:
            cached = self._get_cached_profile(user_id)
            if cached:
                archetype = cached["archetype"]
                return {
                    "archetype": archetype,
                    "metrics": {
                        "speed": cached["speed"],
                        "retention": cached["retention"],
                        "coverage": cached["coverage"],
                        "confidence_accuracy_gap": cached["confidence_accuracy_gap"],
                        "again_rate": cached["again_rate"],
                        "easy_rate": cached["easy_rate"],
                    },
                    "description": ARCHETYPE_DESCRIPTIONS.get(archetype, ""),
                    "strengths": ARCHETYPE_STRENGTHS.get(archetype, []),
                    "weaknesses": ARCHETYPE_WEAKNESSES.get(archetype, []),
                }

        # 实时计算各项指标
        metrics = {
            "speed": self._compute_speed(user_id),
            "retention": self._compute_retention(user_id),
            "coverage": self._compute_coverage(user_id),
            "confidence_accuracy_gap": self._compute_confidence_accuracy_gap(user_id),
            "again_rate": self._compute_again_rate(user_id),
            "easy_rate": self._compute_easy_rate(user_id),
        }

        # 分类原型
        archetype = self._classify_archetype(metrics)

        # 保存到数据库
        self._save_cognitive_profile(user_id, archetype, metrics)

        return {
            "archetype": archetype,
            "metrics": metrics,
            "description": ARCHETYPE_DESCRIPTIONS.get(archetype, ""),
            "strengths": ARCHETYPE_STRENGTHS.get(archetype, []),
            "weaknesses": ARCHETYPE_WEAKNESSES.get(archetype, []),
        }

    # ================================================================
    # 2. 预测校准 (Prediction Calibration)
    # ================================================================

    def record_prediction(self, user_id: str, card_id: str,
                          predicted_score: float, actual_score: float,
                          card_type: str = "sentence") -> Dict:
        """记录一次预测校准数据

        在每次练习前，让用户预测自己的得分（0-100），
        练习后与实际得分对比，追踪校准历史。

        Args:
            user_id: 用户ID
            card_id: 卡片ID
            predicted_score: 用户预测的分数 (0-100)
            actual_score: 实际得分 (0-100)
            card_type: 卡片类型（默认 sentence）

        Returns:
            dict 包含:
            - predicted_score: 预测分数
            - actual_score: 实际分数
            - delta: 差值（预测 - 实际，正值 = 过度自信）
            - calibration_score: 当前校准分数
            - message: 反馈消息
        """
        # 参数校验
        predicted_score = max(0, min(100, _safe_float(predicted_score)))
        actual_score = max(0, min(100, _safe_float(actual_score)))

        delta = round(predicted_score - actual_score, 2)

        try:
            conn = self._get_conn()
            now = time.time()
            conn.execute("""
                INSERT INTO prediction_calibrations
                (user_id, card_id, card_type, predicted_score, actual_score, delta, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, card_id, card_type, predicted_score, actual_score, delta, now))
            conn.commit()
            conn.close()
        except Exception as e:
            return {
                "predicted_score": predicted_score,
                "actual_score": actual_score,
                "delta": delta,
                "calibration_score": 0.0,
                "message": f"保存预测校准数据失败: {str(e)}",
            }

        # 获取更新后的校准分数
        stats = self.get_calibration_stats(user_id)
        calibration_score = stats.get("calibration_score", 0.0)

        # 生成反馈消息
        if abs(delta) <= 5:
            message = "🎯 预测非常准确！你的自我评估能力很好。"
        elif delta > 5 and delta <= 20:
            message = f"你略微高估了自己（差{abs(delta):.0f}分），注意更客观地评估。"
        elif delta > 20:
            message = f"你明显高估了自己（差{abs(delta):.0f}分），建议更谨慎地评估掌握程度。"
        elif delta < -5 and delta >= -20:
            message = f"你低估了自己（实际高{abs(delta):.0f}分），可以更有信心！"
        else:
            message = f"你大大低估了自己（实际高{abs(delta):.0f}分），你的实际水平比想象的好！"

        return {
            "predicted_score": predicted_score,
            "actual_score": actual_score,
            "delta": delta,
            "calibration_score": calibration_score,
            "message": message,
        }

    def get_calibration_stats(self, user_id: str) -> Dict:
        """获取用户的预测校准统计

        校准分数 = 1 - mean(|predicted - actual| / 100)
        - 1.0 = 完美校准
        - 0.0 = 完全不准确

        Args:
            user_id: 用户ID

        Returns:
            dict 包含:
            - calibration_score: 校准分数 [0, 1]
            - recent_predictions: 最近10次预测记录
            - trend: 趋势（"improving" / "stable" / "worsening"）
        """
        try:
            conn = self._get_conn()

            # 获取最近的预测记录（最多50条用于统计）
            rows = conn.execute(
                "SELECT predicted_score, actual_score, delta, created_at "
                "FROM prediction_calibrations WHERE user_id = ? "
                "ORDER BY created_at DESC LIMIT 50",
                (user_id,)
            ).fetchall()
            conn.close()

            if not rows:
                return {
                    "calibration_score": 0.0,
                    "recent_predictions": [],
                    "trend": "stable",
                    "total_predictions": 0,
                }

            # 计算校准分数
            abs_errors = [abs(r[2]) / 100.0 for r in rows]
            mean_error = sum(abs_errors) / len(abs_errors)
            calibration_score = round(max(0, 1.0 - mean_error), 4)

            # 最近10次预测记录
            recent = [
                {
                    "predicted_score": r[0],
                    "actual_score": r[1],
                    "delta": r[2],
                    "created_at": r[3],
                }
                for r in rows[:10]
            ]

            # 计算趋势（比较前半段和后半段的平均误差）
            trend = "stable"
            if len(rows) >= 6:
                half = len(rows) // 2
                older = rows[half:]   # 更早的记录（因为已按时间倒序）
                newer = rows[:half]   # 更近的记录

                older_avg_error = sum(abs(r[2]) for r in older) / len(older)
                newer_avg_error = sum(abs(r[2]) for r in newer) / len(newer)

                if newer_avg_error < older_avg_error - 3:
                    trend = "improving"
                elif newer_avg_error > older_avg_error + 3:
                    trend = "worsening"

            return {
                "calibration_score": calibration_score,
                "recent_predictions": recent,
                "trend": trend,
                "total_predictions": len(rows),
            }
        except Exception:
            return {
                "calibration_score": 0.0,
                "recent_predictions": [],
                "trend": "stable",
                "total_predictions": 0,
            }

    def should_enable_calibration(self, user_id: str) -> bool:
        """判断是否应该为用户启用预测校准

        自动为「高自信低准确型」用户启用。
        也可用于其他需要校准的场景。

        Args:
            user_id: 用户ID

        Returns:
            bool: 是否应启用预测校准
        """
        profile = self.get_cognitive_profile(user_id)
        return profile["archetype"] == ARCHETYPE_OVERCONFIDENT

    # ================================================================
    # 3. 策略推荐 (Strategy Recommendation)
    # ================================================================

    def get_strategy_recommendations(self, user_id: str) -> Dict:
        """获取基于认知画像的策略推荐

        根据用户的学习原型，推荐个性化的学习策略
        和 FSRS 参数调整建议。

        Args:
            user_id: 用户ID

        Returns:
            dict 包含:
            - archetype: 学习原型
            - strategies: 策略列表
            - param_adjustments: FSRS 参数调整建议
        """
        profile = self.get_cognitive_profile(user_id)
        archetype = profile["archetype"]

        # 获取策略
        strategies = ARCHETYPE_STRATEGIES.get(archetype, [])

        # 生成 FSRS 参数调整建议
        param_adjustments = self._compute_param_adjustments(user_id, archetype)

        # 记录策略历史
        self._record_strategy_history(user_id, archetype, strategies)

        return {
            "archetype": archetype,
            "strategies": strategies,
            "param_adjustments": param_adjustments,
        }

    def _compute_param_adjustments(self, user_id: str, archetype: str) -> Dict:
        """根据原型计算 FSRS 参数调整建议

        各原型的参数调整策略：
        - 囫囵吞枣型: 提高期望保持率，减少新卡片数
        - 完美主义型: 降低期望保持率，增加新卡片数
        - 高自信低准确型: 提高期望保持率，强制开启预测校准
        - 焦虑型: 降低期望保持率，减少新卡片数，增加学习步骤
        - 稳健进步型: 保持当前参数，可适当增加新卡片数

        Args:
            user_id: 用户ID
            archetype: 学习原型

        Returns:
            dict: 参数调整建议
        """
        # 获取当前用户参数
        fsrs = self._get_fsrs_db()
        current_params = {
            "desired_retention": 0.9,
            "new_per_day": 5,
            "learning_steps": [1, 10],
            "relearning_steps": [10],
            "maximum_interval": 36500,
        }

        if fsrs:
            try:
                user_config = fsrs.get_user_params(user_id)
                current_params = {
                    "desired_retention": user_config.get("desired_retention", 0.9),
                    "new_per_day": user_config.get("new_per_day", 5),
                    "learning_steps": user_config.get("learning_steps", [1, 10]),
                    "relearning_steps": user_config.get("relearning_steps", [10]),
                    "maximum_interval": user_config.get("maximum_interval", 36500),
                }
            except Exception:
                pass

        adjustments = {
            "current": current_params.copy(),
            "recommended": {},
            "reason": "",
        }

        if archetype == ARCHETYPE_SPEED_EATER:
            # 囫囵吞枣型：需要放慢节奏、加深记忆
            adjustments["recommended"] = {
                "desired_retention": min(0.95, current_params["desired_retention"] + 0.05),
                "new_per_day": max(2, current_params["new_per_day"] - 2),
                "learning_steps": [1, 5, 10],  # 增加学习步骤
            }
            adjustments["reason"] = "提高期望保持率，减少每日新卡片，增加学习步骤以加深记忆"

        elif archetype == ARCHETYPE_PERFECTIONIST:
            # 完美主义型：需要扩大覆盖面
            adjustments["recommended"] = {
                "desired_retention": max(0.8, current_params["desired_retention"] - 0.05),
                "new_per_day": min(15, current_params["new_per_day"] + 3),
                "learning_steps": [1, 10],  # 简化学习步骤
            }
            adjustments["reason"] = "适度降低期望保持率，增加每日新卡片，简化学习步骤以扩大覆盖面"

        elif archetype == ARCHETYPE_OVERCONFIDENT:
            # 高自信低准确型：需要更严格的复习标准
            adjustments["recommended"] = {
                "desired_retention": min(0.95, current_params["desired_retention"] + 0.05),
                "new_per_day": current_params["new_per_day"],  # 保持不变
                "enable_calibration": True,  # 强制开启预测校准
            }
            adjustments["reason"] = "提高期望保持率以增加复习频率，强制开启预测校准以改善自我评估"

        elif archetype == ARCHETYPE_ANXIOUS:
            # 焦虑型：需要降低压力、建立信心
            adjustments["recommended"] = {
                "desired_retention": max(0.8, current_params["desired_retention"] - 0.05),
                "new_per_day": max(2, current_params["new_per_day"] - 2),
                "learning_steps": [1, 3, 5, 10],  # 更细的学习步骤
            }
            adjustments["reason"] = "降低期望保持率减少压力，减少新卡片避免过载，更细的学习步骤帮助渐进掌握"

        else:
            # 稳健进步型：保持当前，可适当增加
            adjustments["recommended"] = {
                "desired_retention": current_params["desired_retention"],
                "new_per_day": min(12, current_params["new_per_day"] + 1),
            }
            adjustments["reason"] = "当前参数合理，可适当增加每日新卡片数以提升进度"

        return adjustments

    def apply_param_adjustments(self, user_id: str) -> Dict:
        """将策略推荐的参数调整应用到用户的 FSRS 配置

        只有推荐值与当前值不同时才会更新。

        Args:
            user_id: 用户ID

        Returns:
            dict: 应用结果
        """
        recommendations = self.get_strategy_recommendations(user_id)
        param_adjustments = recommendations.get("param_adjustments", {})
        recommended = param_adjustments.get("recommended", {})

        if not recommended:
            return {"applied": False, "reason": "无推荐参数调整"}

        fsrs = self._get_fsrs_db()
        if not fsrs:
            return {"applied": False, "reason": "FSRS 模块不可用"}

        try:
            # 构建参数更新字典（只包含有变化的参数）
            update_dict = {}
            for key in ["desired_retention", "new_per_day", "learning_steps",
                        "relearning_steps", "maximum_interval"]:
                if key in recommended:
                    update_dict[key] = recommended[key]

            if update_dict:
                fsrs.set_user_params(user_id, update_dict)
                return {
                    "applied": True,
                    "updated_params": update_dict,
                    "reason": param_adjustments.get("reason", ""),
                }
            else:
                return {"applied": False, "reason": "无参数需要更新"}
        except Exception as e:
            return {"applied": False, "reason": f"应用参数失败: {str(e)}"}

    def _record_strategy_history(self, user_id: str, archetype: str, strategies: List[str]):
        """记录策略推荐历史

        Args:
            user_id: 用户ID
            archetype: 原型名称
            strategies: 策略列表
        """
        try:
            conn = self._get_conn()
            now = time.time()
            conn.execute("""
                INSERT INTO strategy_history (user_id, archetype, strategies_applied, created_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, archetype, json.dumps(strategies, ensure_ascii=False), now))
            conn.commit()
            conn.close()
        except Exception:
            pass

    # ================================================================
    # 4. 学习质量评估 (Learning Session Quality)
    # ================================================================

    def record_session(self, user_id: str, session_data: Dict) -> Dict:
        """记录一次学习会话

        Args:
            user_id: 用户ID
            session_data: 会话数据，包含:
                - start_time: 开始时间（时间戳，秒）
                - end_time: 结束时间（时间戳，秒）
                - cards_reviewed: 复习卡片数
                - avg_rating: 平均评级 (1-4)
                - score_variance: 评级方差
                - ratings: 评级列表（可选，用于僵尸学习检测）
                - review_durations: 复习用时列表（可选，秒）

        Returns:
            dict 包含:
            - quality_score: 质量分数 [0, 100]
            - is_zombie_learning: 是否检测到僵尸学习
            - feedback: 反馈消息
        """
        start_time = _safe_float(session_data.get("start_time"), time.time() - 600)
        end_time = _safe_float(session_data.get("end_time"), time.time())
        cards_reviewed = _safe_int(session_data.get("cards_reviewed"), 0)
        avg_rating = _safe_float(session_data.get("avg_rating"), 0)
        score_variance = _safe_float(session_data.get("score_variance"), 0)

        # 检测僵尸学习
        is_zombie = self._detect_zombie_learning(session_data)

        # 计算质量分数
        quality_score = self._compute_session_quality(
            user_id, session_data, is_zombie
        )

        # 保存到数据库
        try:
            conn = self._get_conn()
            now = time.time()
            conn.execute("""
                INSERT INTO learning_sessions
                (user_id, start_time, end_time, cards_reviewed, avg_rating,
                 score_variance, quality_score, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, start_time, end_time, cards_reviewed,
                avg_rating, score_variance, quality_score, now
            ))
            conn.commit()
            conn.close()
        except Exception:
            pass

        # 生成反馈
        feedback = self._generate_session_feedback(quality_score, is_zombie, avg_rating)

        return {
            "quality_score": quality_score,
            "is_zombie_learning": is_zombie,
            "feedback": feedback,
        }

    def _detect_zombie_learning(self, session_data: Dict) -> bool:
        """检测僵尸学习模式

        僵尸学习特征：
        1. 连续多次 Again 评级（快速连续按 Again）
        2. 复习间隔极短（每次复习不到2秒）
        3. 平均评级极低且无波动（机械式操作）

        Args:
            session_data: 会话数据

        Returns:
            bool: 是否检测到僵尸学习
        """
        ratings = session_data.get("ratings", [])
        review_durations = session_data.get("review_durations", [])

        # 检测1：连续 Again（3次或以上）
        if ratings and len(ratings) >= 3:
            consecutive_again = 0
            for r in ratings:
                if r == 1:
                    consecutive_again += 1
                    if consecutive_again >= 3:
                        return True
                else:
                    consecutive_again = 0

        # 检测2：极短的复习间隔（平均低于2秒，且至少5次复习）
        if review_durations and len(review_durations) >= 5:
            avg_duration = sum(review_durations) / len(review_durations)
            if avg_duration < 2.0:
                return True

        # 检测3：机械式操作（全部相同评级且为低评级，至少10次）
        if ratings and len(ratings) >= 10:
            unique_ratings = set(ratings)
            if len(unique_ratings) == 1 and list(unique_ratings)[0] <= 2:
                return True

        return False

    def _compute_session_quality(self, user_id: str, session_data: Dict,
                                  is_zombie: bool) -> float:
        """计算学习会话质量分数

        评估维度：
        1. 参与度：复习卡片数量、平均用时
        2. 效果：平均评级、评级分布
        3. 专注度：是否僵尸学习、评级波动

        质量分数 = 基础分 × 参与度系数 × 效果系数 × 专注度系数

        Args:
            user_id: 用户ID
            session_data: 会话数据
            is_zombie: 是否僵尸学习

        Returns:
            quality_score (float): 质量分数 [0, 100]
        """
        # 基础分
        base_score = 50.0

        cards_reviewed = _safe_int(session_data.get("cards_reviewed"), 0)
        avg_rating = _safe_float(session_data.get("avg_rating"), 0)
        score_variance = _safe_float(session_data.get("score_variance"), 0)
        review_durations = session_data.get("review_durations", [])
        start_time = _safe_float(session_data.get("start_time"), 0)
        end_time = _safe_float(session_data.get("end_time"), 0)

        # 1. 参与度系数（基于复习数量）
        engagement_factor = 1.0
        if cards_reviewed <= 0:
            engagement_factor = 0.3
        elif cards_reviewed <= 5:
            engagement_factor = 0.7
        elif cards_reviewed <= 15:
            engagement_factor = 1.0
        elif cards_reviewed <= 30:
            engagement_factor = 1.1
        else:
            engagement_factor = 1.15  # 大量复习有小幅加成但不过分

        # 2. 效果系数（基于平均评级）
        effectiveness_factor = 1.0
        if avg_rating <= 0:
            effectiveness_factor = 0.5
        elif avg_rating < 2.0:
            # 大量 Again/Hard，效果较差
            effectiveness_factor = 0.7
        elif avg_rating < 2.5:
            effectiveness_factor = 0.85
        elif avg_rating < 3.5:
            # Good 为主，效果良好
            effectiveness_factor = 1.0
        else:
            # 太多 Easy 可能是轻率评级
            effectiveness_factor = 0.9

        # 3. 专注度系数（基于评级波动和用时）
        focus_factor = 1.0
        if is_zombie:
            focus_factor = 0.3  # 僵尸学习大幅扣分

        # 平均用时合理性检查
        if review_durations and len(review_durations) >= 3:
            avg_duration = sum(review_durations) / len(review_durations)
            if avg_duration < 3:
                focus_factor *= 0.7  # 用时过短
            elif avg_duration > 60:
                focus_factor *= 0.9  # 用时过长可能分心
            else:
                focus_factor *= 1.05  # 合理用时

        # 评级波动检查（完全没有波动可能意味着机械操作）
        if cards_reviewed >= 5:
            if score_variance < 0.1:
                focus_factor *= 0.85  # 评级完全一致，可能是机械操作
            elif 0.1 <= score_variance <= 1.0:
                focus_factor *= 1.05  # 适度的波动是正常的

        # 综合计算质量分数
        quality_score = base_score * engagement_factor * effectiveness_factor * focus_factor
        quality_score = max(0, min(100, round(quality_score, 1)))

        return quality_score

    def _generate_session_feedback(self, quality_score: float,
                                    is_zombie: bool, avg_rating: float) -> str:
        """生成学习会话反馈消息

        Args:
            quality_score: 质量分数
            is_zombie: 是否僵尸学习
            avg_rating: 平均评级

        Returns:
            feedback (str): 反馈消息
        """
        if is_zombie:
            return ("⚠️ 检测到低参与度学习模式。你似乎在机械式地操作，"
                    "建议休息一下再继续，或者换一种学习方式。质量比数量更重要。")

        if quality_score >= 85:
            return "🌟 非常棒的学习会话！专注度和效果都很好，继续保持！"
        elif quality_score >= 70:
            return "👍 不错的学习会话，节奏合理，效果良好。"
        elif quality_score >= 50:
            if avg_rating < 2.5:
                return ("📚 这次会话有不少困难，这是正常的学习过程。"
                        "试着降低难度或者回顾一下之前的内容。")
            else:
                return "📖 学习会话还可以，但可以更加专注和投入。"
        else:
            return ("💡 这次学习效率不高，建议：1) 缩短单次学习时间；"
                    "2) 确保精力充沛时学习；3) 尝试不同的学习方式。")

    def get_session_quality(self, user_id: str) -> Dict:
        """获取用户的学习质量统计

        分析最近的学习会话，提供质量趋势和总体评估。

        Args:
            user_id: 用户ID

        Returns:
            dict 包含:
            - avg_quality_score: 平均质量分数
            - total_sessions: 总会话数
            - zombie_sessions: 僵尸学习会话数
            - quality_trend: 质量趋势
            - recent_sessions: 最近的会话记录
            - recommendation: 质量改进建议
        """
        try:
            conn = self._get_conn()

            # 最近30天的会话
            thirty_days_ago = time.time() - 30 * 86400
            rows = conn.execute(
                "SELECT start_time, end_time, cards_reviewed, avg_rating, "
                "score_variance, quality_score, created_at "
                "FROM learning_sessions WHERE user_id = ? AND created_at >= ? "
                "ORDER BY created_at DESC",
                (user_id, thirty_days_ago)
            ).fetchall()
            conn.close()

            if not rows:
                return {
                    "avg_quality_score": 0.0,
                    "total_sessions": 0,
                    "zombie_sessions": 0,
                    "quality_trend": "no_data",
                    "recent_sessions": [],
                    "recommendation": "还没有学习会话记录，开始学习后将生成质量评估。",
                }

            # 统计数据
            quality_scores = [r[5] for r in rows if r[5] is not None]
            avg_quality = round(sum(quality_scores) / len(quality_scores), 1) if quality_scores else 0.0

            # 僵尸学习检测（quality_score < 30 的会话视为僵尸学习）
            zombie_count = sum(1 for q in quality_scores if q < 30)

            # 质量趋势
            trend = "stable"
            if len(quality_scores) >= 4:
                half = len(quality_scores) // 2
                older = quality_scores[half:]
                newer = quality_scores[:half]
                older_avg = sum(older) / len(older)
                newer_avg = sum(newer) / len(newer)

                if newer_avg > older_avg + 5:
                    trend = "improving"
                elif newer_avg < older_avg - 5:
                    trend = "declining"

            # 最近5次会话
            recent = [
                {
                    "start_time": r[0],
                    "end_time": r[1],
                    "cards_reviewed": r[2],
                    "avg_rating": round(r[3], 2),
                    "score_variance": round(r[4], 4),
                    "quality_score": r[5],
                }
                for r in rows[:5]
            ]

            # 生成改进建议
            recommendation = self._generate_quality_recommendation(
                avg_quality, zombie_count, len(rows), trend
            )

            return {
                "avg_quality_score": avg_quality,
                "total_sessions": len(rows),
                "zombie_sessions": zombie_count,
                "quality_trend": trend,
                "recent_sessions": recent,
                "recommendation": recommendation,
            }
        except Exception:
            return {
                "avg_quality_score": 0.0,
                "total_sessions": 0,
                "zombie_sessions": 0,
                "quality_trend": "no_data",
                "recent_sessions": [],
                "recommendation": "暂无数据。",
            }

    def _generate_quality_recommendation(self, avg_quality: float,
                                          zombie_count: int,
                                          total_sessions: int,
                                          trend: str) -> str:
        """生成学习质量改进建议

        Args:
            avg_quality: 平均质量分数
            zombie_count: 僵尸学习次数
            total_sessions: 总会话数
            trend: 趋势

        Returns:
            recommendation (str): 改进建议
        """
        parts = []

        # 整体评估
        if avg_quality >= 80:
            parts.append("你的学习质量整体很好。")
        elif avg_quality >= 60:
            parts.append("你的学习质量中等，有提升空间。")
        else:
            parts.append("你的学习质量需要改善，建议调整学习方式。")

        # 僵尸学习警告
        if zombie_count > 0:
            ratio = zombie_count / total_sessions
            if ratio > 0.3:
                parts.append(f"⚠️ {zombie_count}次低质量会话占比过高，请确保每次学习都保持专注。")
            else:
                parts.append(f"偶尔的低质量会话是正常的（{zombie_count}次），不必担心。")

        # 趋势反馈
        if trend == "improving":
            parts.append("📈 学习质量在提升，继续加油！")
        elif trend == "declining":
            parts.append("📉 学习质量有所下降，可能需要调整学习节奏或休息一下。")

        # 具体建议
        if avg_quality < 60:
            parts.append("建议：1) 每次学习不超过20分钟；2) 确保精力充沛；3) 尝试更短更频繁的学习。")
        elif avg_quality < 80:
            parts.append("建议：可以尝试增加每次学习的卡片数，或挑战更难的内容。")

        return " ".join(parts)

    # ================================================================
    # 综合分析
    # ================================================================

    def get_full_report(self, user_id: str) -> Dict:
        """获取用户的完整元认知报告

        一次性返回所有元认知信息，包括：
        - 认知画像
        - 预测校准状态
        - 策略推荐
        - 学习质量评估

        Args:
            user_id: 用户ID

        Returns:
            dict: 完整元认知报告
        """
        profile = self.get_cognitive_profile(user_id)
        calibration = self.get_calibration_stats(user_id)
        strategies = self.get_strategy_recommendations(user_id)
        quality = self.get_session_quality(user_id)

        return {
            "cognitive_profile": profile,
            "calibration": calibration,
            "strategies": strategies,
            "session_quality": quality,
            "should_enable_calibration": self.should_enable_calibration(user_id),
        }

    def get_learning_insights(self, user_id: str) -> Dict:
        """获取学习洞察 — 基于所有数据生成可操作的建议

        Args:
            user_id: 用户ID

        Returns:
            dict 包含:
            - top_insight: 最重要的洞察
            - action_items: 可操作的改进项
            - positive_feedback: 正面反馈
        """
        profile = self.get_cognitive_profile(user_id)
        archetype = profile["archetype"]
        metrics = profile["metrics"]

        insights = []
        action_items = []
        positive_feedback = []

        # 基于指标生成洞察
        speed = metrics.get("speed", 0)
        retention = metrics.get("retention", 0)
        coverage = metrics.get("coverage", 0)
        confidence_gap = metrics.get("confidence_accuracy_gap", 0)
        again_rate = metrics.get("again_rate", 0)
        easy_rate = metrics.get("easy_rate", 0)

        # 速度洞察（speed 已归一化到 0-1）
        if speed > 0.8:
            insights.append("你的复习速度非常快，但过快可能影响记忆深度")
            action_items.append("尝试在每次评级前多思考5秒")
        elif speed < 0.15 and speed > 0:
            insights.append("你的复习速度较慢，可能在某些卡片上花了太多时间")
            action_items.append("对不确定的卡片可以先给 Again，不要纠结太久")
        else:
            positive_feedback.append("你的学习节奏适中")

        # 保持率洞察
        if retention < 0.5:
            insights.append("你的记忆保持率偏低，很多内容学完就忘了")
            action_items.append("增加复习频率，使用更短的间隔")
        elif retention > 0.9:
            positive_feedback.append("你的记忆保持率很好，学过的内容大多记住了")
        else:
            positive_feedback.append("你的记忆保持率处于健康水平")

        # 覆盖面洞察
        if coverage < 0.15:
            insights.append("你只覆盖了很小一部分内容")
            action_items.append("尝试增加每日新卡片数，探索更多内容")
        elif coverage > 0.7:
            positive_feedback.append("你已经覆盖了大量内容，广度很好")

        # 信心洞察
        if confidence_gap > 0.2:
            insights.append("你明显高估了自己的掌握程度")
            action_items.append("开启预测校准功能，在评级前预估自己的掌握程度")
        elif confidence_gap < -0.1:
            positive_feedback.append("你比自己想象的更优秀，可以更有信心！")

        # Again 率洞察
        if again_rate > 0.4:
            insights.append("你的 Again 率很高，经常需要重新学习")
            action_items.append("考虑降低难度，或者从更基础的内容开始")

        # Easy 率洞察
        if easy_rate < 0.05 and again_rate < 0.2:
            insights.append("你很少使用 Easy 评级，可能过于保守")
            action_items.append("对真正掌握的内容可以给 Easy，这样能加快进度")

        # 确保有洞察
        if not insights:
            insights.append("你的学习模式比较健康，继续保持")
        if not action_items:
            action_items.append("保持当前的学习节奏和方法")
        if not positive_feedback:
            positive_feedback.append("你正在坚持学习，这本身就是最大的进步")

        return {
            "top_insight": insights[0],
            "all_insights": insights,
            "action_items": action_items,
            "positive_feedback": positive_feedback,
        }


# ============================================================
# 成就系统 (Achievement System)
# ============================================================

ACHIEVEMENTS = [
    {"id": "first_practice", "name": "初次尝试", "icon": "🌟", "desc": "完成第一次练习", "condition": "total_evaluations >= 1"},
    {"id": "ten_practices", "name": "初学之路", "icon": "📚", "desc": "完成10次练习", "condition": "total_evaluations >= 10"},
    {"id": "fifty_practices", "name": "勤学不倦", "icon": "📖", "desc": "完成50次练习", "condition": "total_evaluations >= 50"},
    {"id": "hundred_practices", "name": "百炼成钢", "icon": "🔥", "desc": "完成100次练习", "condition": "total_evaluations >= 100"},
    {"id": "perfect_score", "name": "完美发音", "icon": "💯", "desc": "获得一次90分以上", "condition": "best_score >= 90"},
    {"id": "streak_3", "name": "三日坚持", "icon": "🎯", "desc": "连续学习3天", "condition": "streak >= 3"},
    {"id": "streak_7", "name": "一周达人", "icon": "🏆", "desc": "连续学习7天", "condition": "streak >= 7"},
    {"id": "streak_30", "name": "月度坚持", "icon": "👑", "desc": "连续学习30天", "condition": "streak >= 30"},
    {"id": "vocab_10", "name": "词汇起步", "icon": "📝", "desc": "学习10个单词", "condition": "words_learned >= 10"},
    {"id": "vocab_50", "name": "词汇达人", "icon": "🎓", "desc": "学习50个单词", "condition": "words_learned >= 50"},
    {"id": "vocab_100", "name": "词汇大师", "icon": "🏅", "desc": "学习100个单词", "condition": "words_learned >= 100"},
    {"id": "master_5", "name": "初步掌握", "icon": "✨", "desc": "掌握5个单词", "condition": "words_mastered >= 5"},
    {"id": "master_20", "name": "炉火纯青", "icon": "💎", "desc": "掌握20个单词", "condition": "words_mastered >= 20"},
    {"id": "improve_10", "name": "明显进步", "icon": "📈", "desc": "平均分提升10分", "condition": "improvement >= 10"},
    {"id": "all_phonemes", "name": "音素探索者", "icon": "🔤", "desc": "练习过20个不同音素", "condition": "phonemes_practiced >= 20"},
]

def check_achievements(user_id: str) -> dict:
    """检查用户成就解锁状态
    
    Returns:
        dict: {
            "unlocked": [已解锁成就列表],
            "locked": [未解锁成就列表],
            "stats": 用户统计摘要,
            "total_unlocked": 已解锁数量,
            "total_achievements": 总成就数量,
        }
    """
    from learning_algorithm import get_learning_algorithm
    from fsrs_db import get_fsrs_db
    
    learning = get_learning_algorithm()
    fsrs = get_fsrs_db()
    
    # Gather user stats
    stats = {}
    try:
        import sqlite3 as _sql3
        conn = _sql3.connect(learning.db_path)
        stats["total_evaluations"] = conn.execute(
            "SELECT COUNT(*) FROM user_evaluations WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        score_row = conn.execute(
            "SELECT MAX(overall_score) FROM user_evaluations WHERE user_id = ?", (user_id,)
        ).fetchone()
        stats["best_score"] = score_row[0] if score_row and score_row[0] else 0
        stats["words_learned"] = conn.execute(
            "SELECT COUNT(*) FROM user_word_progress WHERE user_id = ? AND attempts > 0", (user_id,)
        ).fetchone()[0]
        stats["words_mastered"] = conn.execute(
            "SELECT COUNT(*) FROM user_word_progress WHERE user_id = ? AND mastered = 1", (user_id,)
        ).fetchone()[0]
        stats["phonemes_practiced"] = conn.execute(
            "SELECT COUNT(DISTINCT phoneme) FROM user_phoneme_stats WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        conn.close()
    except Exception:
        stats.setdefault("total_evaluations", 0)
        stats.setdefault("best_score", 0)
        stats.setdefault("words_learned", 0)
        stats.setdefault("words_mastered", 0)
        stats.setdefault("phonemes_practiced", 0)
    
    # Compute streak
    try:
        conn = _sql3.connect(learning.db_path)
        rows = conn.execute(
            "SELECT DATE(evaluated_at, 'unixepoch', 'localtime') as date FROM user_evaluations WHERE user_id = ? GROUP BY date ORDER BY date DESC",
            (user_id,)
        ).fetchall()
        conn.close()
        streak = 0
        if rows:
            from datetime import date, timedelta
            today = date.today()
            for i, r in enumerate(rows):
                d = date.fromisoformat(r[0])
                expected = today - timedelta(days=i)
                if d == expected:
                    streak += 1
                else:
                    break
        stats["streak"] = streak
    except Exception:
        stats["streak"] = 0
    
    # Compute improvement
    try:
        conn = _sql3.connect(learning.db_path)
        early_row = conn.execute(
            "SELECT AVG(overall_score) FROM (SELECT overall_score FROM user_evaluations WHERE user_id = ? ORDER BY evaluated_at ASC LIMIT 5)",
            (user_id,)
        ).fetchone()
        recent_row = conn.execute(
            "SELECT AVG(overall_score) FROM (SELECT overall_score FROM user_evaluations WHERE user_id = ? ORDER BY evaluated_at DESC LIMIT 5)",
            (user_id,)
        ).fetchone()
        conn.close()
        early_avg = early_row[0] if early_row and early_row[0] else 0
        recent_avg = recent_row[0] if recent_row and recent_row[0] else 0
        stats["improvement"] = round(recent_avg - early_avg, 1)
    except Exception:
        stats["improvement"] = 0
    
    # Evaluate each achievement
    unlocked = []
    locked = []
    for ach in ACHIEVEMENTS:
        condition = ach["condition"]
        # Simple expression evaluation
        try:
            result = eval(condition, {"__builtins__": {}}, stats)
        except Exception:
            result = False
        
        entry = {
            "id": ach["id"],
            "name": ach["name"],
            "icon": ach["icon"],
            "desc": ach["desc"],
            "unlocked": bool(result),
        }
        if result:
            unlocked.append(entry)
        else:
            locked.append(entry)
    
    return {
        "unlocked": unlocked,
        "locked": locked,
        "stats": stats,
        "total_unlocked": len(unlocked),
        "total_achievements": len(ACHIEVEMENTS),
    }


# ============================================================
# 全局实例（单例模式）
# ============================================================

_metacognition: Optional[MetacognitionEngine] = None


def get_metacognition() -> MetacognitionEngine:
    """获取全局元认知引擎实例（单例）

    Returns:
        MetacognitionEngine: 元认知引擎实例
    """
    global _metacognition
    if _metacognition is None:
        _metacognition = MetacognitionEngine()
    return _metacognition
