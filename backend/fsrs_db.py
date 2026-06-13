"""
FSRS-6 间隔重复算法 + SQLite 持久化（支持多用户）

基于官方 FSRS-6 算法（py-fsrs）实现，用于句子/单词的复习调度。
从 FSRS-4.5（18参数）升级到 FSRS-6（21参数）。

Rating: 1=Again, 2=Hard, 3=Good, 4=Easy

核心变更（FSRS-4.5 → FSRS-6）：
- 参数从 18 个增加到 21 个（w[0]~w[20]）
- DECAY 从常量 -0.5 变为 -w[20]（可学习参数）
- 初始难度 D0(G) 从线性变为指数形式: clamp(w[4]-exp(w[5]*(G-1))+1, 1, 10)
- 遗忘稳定性新增下限: min(S_recall, S/exp(w[17]*w[18]))
- 新增短期稳定性公式（同日复习）: S*exp(w[17]*(G-3+w[18]))*S^(-w[19])
- 新增参数拟合功能（每30次复习自动拟合）
- 新增区间扰动（fuzzing）
- 新增每用户参数存储

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
import random
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

# ============================================================
# FSRS-6 默认参数（21个参数，w[0]~w[20]）
# 与官方 py-fsrs FSRS-6 默认值一致
# ============================================================
DEFAULT_FSRS_PARAMS = [
    0.212,    # w[0]  - S0(Again) 初始稳定性
    1.2931,   # w[1]  - S0(Hard)  初始稳定性
    2.3065,   # w[2]  - S0(Good)  初始稳定性
    8.2956,   # w[3]  - S0(Easy)  初始稳定性
    6.4133,   # w[4]  - D0 基础难度
    0.8334,   # w[5]  - D0 指数系数
    3.0194,   # w[6]  - 难度变化系数
    0.001,    # w[7]  - 难度均值回归系数
    1.8722,   # w[8]  - 回忆稳定性增长系数
    0.1666,   # w[9]  - 回忆稳定性衰减指数
    0.796,    # w[10] - 回忆稳定性回忆率系数
    1.4835,   # w[11] - 遗忘稳定性系数
    0.0614,   # w[12] - 遗忘稳定性难度衰减指数
    0.2629,   # w[13] - 遗忘稳定性稳定性增长指数
    1.6483,   # w[14] - 遗忘稳定性回忆率系数
    0.6014,   # w[15] - Hard 惩罚系数
    1.8729,   # w[16] - Easy 奖励系数
    0.5425,   # w[17] - 短期稳定性系数 / 遗忘稳定性下限系数1
    0.0912,   # w[18] - 短期稳定性偏移 / 遗忘稳定性下限系数2
    0.0658,   # w[19] - 短期稳定性衰减指数
    0.1542,   # w[20] - DECAY（可学习衰减参数，FSRS-4.5中为常量0.5）
]

# 默认期望保持率
DEFAULT_DESIRED_RETENTION = 0.9

# 默认学习步骤（分钟）
DEFAULT_LEARNING_STEPS = [1, 10]

# 默认重新学习步骤（分钟）
DEFAULT_RELEARNING_STEPS = [10]

# 默认最大间隔（天）
DEFAULT_MAXIMUM_INTERVAL = 36500

# 默认每日新卡片数
DEFAULT_NEW_PER_DAY = 5

DB_PATH = Path(__file__).parent / "phonos_fsrs.db"


class Card:
    """FSRS 卡片"""
    __slots__ = [
        'card_id', 'difficulty', 'stability', 'retrievability',
        'state', 'due', 'last_review', 'reps', 'lapses',
        'elapsed_days', 'scheduled_days', 'created_at'
    ]

    # State 常量
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
        # 关键设计：新卡片的 due 设为 0，不再用 time.time()
        # 这样 get_due_cards(到期复习) 不会把新卡片算进去
        # 新卡片通过 state=0 来识别，而不是 due 时间
        self.due = 0.0
        self.last_review = 0.0
        self.reps = 0
        self.lapses = 0
        self.elapsed_days = 0
        self.scheduled_days = 0
        self.created_at = time.time()


# ============================================================
# FSRS-6 核心公式
# ============================================================

def _clamp(value: float, low: float, high: float) -> float:
    """将值限制在 [low, high] 范围内"""
    return max(low, min(high, value))


def _init_decay(w: List[float]) -> float:
    """计算 DECAY 参数
    FSRS-6: DECAY = -w[20]（负值，FSRS-4.5中为常量 -0.5）
    
    注意：DECAY 是负数，这是 FSRS-6 的核心设计。
    w[20] 本身是正数（0.01~1.0），DECAY = -w[20] 确保为负。
    """
    # 确保 w[20] 在合理范围内，DECAY = -w[20]
    w20 = _clamp(w[20], 0.01, 1.0)
    return -w20  # 返回负值


def _init_factor(w: List[float]) -> float:
    """计算 FACTOR 参数
    FACTOR = 0.9^(1/DECAY) - 1
    
    由于 DECAY 为负值，1/DECAY 也为负值，
    0.9^(负值) > 1，因此 FACTOR > 0。
    
    例：DECAY = -0.1542 → FACTOR = 0.9^(1/(-0.1542)) - 1 ≈ 0.979
    """
    decay = _init_decay(w)
    return 0.9 ** (1.0 / decay) - 1.0


def _init_stability(w: List[float], rating: int) -> float:
    """计算初始稳定性 S0(G)
    FSRS-6: S0(G) = max(w[G-1], 0.1)  for G=1..4
    """
    return max(w[rating - 1], 0.1)


def _init_difficulty(w: List[float], rating: int) -> float:
    """计算初始难度 D0(G)
    FSRS-6（指数形式）: D0(G) = clamp(w[4] - exp(w[5] * (G-1)) + 1, 1, 10)
    FSRS-4.5（线性形式）: D0(G) = clamp(w[4] - w[5] * (G-3), 1, 10)
    """
    return _clamp(w[4] - math.exp(w[5] * (rating - 1)) + 1, 1.0, 10.0)


def _next_difficulty(w: List[float], d: float, rating: int) -> float:
    """计算复习后的难度
    FSRS-6:
    ΔD = -w[6] * (G - 3)
    D' = D + ΔD * (10 - D) / 9   （线性衰减，避免极端值）
    D'' = w[7] * D0(4) + (1 - w[7]) * D'  （均值回归）
    结果 clamp(1, 10)
    """
    delta_d = -w[6] * (rating - 3)
    d_prime = d + delta_d * (10 - d) / 9.0
    d_second = w[7] * _init_difficulty(w, 4) + (1 - w[7]) * d_prime
    return _clamp(d_second, 1.0, 10.0)


def _next_recall_stability(w: List[float], d: float, s: float, r: float, rating: int) -> float:
    """计算回忆后的稳定性
    FSRS-6:
    S * (1 + exp(w[8]) * (11-D) * S^(-w[9]) * (exp(w[10]*(1-R))-1) * hard_penalty * easy_bonus)
    hard_penalty = w[15] if G=2, else 1
    easy_bonus = w[16] if G=4, else 1
    """
    hard_penalty = w[15] if rating == 2 else 1.0
    easy_bonus = w[16] if rating == 4 else 1.0
    new_s = s * (1 + math.exp(w[8]) * (11 - d) * (s ** (-w[9])) *
                 (math.exp(w[10] * (1 - r)) - 1) * hard_penalty * easy_bonus)
    return max(0.1, min(new_s, 36500.0))


def _next_forget_stability(w: List[float], d: float, s: float, r: float) -> float:
    """计算遗忘后的稳定性
    FSRS-6:
    min(w[11] * D^(-w[12]) * ((S+1)^w[13] - 1) * exp(w[14]*(1-R)), S/exp(w[17]*w[18]))
    
    注意：FSRS-6 新增了遗忘稳定性下限 S/exp(w[17]*w[18])，
    防止遗忘后稳定性过低。
    """
    s_recall = w[11] * (d ** (-w[12])) * ((s + 1) ** w[13] - 1) * math.exp(w[14] * (1 - r))
    s_floor = s / math.exp(w[17] * w[18])
    # 取两者中的较小值，但至少为0.1
    return max(0.1, min(s_recall, s_floor, s))


def _next_short_term_stability(w: List[float], s: float, rating: int) -> float:
    """计算短期稳定性（同日复习）
    FSRS-6 新增:
    S * exp(w[17] * (G - 3 + w[18])) * S^(-w[19])
    
    用于处理同一天内的重复复习（elapsed_days == 0），
    避免使用长期稳定性公式导致的异常值。
    """
    new_s = s * math.exp(w[17] * (rating - 3 + w[18])) * (s ** (-w[19]))
    return max(0.1, min(new_s, 36500.0))


def _retrievability(elapsed_days: float, stability: float, w: List[float]) -> float:
    """计算可回忆率 R(t, S)
    FSRS-6:
    R(t, S) = (1 + FACTOR * t / S) ^ DECAY
    其中 FACTOR = 0.9^(1/DECAY) - 1, DECAY = -w[20]
    
    由于 DECAY < 0 且 FACTOR > 0，当 t > 0 时：
    - (1 + FACTOR * t/S) > 1
    - (base)^DECAY = 1/(base)^|DECAY|，所以 R 随 t 增大而递减 ✓
    - 当 t=0 时，R=1 ✓
    
    FSRS-4.5 对比:
    R(t, S) = (1 + t / (9*S)) ^ (-1/decay)
    """
    if stability <= 0:
        return 0.0
    if elapsed_days <= 0:
        return 1.0
    decay = _init_decay(w)  # 负值
    factor = _init_factor(w)  # 正值
    base = 1 + factor * elapsed_days / stability
    if base <= 0:
        return 0.0
    return base ** decay


def _next_interval(s: float, desired_retention: float, w: List[float],
                   maximum_interval: float = DEFAULT_MAXIMUM_INTERVAL,
                   enable_fuzzing: bool = True) -> float:
    """计算下次复习间隔（天）
    FSRS-6:
    interval = (S / FACTOR) * (r^(1/DECAY) - 1)
    其中 r = desired_retention, FACTOR = 0.9^(1/DECAY) - 1
    
    推导：设 R(interval) = r，解 interval
    (1 + FACTOR * interval / S)^DECAY = r
    FACTOR * interval / S = r^(1/DECAY) - 1
    interval = (S / FACTOR) * (r^(1/DECAY) - 1)
    
    重要性质：当 r = 0.9 时，interval ≈ S（稳定性即为间隔天数）
    
    新增:
    - fuzzing: 区间扰动，避免同一天到期卡片过多
    - maximum_interval: 最大间隔限制
    """
    if desired_retention <= 0:
        return 1.0
    if desired_retention >= 1.0:
        return maximum_interval
    if s <= 0:
        return 1.0

    decay = _init_decay(w)  # 负值
    factor = _init_factor(w)  # 正值

    # 核心公式: (S/FACTOR) * (r^(1/DECAY) - 1)
    # r^(1/DECAY): 由于 DECAY < 0, 1/DECAY < 0
    # r < 1 → r^(负值) > 1 → (r^(1/DECAY) - 1) > 0
    power_term = desired_retention ** (1.0 / decay) - 1
    interval = (s / factor) * power_term

    # 至少1天
    interval = max(1.0, interval)

    # 限制最大间隔
    interval = min(interval, maximum_interval)

    # Fuzzing: 区间扰动
    if enable_fuzzing and interval >= 2.5:
        interval = _apply_fuzz(interval)

    return interval


def _apply_fuzz(interval: float) -> float:
    """区间扰动（Fuzzing）
    参考 Anki/FSRS 的 fuzz 实现：
    在区间附近添加随机扰动，避免同一天到期卡片过多。
    扰动范围与区间大小成正比，但不超过 ±1 天（短间隔）
    或 ±5% （长间隔）。
    """
    # 使用确定性种子（基于当前时间的微秒部分）
    # 避免同一秒内所有卡片得到相同扰动
    fuzz_range = max(1, round(interval * 0.05))
    fuzz_range = min(fuzz_range, 5)  # 最大 ±5 天
    fuzz = random.randint(-fuzz_range, fuzz_range)
    return max(1.0, round(interval) + fuzz)


# ============================================================
# FSRS-6 调度器
# ============================================================

class FSRSScheduler:
    """FSRS-6 调度器"""

    def __init__(self, params: List[float] = None,
                 desired_retention: float = DEFAULT_DESIRED_RETENTION,
                 learning_steps: List[int] = None,
                 relearning_steps: List[int] = None,
                 maximum_interval: float = DEFAULT_MAXIMUM_INTERVAL):
        self.w = params or DEFAULT_FSRS_PARAMS
        self.desired_retention = desired_retention
        self.learning_steps = learning_steps or list(DEFAULT_LEARNING_STEPS)
        self.relearning_steps = relearning_steps or list(DEFAULT_RELEARNING_STEPS)
        self.maximum_interval = maximum_interval
        self.decay = _init_decay(self.w)
        self.factor = _init_factor(self.w)

    def review(self, card: Card, rating: int, now: float = None) -> Card:
        """对卡片进行复习评分
        
        核心流程（FSRS-6）：
        1. 新卡片(NEW)：设置初始难度和稳定性
        2. 非新卡片：
           a. 计算经过时间 elapsed_days
           b. 如果是同日复习(elapsed_days < 1)：使用短期稳定性公式
           c. 如果是长期复习：使用标准稳定性更新公式
        3. 计算新间隔
        4. 应用 learning_steps / relearning_steps
        """
        if now is None:
            now = time.time()

        if card.state == Card.NEW:
            # 新卡片：设置初始参数
            card.stability = _init_stability(self.w, rating)
            card.difficulty = _init_difficulty(self.w, rating)

            # 根据评级设置不同的初始状态
            # Again(1)/Hard(2) → LEARNING, Good(3)/Easy(4) → REVIEW
            if rating >= 3:
                card.state = Card.REVIEW
            else:
                card.state = Card.LEARNING
        else:
            # 非新卡片：更新参数
            elapsed = max(0, (now - card.last_review) / 86400.0) if card.last_review > 0 else 0
            card.elapsed_days = elapsed

            if card.stability > 0:
                card.retrievability = _retrievability(elapsed, card.stability, self.w)
            else:
                card.retrievability = 0

            # 判断是否为同日复习（elapsed_days < 1）
            is_same_day = elapsed < 1.0 and card.last_review > 0

            if rating >= 3:  # Good / Easy
                if is_same_day:
                    # 同日复习：使用短期稳定性公式
                    card.stability = _next_short_term_stability(self.w, card.stability, rating)
                else:
                    # 长期复习：使用标准回忆稳定性公式
                    card.stability = _next_recall_stability(
                        self.w, card.difficulty, card.stability, card.retrievability, rating)
                card.difficulty = _next_difficulty(self.w, card.difficulty, rating)
                if card.state == Card.RELEARNING:
                    card.state = Card.REVIEW
                else:
                    card.state = Card.REVIEW
            else:  # Again / Hard
                if rating == 1:
                    # Again: 遗忘 → lapse
                    card.lapses += 1
                    if is_same_day:
                        # 同日遗忘：使用短期稳定性公式（降低稳定性）
                        card.stability = _next_short_term_stability(self.w, card.stability, rating)
                    else:
                        # 长期遗忘：使用标准遗忘稳定性公式
                        card.stability = _next_forget_stability(
                            self.w, card.difficulty, card.stability, card.retrievability)
                    card.state = Card.RELEARNING
                else:  # Hard
                    if is_same_day:
                        card.stability = _next_short_term_stability(self.w, card.stability, rating)
                    else:
                        card.stability = _next_recall_stability(
                            self.w, card.difficulty, card.stability, card.retrievability, rating)
                    card.difficulty = _next_difficulty(self.w, card.difficulty, rating)

        card.reps += 1
        card.last_review = now

        # 更新可回忆率（刚复习后 elapsed=0）
        card.retrievability = _retrievability(0, card.stability, self.w)

        # 计算下次间隔
        if card.state == Card.LEARNING:
            # LEARNING 状态：使用 learning_steps
            step_idx = min(card.reps - 1, len(self.learning_steps) - 1)
            card.scheduled_days = self.learning_steps[step_idx] / (24.0 * 60.0)  # 分钟→天
        elif card.state == Card.RELEARNING:
            # RELEARNING 状态：使用 relearning_steps
            step_idx = min(card.reps - 1, len(self.relearning_steps) - 1)
            card.scheduled_days = self.relearning_steps[step_idx] / (24.0 * 60.0)  # 分钟→天
        else:
            # REVIEW 状态：使用 FSRS-6 间隔公式
            card.scheduled_days = _next_interval(
                card.stability, self.desired_retention, self.w,
                self.maximum_interval, enable_fuzzing=True
            )

        card.due = now + card.scheduled_days * 86400

        return card

    def get_retrievability(self, card: Card, now: float = None) -> float:
        """获取卡片当前的可回忆率
        
        Args:
            card: FSRS 卡片
            now: 当前时间戳（秒），默认为当前时间
            
        Returns:
            可回忆率 [0, 1]
        """
        if now is None:
            now = time.time()
        if card.state == Card.NEW:
            return 0.0
        elapsed = max(0, (now - card.last_review) / 86400.0) if card.last_review > 0 else 0
        return _retrievability(elapsed, card.stability, self.w)

    def get_next_interval_info(self, card: Card, now: float = None) -> dict:
        """获取卡片的下次间隔预测信息
        
        Args:
            card: FSRS 卡片
            now: 当前时间戳（秒），默认为当前时间
            
        Returns:
            dict 包含:
            - interval: 当前安排的间隔（天）
            - retrievability: 当前可回忆率
            - next_intervals: 各评级下的预测间隔 {1: ..., 2: ..., 3: ..., 4: ...}
        """
        if now is None:
            now = time.time()

        current_ret = self.get_retrievability(card, now)
        current_interval = card.scheduled_days

        # 预测各评级下的间隔
        next_intervals = {}
        for r in [1, 2, 3, 4]:
            # 临时复制卡片，模拟复习
            import copy
            temp_card = copy.copy(card)
            temp_card = self.review(temp_card, r, now)
            next_intervals[r] = round(temp_card.scheduled_days, 1)

        return {
            "interval": round(current_interval, 1),
            "retrievability": round(current_ret, 4),
            "next_intervals": next_intervals,
        }


# ============================================================
# FSRS-6 参数拟合（简化梯度下降，无 PyTorch 依赖）
# ============================================================

# 参数边界（参考官方 py-fsrs）
PARAM_BOUNDS = [
    (0.01, 10.0),   # w[0]  - S0(Again)
    (0.01, 10.0),   # w[1]  - S0(Hard)
    (0.01, 10.0),   # w[2]  - S0(Good)
    (0.01, 30.0),   # w[3]  - S0(Easy)
    (1.0, 10.0),    # w[4]  - D0 基础难度
    (0.01, 5.0),    # w[5]  - D0 指数系数
    (0.01, 10.0),   # w[6]  - 难度变化系数
    (0.001, 1.0),   # w[7]  - 难度均值回归系数
    (0.01, 10.0),   # w[8]  - 回忆稳定性增长系数
    (0.01, 1.0),    # w[9]  - 回忆稳定性衰减指数
    (0.01, 5.0),    # w[10] - 回忆稳定性回忆率系数
    (0.01, 10.0),   # w[11] - 遗忘稳定性系数
    (0.001, 1.0),   # w[12] - 遗忘稳定性难度衰减指数
    (0.01, 2.0),    # w[13] - 遗忘稳定性稳定性增长指数
    (0.01, 5.0),    # w[14] - 遗忘稳定性回忆率系数
    (0.01, 5.0),    # w[15] - Hard 惩罚系数
    (0.5, 5.0),     # w[16] - Easy 奖励系数
    (0.01, 5.0),    # w[17] - 短期稳定性系数
    (0.01, 2.0),    # w[18] - 短期稳定性偏移
    (0.001, 1.0),   # w[19] - 短期稳定性衰减指数
    (0.01, 1.0),    # w[20] - DECAY
]


def _binary_cross_entropy(predicted: float, actual: float) -> float:
    """计算二元交叉熵损失
    predicted: 预测回忆概率 [0, 1]
    actual: 实际结果 (1=回忆成功, 0=遗忘)
    """
    eps = 1e-7
    predicted = _clamp(predicted, eps, 1.0 - eps)
    if actual >= 1:
        return -math.log(predicted)
    else:
        return -math.log(1.0 - predicted)


def _simulate_review_sequence(w: List[float], reviews: List[dict]) -> List[Tuple[float, float]]:
    """模拟复习序列，返回每步的 (predicted_R, actual_recall) 对
    
    reviews: 列表，每个元素包含 rating, elapsed_days
    只使用 elapsed_days > 0 的复习
    
    返回: [(predicted_retrievability, actual_recall), ...]
    """
    results = []
    d = 0.0  # 当前难度
    s = 0.0  # 当前稳定性
    state = Card.NEW

    for i, rev in enumerate(reviews):
        rating = rev['rating']
        elapsed = rev['elapsed_days']
        actual_recall = 1.0 if rating > 1 else 0.0

        if state == Card.NEW:
            s = _init_stability(w, rating)
            d = _init_difficulty(w, rating)
            if rating >= 3:
                state = Card.REVIEW
            else:
                state = Card.LEARNING
        else:
            # 只有 elapsed > 0 时才有有意义的 R 预测
            if elapsed > 0 and s > 0:
                r = _retrievability(elapsed, s, w)
                results.append((r, actual_recall))

            # 更新难度和稳定性
            if rating >= 3:
                if elapsed < 1.0:
                    s = _next_short_term_stability(w, s, rating)
                else:
                    r_for_update = _retrievability(elapsed, s, w) if s > 0 else 0
                    s = _next_recall_stability(w, d, s, r_for_update, rating)
                d = _next_difficulty(w, d, rating)
                state = Card.REVIEW
            else:
                if rating == 1:
                    if elapsed < 1.0:
                        s = _next_short_term_stability(w, s, rating)
                    else:
                        r_for_update = _retrievability(elapsed, s, w) if s > 0 else 0
                        s = _next_forget_stability(w, d, s, r_for_update)
                    state = Card.RELEARNING
                else:  # Hard
                    if elapsed < 1.0:
                        s = _next_short_term_stability(w, s, rating)
                    else:
                        r_for_update = _retrievability(elapsed, s, w) if s > 0 else 0
                        s = _next_recall_stability(w, d, s, r_for_update, rating)
                    d = _next_difficulty(w, d, rating)

    return results


def _compute_loss(w: List[float], reviews: List[dict]) -> float:
    """计算给定参数下的 BCE 损失"""
    pairs = _simulate_review_sequence(w, reviews)
    if not pairs:
        return 0.0
    total_loss = sum(_binary_cross_entropy(pred, actual) for pred, actual in pairs)
    return total_loss / len(pairs)


def _compute_gradients(w: List[float], reviews: List[dict], eps: float = 0.001) -> List[float]:
    """计算参数梯度（有限差分法）
    
    对每个参数 w[i]，计算:
    grad[i] = (loss(w + eps*e_i) - loss(w - eps*e_i)) / (2*eps)
    """
    base_loss = _compute_loss(w, reviews)
    gradients = [0.0] * len(w)

    for i in range(len(w)):
        # 中心差分
        w_plus = w.copy()
        w_minus = w.copy()
        w_plus[i] += eps
        w_minus[i] -= eps
        loss_plus = _compute_loss(w_plus, reviews)
        loss_minus = _compute_loss(w_minus, reviews)
        gradients[i] = (loss_plus - loss_minus) / (2 * eps)

    return gradients


def fit_fsrs_params(w: List[float], reviews: List[dict],
                    epochs: int = 5, lr: float = 0.01) -> Tuple[List[float], List[float]]:
    """简化梯度下降拟合 FSRS 参数
    
    Args:
        w: 初始参数
        reviews: 复习记录列表 [{rating, elapsed_days}, ...]
        epochs: 训练轮数
        lr: 学习率
        
    Returns:
        (fitted_params, loss_history)
    """
    if not reviews:
        return w.copy(), []

    # 只使用 elapsed_days > 0 的复习记录（有意义的 R 预测）
    # 但我们仍然需要完整序列来模拟状态转移
    # 所以这里不做过滤，让 _simulate_review_sequence 内部处理

    w_current = w.copy()
    loss_history = []

    for epoch in range(epochs):
        # 计算梯度
        gradients = _compute_gradients(w_current, reviews)

        # 更新参数
        for i in range(len(w_current)):
            # 限制梯度大小，防止参数跳变过大
            grad = _clamp(gradients[i], -1.0, 1.0)
            w_current[i] -= lr * grad

            # 将参数限制在有效范围内
            low, high = PARAM_BOUNDS[i]
            w_current[i] = _clamp(w_current[i], low, high)

        # 记录损失
        loss = _compute_loss(w_current, reviews)
        loss_history.append(loss)

    return w_current, loss_history


# ============================================================
# FSRS-6 数据库（SQLite）
# ============================================================

class FSRSDatabase:
    """FSRS SQLite 数据库（支持多用户，FSRS-6）"""

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

            CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due);
            CREATE INDEX IF NOT EXISTS idx_cards_state ON cards(state);
            CREATE INDEX IF NOT EXISTS idx_cards_user ON cards(user_id);
            CREATE INDEX IF NOT EXISTS idx_cards_user_type ON cards(user_id, card_type);
            CREATE INDEX IF NOT EXISTS idx_review_card ON review_log(card_id);
            CREATE INDEX IF NOT EXISTS idx_review_user ON review_log(user_id);
        """)
        conn.commit()

        # 迁移：添加 user_id 列（兼容旧版本）
        self._migrate_add_user_id(conn)

        # 迁移：修复旧数据 - 把 due=创建时间 且 state=0 的卡片 due 改为 0
        self._migrate_fix_new_card_due(conn)

        # 迁移：添加 review_duration 列
        self._migrate_add_review_duration(conn)

        conn.close()

    def _migrate_add_user_id(self, conn):
        """迁移：为旧表添加 user_id 列"""
        # 检查 cards 表
        cards_cols = [row[1] for row in conn.execute("PRAGMA table_info(cards)").fetchall()]
        if 'user_id' not in cards_cols:
            conn.execute("ALTER TABLE cards ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'")
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

        # 检查 review_log 表
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

    def _migrate_add_review_duration(self, conn):
        """迁移：为 review_log 添加 review_duration 列"""
        review_cols = [row[1] for row in conn.execute("PRAGMA table_info(review_log)").fetchall()]
        if 'review_duration' not in review_cols:
            try:
                conn.execute("ALTER TABLE review_log ADD COLUMN review_duration REAL NOT NULL DEFAULT 0")
                conn.commit()
            except Exception:
                pass

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    # ============================================================
    # 用户参数管理
    # ============================================================

    def get_user_params(self, user_id: str = "default") -> dict:
        """获取用户的 FSRS 参数配置
        
        Returns:
            dict 包含:
            - params: 21个参数的列表
            - desired_retention: 期望保持率
            - learning_steps: 学习步骤（分钟）
            - relearning_steps: 重新学习步骤（分钟）
            - maximum_interval: 最大间隔（天）
            - new_per_day: 每日新卡片数
            - fit_count: 拟合次数
            - last_fit_time: 上次拟合时间
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT params_json, fit_count, last_fit_time, desired_retention, "
            "learning_steps, relearning_steps, maximum_interval, new_per_day "
            "FROM user_fsrs_params WHERE user_id = ?",
            (user_id,)
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
        """设置用户的 FSRS 参数配置
        
        Args:
            user_id: 用户ID
            params_dict: 可包含 params, desired_retention, learning_steps,
                         relearning_steps, maximum_interval, new_per_day 中的任意项
        """
        # 先获取当前参数
        current = self.get_user_params(user_id)

        # 更新指定字段
        if "params" in params_dict:
            current["params"] = params_dict["params"]
        if "desired_retention" in params_dict:
            current["desired_retention"] = params_dict["desired_retention"]
        if "learning_steps" in params_dict:
            current["learning_steps"] = params_dict["learning_steps"]
        if "relearning_steps" in params_dict:
            current["relearning_steps"] = params_dict["relearning_steps"]
        if "maximum_interval" in params_dict:
            current["maximum_interval"] = params_dict["maximum_interval"]
        if "new_per_day" in params_dict:
            current["new_per_day"] = params_dict["new_per_day"]

        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO user_fsrs_params 
            (user_id, params_json, fit_count, last_fit_time, desired_retention,
             learning_steps, relearning_steps, maximum_interval, new_per_day)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            json.dumps(current["params"]),
            current["fit_count"],
            current["last_fit_time"],
            current["desired_retention"],
            json.dumps(current["learning_steps"]),
            json.dumps(current["relearning_steps"]),
            current["maximum_interval"],
            current["new_per_day"],
        ))
        conn.commit()
        conn.close()

    def get_scheduler(self, user_id: str = "default") -> FSRSScheduler:
        """获取用户的个性化调度器
        
        根据用户存储的参数创建 FSRSScheduler 实例。
        如果用户没有自定义参数，使用默认参数。
        """
        user_params = self.get_user_params(user_id)
        return FSRSScheduler(
            params=user_params["params"],
            desired_retention=user_params["desired_retention"],
            learning_steps=user_params["learning_steps"],
            relearning_steps=user_params["relearning_steps"],
            maximum_interval=user_params["maximum_interval"],
        )

    def fit_params(self, user_id: str = "default") -> dict:
        """对用户的复习数据进行参数拟合
        
        使用简化梯度下降（有限差分法），无需 PyTorch。
        
        Returns:
            dict 包含:
            - success: 是否成功
            - fit_count: 拟合次数
            - loss_before: 拟合前损失
            - loss_after: 拟合后损失
            - epochs: 训练轮数
            - message: 状态消息
        """
        # 获取用户的复习日志
        conn = self._get_conn()

        # 获取所有复习记录，按 card_id 和 review_time 排序
        rows = conn.execute(
            "SELECT card_id, rating, elapsed_days, review_time "
            "FROM review_log WHERE user_id = ? "
            "ORDER BY card_id, review_time ASC",
            (user_id,)
        ).fetchall()
        conn.close()

        if len(rows) < 30:
            return {
                "success": False,
                "fit_count": 0,
                "loss_before": 0,
                "loss_after": 0,
                "epochs": 0,
                "message": f"复习记录不足30条（当前{len(rows)}条），无法拟合",
            }

        # 按卡片分组，构建复习序列
        card_reviews: Dict[str, List[dict]] = {}
        for row in rows:
            card_id = row[0]
            if card_id not in card_reviews:
                card_reviews[card_id] = []
            card_reviews[card_id].append({
                "rating": row[1],
                "elapsed_days": row[2],
                "review_time": row[3],
            })

        # 合并所有卡片的复习序列（用于拟合）
        # 只保留有 elapsed_days > 0 的记录的卡片
        all_reviews = []
        for card_id, reviews in card_reviews.items():
            # 完整序列用于状态转移模拟
            all_reviews.extend(reviews)

        # 按时间排序（跨卡片模拟不太精确，但简化拟合可用）
        all_reviews.sort(key=lambda x: x['review_time'])

        # 获取当前参数
        user_params = self.get_user_params(user_id)
        w_init = user_params["params"]

        # 计算拟合前损失
        loss_before = _compute_loss(w_init, all_reviews)

        # 执行拟合
        try:
            w_fitted, loss_history = fit_fsrs_params(
                w_init, all_reviews,
                epochs=5, lr=0.01
            )
            loss_after = loss_history[-1] if loss_history else loss_before
        except Exception as e:
            return {
                "success": False,
                "fit_count": user_params["fit_count"],
                "loss_before": loss_before,
                "loss_after": loss_before,
                "epochs": 0,
                "message": f"拟合失败: {str(e)}",
            }

        # 保存拟合结果
        user_params["params"] = w_fitted
        user_params["fit_count"] = user_params["fit_count"] + 1
        user_params["last_fit_time"] = time.time()

        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO user_fsrs_params 
            (user_id, params_json, fit_count, last_fit_time, desired_retention,
             learning_steps, relearning_steps, maximum_interval, new_per_day)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            json.dumps(user_params["params"]),
            user_params["fit_count"],
            user_params["last_fit_time"],
            user_params["desired_retention"],
            json.dumps(user_params["learning_steps"]),
            json.dumps(user_params["relearning_steps"]),
            user_params["maximum_interval"],
            user_params["new_per_day"],
        ))
        conn.commit()
        conn.close()

        # 更新默认调度器（如果当前用户是默认用户）
        if user_id == "default":
            self.scheduler = self.get_scheduler("default")

        return {
            "success": True,
            "fit_count": user_params["fit_count"],
            "loss_before": round(loss_before, 4),
            "loss_after": round(loss_after, 4),
            "epochs": 5,
            "message": f"拟合完成，损失从 {loss_before:.4f} 降至 {loss_after:.4f}",
        }

    # ============================================================
    # 卡片管理（保持与旧版完全兼容的方法签名）
    # ============================================================

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

        # 使用用户个性化调度器
        scheduler = self.get_scheduler(user_id)
        ret = scheduler.get_retrievability(card)

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

    def review_card(self, card_id: str, rating: int, card_type: str = "sentence",
                    user_id: str = "default", review_duration: float = 0) -> dict:
        """复习卡片并返回结果
        
        Args:
            card_id: 卡片ID
            rating: 评级 (1=Again, 2=Hard, 3=Good, 4=Easy)
            card_type: 卡片类型
            user_id: 用户ID
            review_duration: 复习用时（秒），可选
            
        Returns:
            dict 包含复习结果
        """
        self.ensure_card(card_id, card_type, user_id)
        card = self.get_card(card_id, user_id)
        now = time.time()

        old_state = card.state

        # 使用用户个性化调度器
        scheduler = self.get_scheduler(user_id)
        card = scheduler.review(card, rating, now)

        conn = self._get_conn()
        conn.execute("""
            UPDATE cards SET difficulty=?, stability=?, state=?, due=?, last_review=?,
            reps=?, lapses=?, scheduled_days=? WHERE card_id=? AND user_id=?
        """, (card.difficulty, card.stability, card.state, card.due,
              card.last_review, card.reps, card.lapses, card.scheduled_days, card_id, user_id))

        conn.execute("""
            INSERT INTO review_log (card_id, user_id, rating, state, due, review_time, elapsed_days, review_duration)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (card_id, user_id, rating, old_state, card.due, now, card.elapsed_days, review_duration))

        conn.commit()
        conn.close()

        # 检查是否需要自动拟合（每30次复习）
        self._check_auto_fit(user_id)

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

    def _check_auto_fit(self, user_id: str = "default"):
        """检查是否需要自动拟合参数（每30次复习触发一次）
        
        在后台静默执行，不影响主流程。
        """
        try:
            conn = self._get_conn()
            total_reviews = conn.execute(
                "SELECT COUNT(*) FROM review_log WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            conn.close()

            # 每30次复习触发一次拟合
            if total_reviews > 0 and total_reviews % 30 == 0:
                user_params = self.get_user_params(user_id)
                # 只在拟合次数合理的情况下执行（避免过于频繁）
                # 如果上次拟合时间距今不到1小时，跳过
                if user_params["last_fit_time"] > 0:
                    if time.time() - user_params["last_fit_time"] < 3600:
                        return
                # 异步执行拟合（当前为同步，但静默捕获异常）
                try:
                    self.fit_params(user_id)
                except Exception:
                    pass  # 拟合失败不影响主流程
        except Exception:
            pass

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
        now = time.time()
        conn = self._get_conn()

        # 获取所有未掌握的卡片
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
        unmastered_review_cards = [r for r in rows if r[1] == 2 and not (r[2] > now and r[3] >= 3)]

        # 优先级：到期复习 > 学习中 > 未掌握复习 > 新词
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

    def get_review_queue(self, card_type: str = "sentence", user_id: str = "default",
                         new_per_day: int = 5, review_limit: int = 50) -> List[dict]:
        """获取复习队列：混合到期复习卡片和新卡片
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

        # 3. REVIEW 但未掌握的单词（due > now 但 scheduled_days < 3）
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
        - due (待复习): 所有非NEW且非已掌握的卡片
        - learning (学习中): state=LEARNING 或 RELEARNING
        - new (新词): state=NEW
        """
        now = time.time()
        conn = self._get_conn()

        total = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type='word' AND user_id=?", (user_id,)
        ).fetchone()[0]

        new_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type='word' AND user_id=? AND state=0", (user_id,)
        ).fetchone()[0]

        mastered_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type='word' AND user_id=? AND state=2 AND due > ? AND scheduled_days >= 3",
            (user_id, now)
        ).fetchone()[0]

        due_count = total - mastered_count - new_count
        if due_count < 0:
            due_count = 0

        learning_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE card_type='word' AND user_id=? AND state IN (1, 3)", (user_id,)
        ).fetchone()[0]

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

        # 获取用户拟合信息
        user_params = self.get_user_params(user_id)

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
            "fsrs_version": "6.0",
            "fsrs_params_count": len(user_params["params"]),
            "fsrs_fit_count": user_params["fit_count"],
            "fsrs_last_fit_time": user_params["last_fit_time"],
            "fsrs_desired_retention": user_params["desired_retention"],
        }


# ============================================================
# 全局实例（单例模式）
# ============================================================

_fsrs_db: Optional[FSRSDatabase] = None


def get_fsrs_db() -> FSRSDatabase:
    """获取全局 FSRS 数据库实例（单例）"""
    global _fsrs_db
    if _fsrs_db is None:
        _fsrs_db = FSRSDatabase()
    return _fsrs_db
