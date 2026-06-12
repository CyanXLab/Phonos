"""
评分算法 - 发音评测核心

基于音素对比的发音评分系统，包含：
1. 音素对齐（基于动态规划的序列对齐）
2. 发音准确度评分
3. 流利度评分
4. 完整度评分
5. 综合评分
6. 错误诊断和改进建议
"""

import math
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field

from .phoneme_data import SIMILARITY_FUNC, PHONEME_TIPS


@dataclass
class PhonemeError:
    """单个音素错误"""
    expected: str           # 期望音素
    actual: Optional[str]   # 实际音素 (None=漏读)
    error_type: str         # substitution / deletion / insertion
    position: int           # 在期望序列中的位置
    similarity: float       # 相似度 (0-1)
    word_index: int = -1    # 所属单词索引


@dataclass
class WordResult:
    """单词级别结果"""
    word: str
    expected_phonemes: List[str]
    actual_phonemes: List[str]
    errors: List[PhonemeError]
    accuracy: float  # 0-100


@dataclass
class EvaluationResult:
    """完整评测结果"""
    # 评分
    pronunciation_score: float    # 发音准确度 0-100
    fluency_score: float          # 流利度 0-100
    completeness_score: float     # 完整度 0-100
    overall_score: float          # 综合评分 0-100

    # 详细信息
    errors: List[PhonemeError]
    word_results: List[WordResult]

    # 原始数据
    expected_phonemes: List[str]
    actual_phonemes: List[str]

    # 时间信息
    total_duration: float = 0.0
    pause_count: int = 0
    pause_duration: float = 0.0
    speaking_rate: float = 0.0  # 每秒音素数


def align_phonemes(
    expected: List[str],
    actual: List[str],
    sub_cost_func=None,
    ins_cost: float = 1.0,
    del_cost: float = 1.0,
) -> Tuple[List[Tuple[Optional[str], Optional[str]]], float]:
    """
    使用动态规划进行音素序列对齐

    类似于序列比对算法，支持替换、插入、删除操作，
    并使用音素相似度来计算替换代价。

    参数:
        expected: 期望音素序列
        actual: 实际音素序列
        sub_cost_func: 替换代价函数 (p1, p2) -> float, 默认使用相似度
        ins_cost: 插入代价
        del_cost: 删除代价

    返回:
        (alignment, total_cost): 对齐结果和总代价
        alignment: [(expected_phoneme or None, actual_phoneme or None), ...]
    """
    if sub_cost_func is None:
        def sub_cost_func(p1, p2):
            return 1.0 - SIMILARITY_FUNC(p1, p2)

    m, n = len(expected), len(actual)

    # DP 表
    dp = [[0.0] * (n + 1) for _ in range(m + 1)]
    # 回溯表
    trace = [[0] * (n + 1) for _ in range(m + 1)]
    # 0=match/sub, 1=delete, 2=insert

    # 初始化
    for i in range(1, m + 1):
        dp[i][0] = dp[i - 1][0] + del_cost
        trace[i][0] = 1
    for j in range(1, n + 1):
        dp[0][j] = dp[0][j - 1] + ins_cost
        trace[0][j] = 2

    # 填表
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            sub = dp[i - 1][j - 1] + sub_cost_func(expected[i - 1], actual[j - 1])
            delete = dp[i - 1][j] + del_cost
            insert = dp[i][j - 1] + ins_cost

            if sub <= delete and sub <= insert:
                dp[i][j] = sub
                trace[i][j] = 0
            elif delete <= insert:
                dp[i][j] = delete
                trace[i][j] = 1
            else:
                dp[i][j] = insert
                trace[i][j] = 2

    # 回溯
    alignment = []
    i, j = m, n
    while i > 0 or j > 0:
        if i > 0 and j > 0 and trace[i][j] == 0:
            alignment.append((expected[i - 1], actual[j - 1]))
            i -= 1
            j -= 1
        elif i > 0 and trace[i][j] == 1:
            alignment.append((expected[i - 1], None))
            i -= 1
        else:
            alignment.append((None, actual[j - 1]))
            j -= 1

    alignment.reverse()
    return alignment, dp[m][n]


def analyze_errors(
    alignment: List[Tuple[Optional[str], Optional[str]]],
    expected_phonemes: List[str],
) -> List[PhonemeError]:
    """
    分析对齐结果，生成错误列表

    参数:
        alignment: 对齐结果
        expected_phonemes: 原始期望音素序列

    返回:
        错误列表
    """
    errors = []
    expected_idx = 0

    for exp, act in alignment:
        if exp is not None and act is not None:
            if exp != act:
                # 替换错误
                similarity = SIMILARITY_FUNC(exp, act)
                errors.append(PhonemeError(
                    expected=exp,
                    actual=act,
                    error_type="substitution",
                    position=expected_idx,
                    similarity=similarity,
                ))
            expected_idx += 1
        elif exp is not None and act is None:
            # 删除错误（漏读）
            errors.append(PhonemeError(
                expected=exp,
                actual=None,
                error_type="deletion",
                position=expected_idx,
                similarity=0.0,
            ))
            expected_idx += 1
        elif exp is None and act is not None:
            # 插入错误（多读）
            errors.append(PhonemeError(
                expected="",
                actual=act,
                error_type="insertion",
                position=expected_idx,
                similarity=0.0,
            ))

    return errors


def calculate_pronunciation_score(
    alignment: List[Tuple[Optional[str], Optional[str]]],
    errors: List[PhonemeError],
    expected: List[str],
) -> float:
    """
    计算发音准确度评分

    评分算法：
    1. 基于音素对齐结果
    2. 正确音素得分，替换按相似度部分得分
    3. 删除和插入扣分
    4. 使用加权评分，重要音素（如元音、关键辅音）权重更高

    参数:
        alignment: 对齐结果
        errors: 错误列表
        expected: 期望音素序列

    返回:
        发音准确度评分 (0-100)
    """
    if not expected:
        return 0.0

    total_score = 0.0
    total_weight = 0.0

    # 音素权重（元音权重更高，因为元音错误更影响理解）
    weight_map = {
        "vowel": 1.5,
        "consonant": 1.0,
    }

    def get_weight(phoneme: str) -> float:
        from .phoneme_data import PHONEME_GROUP
        group, _ = PHONEME_GROUP.get(phoneme, ("consonant", "other"))
        return weight_map.get(group, 1.0)

    for exp, act in alignment:
        if exp is None:
            # 插入错误 - 小扣分
            total_weight += 0.5
            total_score += 0.0
            continue

        w = get_weight(exp)
        total_weight += w

        if act is None:
            # 删除错误 - 重扣
            total_score += 0.0
        elif exp == act:
            # 完全正确
            total_score += w
        else:
            # 替换 - 按相似度部分得分
            similarity = SIMILARITY_FUNC(exp, act)
            # 给一个基础分 + 相似度加权
            partial_score = similarity * 0.7 + 0.1  # 最低0.1，最高0.8
            total_score += w * partial_score

    if total_weight == 0:
        return 0.0

    raw_score = (total_score / total_weight) * 100

    # 非线性映射，使得高分段更难获得，低分段更宽容
    # 使用 sigmoid-like 映射
    mapped_score = 100 / (1 + math.exp(-0.08 * (raw_score - 50)))

    return round(mapped_score, 1)


def calculate_fluency_score(
    timeline: List[dict],
    blank_segments: List[dict],
    total_duration: float,
    expected_phonemes: List[str],
) -> float:
    """
    计算流利度评分

    评分因素：
    1. 语速是否在合理范围
    2. 停顿次数和时长
    3. 音素时长的一致性（节奏感）
    4. 有无异常长的停顿

    参数:
        timeline: 音素时间线
        blank_segments: 停顿段
        total_duration: 总时长
        expected_phonemes: 期望音素列表

    返回:
        流利度评分 (0-100)
    """
    if total_duration <= 0 or not timeline:
        return 0.0

    score = 100.0

    # 1. 语速评分 (正常英语约 10-15 音素/秒)
    speaking_rate = len(timeline) / total_duration
    if speaking_rate < 5:
        # 太慢
        score -= (5 - speaking_rate) * 8
    elif speaking_rate > 18:
        # 太快
        score -= (speaking_rate - 18) * 5

    # 2. 停顿评分
    # 正常朗读应该在单词间有少量停顿
    num_expected_pauses = max(1, len(expected_phonemes) // 8)
    long_pauses = [p for p in blank_segments if p["duration"] > 0.5]
    medium_pauses = [p for p in blank_segments if 0.3 < p["duration"] <= 0.5]

    # 过多长停顿扣分
    if len(long_pauses) > 2:
        score -= (len(long_pauses) - 2) * 10

    # 过多中等停顿扣分
    if len(medium_pauses) > num_expected_pauses + 3:
        score -= (len(medium_pauses) - num_expected_pauses - 3) * 5

    # 总停顿时长占比
    total_pause = sum(p["duration"] for p in blank_segments)
    pause_ratio = total_pause / total_duration
    if pause_ratio > 0.4:
        score -= (pause_ratio - 0.4) * 50
    elif pause_ratio > 0.25:
        score -= (pause_ratio - 0.25) * 20

    # 3. 节奏一致性（音素时长的变异系数）
    if len(timeline) > 2:
        durations = [p["duration"] for p in timeline]
        mean_dur = sum(durations) / len(durations)
        if mean_dur > 0:
            variance = sum((d - mean_dur) ** 2 for d in durations) / len(durations)
            std_dur = math.sqrt(variance)
            cv = std_dur / mean_dur  # 变异系数
            if cv > 1.0:
                score -= (cv - 1.0) * 15

    return max(0.0, min(100.0, round(score, 1)))


def calculate_completeness_score(
    alignment: List[Tuple[Optional[str], Optional[str]]],
    expected: List[str],
) -> float:
    """
    计算完整度评分

    评分因素：
    1. 期望音素被读出的比例
    2. 是否有大量漏读
    3. 是否有大量多读（影响比例）

    参数:
        alignment: 对齐结果
        expected: 期望音素列表

    返回:
        完整度评分 (0-100)
    """
    if not expected:
        return 0.0

    # 统计匹配的期望音素数
    matched = 0
    substituted = 0
    deleted = 0

    for exp, act in alignment:
        if exp is not None:
            if act is not None:
                if exp == act:
                    matched += 1
                else:
                    substituted += 1  # 替换也算部分完整
            else:
                deleted += 1

    total = len(expected)
    # 完全匹配 + 替换部分得分
    completeness = (matched + substituted * 0.5) / total * 100

    return round(min(100.0, max(0.0, completeness)), 1)


def calculate_overall_score(
    pronunciation: float,
    fluency: float,
    completeness: float,
) -> float:
    """
    计算综合评分

    权重分配：
    - 发音准确度: 55% (最核心)
    - 完整度: 25% (是否读全)
    - 流利度: 20% (是否流畅)

    使用加权几何平均，使得各维度都重要

    参数:
        pronunciation: 发音准确度
        fluency: 流利度
        completeness: 完整度

    返回:
        综合评分 (0-100)
    """
    # 加权算术平均
    overall = (
        pronunciation * 0.55 +
        completeness * 0.25 +
        fluency * 0.20
    )

    # 如果发音准确度很低，额外惩罚
    if pronunciation < 40:
        overall *= 0.85

    return round(min(100.0, max(0.0, overall)), 1)


def generate_error_tips(errors: List[PhonemeError]) -> List[dict]:
    """
    生成错误诊断和建议

    参数:
        errors: 错误列表

    返回:
        建议列表，每个包含 error info 和 tip
    """
    tips = []
    seen = set()  # 去重

    for error in errors:
        # 优先显示替换和删除错误
        if error.error_type == "insertion":
            # 插入错误较次要，且提示有限
            tip_key = f"insert_{error.actual}"
            if tip_key not in seen:
                seen.add(tip_key)
                tips.append({
                    "type": "insertion",
                    "description": f"多读了音素 /{error.actual}/",
                    "severity": "low",
                    "tip": f"注意不要在读 /{error.actual}/ 的位置多加发音，仔细对照原文。",
                })
            continue

        tip_key = f"{error.expected}_{error.actual}"
        if tip_key in seen:
            continue
        seen.add(tip_key)

        phoneme_info = PHONEME_TIPS.get(error.expected)
        if not phoneme_info:
            continue

        if error.error_type == "deletion":
            tips.append({
                "type": "deletion",
                "phoneme": error.expected,
                "description": f"漏读了音素 /{error.expected}/",
                "severity": "high",
                "common_error": phoneme_info["common_error"],
                "solution": phoneme_info["solution"],
                "mouth_shape": phoneme_info["mouth_shape"],
            })
        elif error.error_type == "substitution":
            severity = "high" if error.similarity < 0.3 else "medium" if error.similarity < 0.5 else "low"
            tips.append({
                "type": "substitution",
                "phoneme": error.expected,
                "actual": error.actual,
                "description": f"将 /{error.expected}/ 错读为 /{error.actual}/",
                "severity": severity,
                "similarity": error.similarity,
                "common_error": phoneme_info["common_error"],
                "solution": phoneme_info["solution"],
                "mouth_shape": phoneme_info["mouth_shape"],
            })

    # 按严重程度排序
    severity_order = {"high": 0, "medium": 1, "low": 2}
    tips.sort(key=lambda x: severity_order.get(x["severity"], 3))

    return tips


def evaluate_pronunciation(
    expected_phonemes: List[str],
    actual_phonemes: List[str],
    word_boundaries: List[dict] = None,
    timeline: List[dict] = None,
    blank_segments: List[dict] = None,
    total_duration: float = 0.0,
) -> EvaluationResult:
    """
    完整的发音评测流程

    参数:
        expected_phonemes: 期望音素序列
        actual_phonemes: 实际音素序列
        word_boundaries: 单词边界信息 [{"word": str, "phonemes": [str]}]
        timeline: 音素时间线
        blank_segments: 停顿段
        total_duration: 总时长

    返回:
        EvaluationResult
    """
    # 1. 音素对齐
    alignment, total_cost = align_phonemes(expected_phonemes, actual_phonemes)

    # 2. 错误分析
    errors = analyze_errors(alignment, expected_phonemes)

    # 3. 计算各项评分
    pronunciation_score = calculate_pronunciation_score(alignment, errors, expected_phonemes)
    completeness_score = calculate_completeness_score(alignment, expected_phonemes)
    fluency_score = calculate_fluency_score(
        timeline or [], blank_segments or [], total_duration, expected_phonemes
    )
    overall_score = calculate_overall_score(pronunciation_score, fluency_score, completeness_score)

    # 4. 单词级别评分
    word_results = []
    if word_boundaries:
        word_results = _evaluate_words(word_boundaries, actual_phonemes, errors, expected_phonemes)

    # 5. 语速
    speaking_rate = len(timeline) / total_duration if total_duration > 0 and timeline else 0
    pause_count = len(blank_segments) if blank_segments else 0
    pause_duration = sum(p["duration"] for p in blank_segments) if blank_segments else 0

    return EvaluationResult(
        pronunciation_score=pronunciation_score,
        fluency_score=fluency_score,
        completeness_score=completeness_score,
        overall_score=overall_score,
        errors=errors,
        word_results=word_results,
        expected_phonemes=expected_phonemes,
        actual_phonemes=actual_phonemes,
        total_duration=total_duration,
        pause_count=pause_count,
        pause_duration=pause_duration,
        speaking_rate=speaking_rate,
    )


def _evaluate_words(
    word_boundaries: List[dict],
    actual_phonemes: List[str],
    all_errors: List[PhonemeError],
    expected_phonemes: List[str],
) -> List[WordResult]:
    """评估每个单词的发音"""
    word_results = []
    global_offset = 0

    for idx, wb in enumerate(word_boundaries):
        word = wb["word"]
        word_phonemes = wb["phonemes"]
        word_len = len(word_phonemes)

        # 找出属于这个单词的错误
        word_errors = [
            e for e in all_errors
            if global_offset <= e.position < global_offset + word_len
        ]

        # 计算单词准确度
        correct = word_len - len([e for e in word_errors if e.error_type in ("substitution", "deletion")])
        accuracy = (correct / word_len * 100) if word_len > 0 else 0

        word_results.append(WordResult(
            word=word,
            expected_phonemes=word_phonemes,
            actual_phonemes=[],  # 不做精细映射
            errors=word_errors,
            accuracy=round(accuracy, 1),
        ))

        global_offset += word_len

    return word_results


def result_to_dict(result: EvaluationResult, tips: List[dict]) -> dict:
    """将评测结果转换为 API 响应 dict"""

    def error_to_dict(e: PhonemeError) -> dict:
        return {
            "expected": e.expected,
            "actual": e.actual,
            "type": e.error_type,
            "position": e.position,
            "similarity": round(e.similarity, 2),
        }

    def word_to_dict(w: WordResult) -> dict:
        return {
            "word": w.word,
            "expected": w.expected_phonemes,
            "accuracy": w.accuracy,
            "has_error": len(w.errors) > 0,
        }

    return {
        "scores": {
            "overall": result.overall_score,
            "pronunciation": result.pronunciation_score,
            "fluency": result.fluency_score,
            "completeness": result.completeness_score,
        },
        "phonemes": {
            "expected": result.expected_phonemes,
            "actual": result.actual_phonemes,
        },
        "errors": [error_to_dict(e) for e in result.errors],
        "words": [word_to_dict(w) for w in result.word_results],
        "tips": tips,
        "fluency_details": {
            "total_duration": round(result.total_duration, 2),
            "speaking_rate": round(result.speaking_rate, 1),
            "pause_count": result.pause_count,
            "pause_duration": round(result.pause_duration, 2),
        },
    }
