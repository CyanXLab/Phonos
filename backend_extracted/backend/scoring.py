"""
评分算法 - 发音评测核心

基于音素对比的发音评分系统
"""

import math
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field

from phoneme_data import SIMILARITY_FUNC, PHONEME_TIPS, MINIMAL_PAIRS, ARPABET_TO_IPA


@dataclass
class PhonemeError:
    expected: str
    actual: Optional[str]
    error_type: str
    position: int
    similarity: float
    word_index: int = -1
    is_minimal_pair_issue: bool = False
    minimal_pair_detail: Optional[dict] = None


@dataclass
class WordResult:
    word: str
    expected_phonemes: List[str]
    actual_phonemes: List[str]
    errors: List[PhonemeError]
    accuracy: float


@dataclass
class EvaluationResult:
    pronunciation_score: float
    fluency_score: float
    completeness_score: float
    overall_score: float
    errors: List[PhonemeError]
    word_results: List[WordResult]
    expected_phonemes: List[str]
    actual_phonemes: List[str]
    total_duration: float = 0.0
    pause_count: int = 0
    pause_duration: float = 0.0
    speaking_rate: float = 0.0


def align_phonemes(
    expected: List[str],
    actual: List[str],
    sub_cost_func=None,
    ins_cost: float = 1.0,
    del_cost: float = 1.0,
) -> Tuple[List[Tuple[Optional[str], Optional[str]]], float]:
    """动态规划音素序列对齐"""
    if sub_cost_func is None:
        def sub_cost_func(p1, p2):
            return 1.0 - SIMILARITY_FUNC(p1, p2)

    m, n = len(expected), len(actual)
    dp = [[0.0] * (n + 1) for _ in range(m + 1)]
    trace = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        dp[i][0] = dp[i - 1][0] + del_cost
        trace[i][0] = 1
    for j in range(1, n + 1):
        dp[0][j] = dp[0][j - 1] + ins_cost
        trace[0][j] = 2

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


def _check_minimal_pair(expected: str, actual: str) -> Optional[dict]:
    """检查是否为最小对立对错误"""
    for mp in MINIMAL_PAIRS:
        p1, p2 = mp["pair"]
        if (expected == p1 and actual == p2) or (expected == p2 and actual == p1):
            return mp
    return None


def analyze_errors(
    alignment: List[Tuple[Optional[str], Optional[str]]],
    expected_phonemes: List[str],
) -> List[PhonemeError]:
    """分析对齐结果，生成错误列表（含最小对立对检测）"""
    errors = []
    expected_idx = 0

    for exp, act in alignment:
        if exp is not None and act is not None:
            if exp != act:
                similarity = SIMILARITY_FUNC(exp, act)
                mp_detail = _check_minimal_pair(exp, act)
                errors.append(PhonemeError(
                    expected=exp, actual=act, error_type="substitution",
                    position=expected_idx, similarity=similarity,
                    is_minimal_pair_issue=mp_detail is not None,
                    minimal_pair_detail=mp_detail,
                ))
            expected_idx += 1
        elif exp is not None and act is None:
            errors.append(PhonemeError(
                expected=exp, actual=None, error_type="deletion",
                position=expected_idx, similarity=0.0,
            ))
            expected_idx += 1
        elif exp is None and act is not None:
            errors.append(PhonemeError(
                expected="", actual=act, error_type="insertion",
                position=expected_idx, similarity=0.0,
            ))

    return errors


def calculate_pronunciation_score(
    alignment: List[Tuple[Optional[str], Optional[str]]],
    errors: List[PhonemeError],
    expected: List[str],
) -> float:
    """发音准确度评分"""
    if not expected:
        return 0.0

    from phoneme_data import PHONEME_GROUP

    total_score = 0.0
    total_weight = 0.0
    weight_map = {"vowels": 1.5, "consonants": 1.0}

    def get_weight(phoneme: str) -> float:
        group, _ = PHONEME_GROUP.get(phoneme, ("consonants", "other"))
        return weight_map.get(group, 1.0)

    for exp, act in alignment:
        if exp is None:
            total_weight += 0.5
            continue
        w = get_weight(exp)
        total_weight += w
        if act is None:
            total_score += 0.0
        elif exp == act:
            total_score += w
        else:
            similarity = SIMILARITY_FUNC(exp, act)
            partial_score = similarity * 0.7 + 0.1
            total_score += w * partial_score

    if total_weight == 0:
        return 0.0

    raw_score = (total_score / total_weight) * 100
    mapped_score = 100 / (1 + math.exp(-0.08 * (raw_score - 50)))
    return round(mapped_score, 1)


def calculate_fluency_score(
    timeline: List[dict],
    blank_segments: List[dict],
    total_duration: float,
    expected_phonemes: List[str],
) -> float:
    """流利度评分"""
    if total_duration <= 0 or not timeline:
        return 0.0

    score = 100.0
    speaking_rate = len(timeline) / total_duration

    if speaking_rate < 5:
        score -= (5 - speaking_rate) * 8
    elif speaking_rate > 18:
        score -= (speaking_rate - 18) * 5

    num_expected_pauses = max(1, len(expected_phonemes) // 8)
    long_pauses = [p for p in blank_segments if p["duration"] > 0.5]
    medium_pauses = [p for p in blank_segments if 0.3 < p["duration"] <= 0.5]

    if len(long_pauses) > 2:
        score -= (len(long_pauses) - 2) * 10
    if len(medium_pauses) > num_expected_pauses + 3:
        score -= (len(medium_pauses) - num_expected_pauses - 3) * 5

    total_pause = sum(p["duration"] for p in blank_segments)
    pause_ratio = total_pause / total_duration
    if pause_ratio > 0.4:
        score -= (pause_ratio - 0.4) * 50
    elif pause_ratio > 0.25:
        score -= (pause_ratio - 0.25) * 20

    if len(timeline) > 2:
        durations = [p["duration"] for p in timeline]
        mean_dur = sum(durations) / len(durations)
        if mean_dur > 0:
            variance = sum((d - mean_dur) ** 2 for d in durations) / len(durations)
            cv = math.sqrt(variance) / mean_dur
            if cv > 1.0:
                score -= (cv - 1.0) * 15

    return max(0.0, min(100.0, round(score, 1)))


def calculate_completeness_score(
    alignment: List[Tuple[Optional[str], Optional[str]]],
    expected: List[str],
) -> float:
    """完整度评分"""
    if not expected:
        return 0.0

    matched = 0
    substituted = 0
    deleted = 0

    for exp, act in alignment:
        if exp is not None:
            if act is not None:
                if exp == act:
                    matched += 1
                else:
                    substituted += 1
            else:
                deleted += 1

    total = len(expected)
    completeness = (matched + substituted * 0.5) / total * 100
    return round(min(100.0, max(0.0, completeness)), 1)


def calculate_overall_score(pronunciation: float, fluency: float, completeness: float) -> float:
    """综合评分"""
    overall = pronunciation * 0.55 + completeness * 0.25 + fluency * 0.20
    if pronunciation < 40:
        overall *= 0.85
    return round(min(100.0, max(0.0, overall)), 1)


def generate_error_tips(errors: List[PhonemeError]) -> List[dict]:
    """生成错误诊断和建议（含最小对立对额外信息）"""
    tips = []
    seen = set()

    for error in errors:
        if error.error_type == "insertion":
            tip_key = f"insert_{error.actual}"
            if tip_key not in seen:
                seen.add(tip_key)
                tips.append({
                    "type": "insertion",
                    "description": f"多读了音素 /{error.actual}/",
                    "severity": "low",
                    "tip": f"注意不要在读 /{error.actual}/ 的位置多加发音，仔细对照原文逐词练习。",
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
                "ipa": ARPABET_TO_IPA.get(error.expected, ""),
                "description": f"漏读了音素 /{error.expected}/ ({ARPABET_TO_IPA.get(error.expected, '')})",
                "severity": "high",
                "common_error": phoneme_info.get("common_error", ""),
                "solution": phoneme_info.get("solution", ""),
                "mouth_shape": phoneme_info.get("mouth_shape", ""),
                "practice_words": phoneme_info.get("practice_words", []),
            })
        elif error.error_type == "substitution":
            severity = "high" if error.similarity < 0.3 else "medium" if error.similarity < 0.5 else "low"
            tip_data = {
                "type": "substitution",
                "phoneme": error.expected,
                "actual": error.actual,
                "ipa": ARPABET_TO_IPA.get(error.expected, ""),
                "actual_ipa": ARPABET_TO_IPA.get(error.actual, ""),
                "description": f"将 /{error.expected}/ ({ARPABET_TO_IPA.get(error.expected, '')}) 错读为 /{error.actual}/ ({ARPABET_TO_IPA.get(error.actual, '')})",
                "severity": severity,
                "similarity": error.similarity,
                "common_error": phoneme_info.get("common_error", ""),
                "solution": phoneme_info.get("solution", ""),
                "mouth_shape": phoneme_info.get("mouth_shape", ""),
                "practice_words": phoneme_info.get("practice_words", []),
            }
            # 最小对立对额外信息
            if error.is_minimal_pair_issue and error.minimal_pair_detail:
                mp = error.minimal_pair_detail
                tip_data["minimal_pair"] = {
                    "pair": list(mp["pair"]),
                    "examples": mp["examples"],
                    "description": mp["description"],
                    "drill_sentence": mp["drill_sentence"],
                    "native_issue": mp.get("native_language_issue", ""),
                }
            tips.append(tip_data)

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
    """完整发音评测"""
    alignment, _ = align_phonemes(expected_phonemes, actual_phonemes)
    errors = analyze_errors(alignment, expected_phonemes)

    pronunciation_score = calculate_pronunciation_score(alignment, errors, expected_phonemes)
    completeness_score = calculate_completeness_score(alignment, expected_phonemes)
    fluency_score = calculate_fluency_score(timeline or [], blank_segments or [], total_duration, expected_phonemes)
    overall_score = calculate_overall_score(pronunciation_score, fluency_score, completeness_score)

    word_results = []
    if word_boundaries:
        word_results = _evaluate_words(word_boundaries, actual_phonemes, errors, expected_phonemes)

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


def _evaluate_words(word_boundaries, actual_phonemes, all_errors, expected_phonemes):
    word_results = []
    global_offset = 0
    for idx, wb in enumerate(word_boundaries):
        word = wb["word"]
        word_phonemes = wb["phonemes"]
        word_len = len(word_phonemes)
        word_errors = [e for e in all_errors if global_offset <= e.position < global_offset + word_len]
        correct = word_len - len([e for e in word_errors if e.error_type in ("substitution", "deletion")])
        accuracy = (correct / word_len * 100) if word_len > 0 else 0
        word_results.append(WordResult(
            word=word, expected_phonemes=word_phonemes, actual_phonemes=[],
            errors=word_errors, accuracy=round(accuracy, 1),
        ))
        global_offset += word_len
    return word_results


def result_to_dict(result: EvaluationResult, tips: List[dict]) -> dict:
    """将评测结果转换为 API 响应 dict"""

    def error_to_dict(e: PhonemeError) -> dict:
        d = {
            "expected": e.expected,
            "actual": e.actual,
            "type": e.error_type,
            "position": e.position,
            "similarity": round(e.similarity, 2),
            "is_minimal_pair": e.is_minimal_pair_issue,
        }
        if e.is_minimal_pair_issue and e.minimal_pair_detail:
            mp = e.minimal_pair_detail
            d["minimal_pair"] = {
                "pair": list(mp["pair"]),
                "drill_sentence": mp["drill_sentence"],
                "native_issue": mp.get("native_language_issue", ""),
            }
        return d

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
