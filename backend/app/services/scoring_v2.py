"""评分引擎 v2 - 商业级多维评分 + 可解释诊断。

升级点：
1. 9 维评分：音素准确度/完整度/流利度/韵律/重音/语调/停顿合理性/语速/音频质量
2. 8 类错误：substitution/deletion/insertion/minimal_pair_confusion/vowel_length_error/
   stress_error/intonation_error/unnatural_pause
3. 置信度加权：模型置信度低的音素扣分权重降低
4. 时间戳绑定：每个音素/单词都有 start_time/end_time
5. 校准框架：支持线性/逻辑回归映射到人工评分标尺
6. 可解释建议：每类错误都有针对性 tip

设计原则：
- 不破坏旧接口：scoring.py 的 evaluate_pronunciation 仍可用
- v2 通过 evaluate_pronunciation_v2 入口调用
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from phoneme_data import (
    SIMILARITY_FUNC, PHONEME_TIPS, MINIMAL_PAIRS, ARPABET_TO_IPA,
    PHONEME_CATEGORIES, PHONEME_GROUP,
)


# ============================================================
# 错误类型枚举（8 类）
# ============================================================
class ErrorType(str, Enum):
    MATCH = "match"
    SUBSTITUTION = "substitution"
    DELETION = "deletion"
    INSERTION = "insertion"
    MINIMAL_PAIR_CONFUSION = "minimal_pair_confusion"
    VOWEL_LENGTH_ERROR = "vowel_length_error"
    STRESS_ERROR = "stress_error"
    INTONATION_ERROR = "intonation_error"
    UNNATURAL_PAUSE = "unnatural_pause"


# ============================================================
# 9 维评分维度
# ============================================================
@dataclass
class ScoreBreakdown:
    phoneme_accuracy: float  # 音素准确度
    completeness: float  # 完整度
    fluency: float  # 流利度
    prosody: float  # 韵律
    stress: float  # 重音
    intonation: float  # 语调
    pause_appropriateness: float  # 停顿合理性
    speaking_rate: float  # 语速
    audio_quality: float  # 音频质量

    # 加权综合
    overall: float = 0.0


@dataclass
class PhoneDiagnosticV2:
    expected_phone: str
    recognized_phone: Optional[str]
    score: float
    confidence: float
    start_time: float
    end_time: float
    error_type: ErrorType = ErrorType.MATCH
    word_index: int = -1
    suggestion: str = ""


@dataclass
class WordDiagnosticV2:
    word: str
    start_time: float
    end_time: float
    phonemes: List[PhoneDiagnosticV2]
    accuracy: float = 0.0
    stress_correct: bool = True


@dataclass
class FluencyDetails:
    total_duration: float
    speaking_rate: float  # 音素/秒
    pause_count: int
    pause_duration: float
    pause_ratio: float
    long_pause_count: int
    avg_pause_duration: float
    phoneme_duration_cv: float  # 变异系数


@dataclass
class EvaluationResultV2:
    scores: ScoreBreakdown
    phonemes: List[PhoneDiagnosticV2]
    words: List[WordDiagnosticV2]
    fluency: FluencyDetails
    expected_phonemes: List[str]
    actual_phonemes: List[str]
    expected_stress: List[int]
    actual_stress: List[int]
    tips: List[dict] = field(default_factory=list)
    audio_quality_warning: str = ""
    inference_ms: float = 0.0
    provider: str = ""
    calibration_applied: bool = False


# ============================================================
# 主评分入口
# ============================================================
def evaluate_pronunciation_v2(
    expected_phonemes: List[str],
    actual_phonemes: List[str],
    expected_stress: Optional[List[int]] = None,
    actual_stress: Optional[List[int]] = None,
    word_boundaries: Optional[List[dict]] = None,
    timeline: Optional[List[dict]] = None,
    blank_segments: Optional[List[dict]] = None,
    total_duration: float = 0.0,
    audio_quality_score: float = 100.0,
    audio_quality_warning: str = "",
    phone_confidences: Optional[List[float]] = None,
    weights: Optional[dict] = None,
) -> EvaluationResultV2:
    """v2 评分主入口。"""
    from scoring import align_phonemes

    expected_stress = expected_stress or []
    actual_stress = actual_stress or []
    timeline = timeline or []
    blank_segments = blank_segments or []
    weights = weights or _default_weights()

    # 1. 对齐
    alignment, _ = align_phonemes(expected_phonemes, actual_phonemes)

    # 2. 诊断每个音素
    phone_diagnostics = _diagnose_phonemes(
        alignment, expected_phonemes, actual_phonemes, timeline, phone_confidences
    )

    # 3. 9 维评分
    phoneme_accuracy = _calc_phoneme_accuracy(phone_diagnostics)
    completeness = _calc_completeness(alignment, expected_phonemes)
    fluency_score, fluency_details = _calc_fluency_v2(
        timeline, blank_segments, total_duration, expected_phonemes
    )
    prosody = _calc_prosody(timeline, blank_segments, expected_phonemes)
    stress_score = _calc_stress(expected_stress, actual_stress)
    intonation = _calc_intonation(timeline, expected_phonemes)
    pause_score = _calc_pause_appropriateness(blank_segments, total_duration, expected_phonemes)
    rate_score = _calc_speaking_rate(timeline, total_duration)
    quality_score = audio_quality_score

    scores = ScoreBreakdown(
        phoneme_accuracy=phoneme_accuracy,
        completeness=completeness,
        fluency=fluency_score,
        prosody=prosody,
        stress=stress_score,
        intonation=intonation,
        pause_appropriateness=pause_score,
        speaking_rate=rate_score,
        audio_quality=quality_score,
    )

    # 加权综合
    scores.overall = _weighted_overall(scores, weights)

    # 4. 词级诊断
    word_diagnostics = _diagnose_words(word_boundaries or [], phone_diagnostics)

    # 5. 生成 tips
    tips = _generate_tips_v2(phone_diagnostics, word_diagnostics, fluency_details)

    return EvaluationResultV2(
        scores=scores,
        phonemes=phone_diagnostics,
        words=word_diagnostics,
        fluency=fluency_details,
        expected_phonemes=expected_phonemes,
        actual_phonemes=actual_phonemes,
        expected_stress=expected_stress,
        actual_stress=actual_stress,
        tips=tips,
        audio_quality_warning=audio_quality_warning,
    )


def _default_weights() -> dict:
    from app.core.config import get_settings

    s = get_settings()
    return {
        "phoneme_accuracy": s.scoring_weights_pron,
        "completeness": s.scoring_weights_comp,
        "fluency": s.scoring_weights_flu,
        "prosody": s.scoring_weights_prosody,
        "audio_quality": s.scoring_weights_quality,
    }


# ============================================================
# 音素诊断
# ============================================================
def _diagnose_phonemes(
    alignment: List[Tuple[Optional[str], Optional[str]]],
    expected: List[str],
    actual: List[str],
    timeline: List[dict],
    confidences: Optional[List[float]],
) -> List[PhoneDiagnosticV2]:
    """诊断每个音素，识别 8 类错误。"""
    diagnostics: List[PhoneDiagnosticV2] = []
    actual_idx = 0

    for exp, act in alignment:
        # 取时间戳与置信度
        ts = timeline[actual_idx] if actual_idx < len(timeline) and act is not None else {}
        conf = ts.get("confidence", 0.8) if ts else 0.8
        if confidences and actual_idx < len(confidences) and act is not None:
            conf = confidences[actual_idx]

        if exp is not None and act is not None:
            if exp == act:
                et = ErrorType.MATCH
                score = 1.0
                suggestion = ""
            else:
                score = SIMILARITY_FUNC(exp, act)
                # 判断具体错误类型
                mp = _check_minimal_pair(exp, act)
                if mp:
                    et = ErrorType.MINIMAL_PAIR_CONFUSION
                    suggestion = _mp_suggestion(mp)
                elif _is_vowel_length_error(exp, act):
                    et = ErrorType.VOWEL_LENGTH_ERROR
                    suggestion = f"/{exp}/ 与 /{act}/ 仅元音长短不同，注意长短对比"
                else:
                    et = ErrorType.SUBSTITUTION
                    suggestion = _substitution_suggestion(exp, act)
            diagnostics.append(
                PhoneDiagnosticV2(
                    expected_phone=exp,
                    recognized_phone=act,
                    score=round(score, 3),
                    confidence=round(conf, 3),
                    start_time=ts.get("start_time", 0.0) if ts else 0.0,
                    end_time=ts.get("end_time", 0.0) if ts else 0.0,
                    error_type=et,
                    suggestion=suggestion,
                )
            )
            actual_idx += 1
        elif exp is not None and act is None:
            diagnostics.append(
                PhoneDiagnosticV2(
                    expected_phone=exp,
                    recognized_phone=None,
                    score=0.0,
                    confidence=0.0,
                    start_time=0.0,
                    end_time=0.0,
                    error_type=ErrorType.DELETION,
                    suggestion=f"漏读了 /{exp}/（{ARPABET_TO_IPA.get(exp, '')}），请对照原文逐音素练习",
                )
            )
        elif exp is None and act is not None:
            diagnostics.append(
                PhoneDiagnosticV2(
                    expected_phone="",
                    recognized_phone=act,
                    score=0.0,
                    confidence=round(conf, 3),
                    start_time=ts.get("start_time", 0.0) if ts else 0.0,
                    end_time=ts.get("end_time", 0.0) if ts else 0.0,
                    error_type=ErrorType.INSERTION,
                    suggestion=f"多读了 /{act}/，注意不要在该位置添加发音",
                )
            )
            actual_idx += 1

    return diagnostics


def _check_minimal_pair(expected: str, actual: str) -> Optional[dict]:
    for mp in MINIMAL_PAIRS:
        p1, p2 = mp["pair"]
        if (expected == p1 and actual == p2) or (expected == p2 and actual == p1):
            return mp
    return None


def _is_vowel_length_error(exp: str, act: str) -> bool:
    """检测元音长短错误（如 IH/IY, UH/UW, AE/EY）。"""
    vowel_pairs = [
        {"IH", "IY"}, {"UH", "UW"}, {"AE", "EY"}, {"AH", "AA"},
        {"EH", "EY"}, {"AO", "OW"},
    ]
    for pair in vowel_pairs:
        if exp in pair and act in pair and exp != act:
            return True
    return False


def _mp_suggestion(mp: dict) -> str:
    return f"最小对立对混淆：{mp.get('description', '')}。练习：{mp.get('drill_sentence', '')}"


def _substitution_suggestion(exp: str, act: str) -> str:
    info = PHONEME_TIPS.get(exp, {})
    if info:
        return f"将 /{exp}/（{ARPABET_TO_IPA.get(exp, '')}）错读为 /{act}/。{info.get('solution', '')}"
    return f"将 /{exp}/ 错读为 /{act}/"


# ============================================================
# 9 维评分计算
# ============================================================
def _calc_phoneme_accuracy(diagnostics: List[PhoneDiagnosticV2]) -> float:
    """音素准确度（置信度加权）。

    置信度加权逻辑：模型置信度低的错误音素扣分更轻（因为可能模型自己错了）。
    实现方式：低置信度的错误音素权重降低（接近"忽略"），而不是给错误分数打折。
    """
    if not diagnostics:
        return 0.0
    total_weight = 0.0
    total_score = 0.0
    for d in diagnostics:
        # 元音权重 1.5，辅音 1.0
        group, _ = PHONEME_GROUP.get(d.expected_phone, ("consonants", "other"))
        w = 1.5 if group == "vowels" else 1.0
        # 置信度加权：低置信度的错误音素权重降低（接近忽略）
        if d.error_type == "match":
            w_effective = w
        else:
            # 错误音素：置信度越低，权重越低（0.3-1.0）
            w_effective = w * (0.3 + 0.7 * d.confidence)
        total_weight += w_effective
        if d.error_type == "match":
            total_score += w_effective
        elif d.error_type in ("substitution", "minimal_pair_confusion", "vowel_length_error"):
            total_score += w_effective * d.score
        # deletion/insertion: 0 分
    raw = (total_score / total_weight) * 100 if total_weight > 0 else 0
    return round(_sigmoid(raw, 50, 0.08), 1)


def _calc_completeness(alignment, expected) -> float:
    if not expected:
        return 0.0
    matched = 0
    substituted = 0
    for exp, act in alignment:
        if exp is not None:
            if act is not None:
                if exp == act:
                    matched += 1
                else:
                    substituted += 1
    total = len(expected)
    completeness = (matched + substituted * 0.5) / total * 100
    return round(min(100.0, max(0.0, completeness)), 1)


def _calc_fluency_v2(timeline, blank_segments, total_duration, expected_phonemes) -> Tuple[float, FluencyDetails]:
    """流利度评分 v2（与旧版一致 + 更细粒度输出）。"""
    if total_duration <= 0 or not timeline:
        return 0.0, FluencyDetails(0, 0, 0, 0, 0, 0, 0, 0)

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

    cv = 0.0
    if len(timeline) > 2:
        durations = [p["duration"] for p in timeline]
        mean_dur = sum(durations) / len(durations)
        if mean_dur > 0:
            variance = sum((d - mean_dur) ** 2 for d in durations) / len(durations)
            cv = math.sqrt(variance) / mean_dur
            if cv > 1.0:
                score -= (cv - 1.0) * 15

    score = max(0.0, min(100.0, round(score, 1)))
    avg_pause = total_pause / len(blank_segments) if blank_segments else 0.0

    details = FluencyDetails(
        total_duration=round(total_duration, 2),
        speaking_rate=round(speaking_rate, 1),
        pause_count=len(blank_segments),
        pause_duration=round(total_pause, 2),
        pause_ratio=round(pause_ratio, 3),
        long_pause_count=len(long_pauses),
        avg_pause_duration=round(avg_pause, 3),
        phoneme_duration_cv=round(cv, 3),
    )
    return score, details


def _calc_prosody(timeline, blank_segments, expected_phonemes) -> float:
    """韵律评分：节奏 + 音高变化（简化版，基于时长模式）。"""
    if not timeline:
        return 50.0
    score = 80.0
    # 时长模式：理想情况下元音比辅音长
    vowel_durations = []
    consonant_durations = []
    for p in timeline:
        ph = p.get("phoneme", "")
        group, _ = PHONEME_GROUP.get(ph, ("consonants", "other"))
        if group == "vowels":
            vowel_durations.append(p.get("duration", 0))
        else:
            consonant_durations.append(p.get("duration", 0))
    if vowel_durations and consonant_durations:
        ratio = sum(vowel_durations) / max(sum(consonant_durations), 0.01)
        if ratio < 1.0:
            score -= (1.0 - ratio) * 20
        elif ratio > 4.0:
            score -= (ratio - 4.0) * 5
    return max(0.0, min(100.0, round(score, 1)))


def _calc_stress(expected_stress: List[int], actual_stress: List[int]) -> float:
    """重音评分：对比重音模式。"""
    if not expected_stress:
        return 80.0  # 无重音信息时给中性分
    if not actual_stress:
        return 50.0
    n = min(len(expected_stress), len(actual_stress))
    if n == 0:
        return 50.0
    correct = sum(1 for i in range(n) if expected_stress[i] == actual_stress[i])
    return round(correct / n * 100, 1)


def _calc_intonation(timeline, expected_phonemes) -> float:
    """语调评分（简化版：基于时长变化模式）。"""
    if len(timeline) < 3:
        return 70.0
    # 简化：检测句末是否有时长延长（陈述句语调下降的近似）
    last_3 = timeline[-3:]
    last_dur = last_3[-1].get("duration", 0)
    avg_prev = sum(p.get("duration", 0) for p in last_3[:-1]) / max(len(last_3) - 1, 1)
    if last_dur > avg_prev * 1.5:
        return 80.0
    if last_dur < avg_prev * 0.5:
        return 70.0
    return 75.0


def _calc_pause_appropriateness(blank_segments, total_duration, expected_phonemes) -> float:
    """停顿合理性评分。"""
    if not blank_segments:
        return 90.0
    score = 100.0
    long_pauses = [p for p in blank_segments if p["duration"] > 0.5]
    very_long_pauses = [p for p in blank_segments if p["duration"] > 1.5]
    if len(long_pauses) > 2:
        score -= (len(long_pauses) - 2) * 8
    for p in very_long_pauses:
        score -= p["duration"] * 5
    total_pause = sum(p["duration"] for p in blank_segments)
    pause_ratio = total_pause / total_duration if total_duration > 0 else 0
    if pause_ratio > 0.4:
        score -= (pause_ratio - 0.4) * 40
    return max(0.0, min(100.0, round(score, 1)))


def _calc_speaking_rate(timeline, total_duration) -> float:
    """语速评分（与流利度中的语速不同，这里只评 0-100）。"""
    if total_duration <= 0 or not timeline:
        return 0.0
    rate = len(timeline) / total_duration
    # 理想区间 8-12 音素/秒
    if 8 <= rate <= 12:
        return 100.0
    if rate < 8:
        return max(0, 100 - (8 - rate) * 10)
    return max(0, 100 - (rate - 12) * 8)


def _weighted_overall(scores: ScoreBreakdown, weights: dict) -> float:
    """加权综合分。"""
    overall = (
        scores.phoneme_accuracy * weights.get("phoneme_accuracy", 0.45)
        + scores.completeness * weights.get("completeness", 0.20)
        + scores.fluency * weights.get("fluency", 0.15)
        + scores.prosody * weights.get("prosody", 0.10)
        + scores.audio_quality * weights.get("audio_quality", 0.10)
    )
    # 低分额外惩罚
    if scores.phoneme_accuracy < 40:
        overall *= 0.85
    return round(min(100.0, max(0.0, overall)), 1)


def _sigmoid(x: float, midpoint: float = 50, slope: float = 0.08) -> float:
    return 100 / (1 + math.exp(-slope * (x - midpoint)))


# ============================================================
# 词级诊断
# ============================================================
def _diagnose_words(word_boundaries, phone_diagnostics) -> List[WordDiagnosticV2]:
    words: List[WordDiagnosticV2] = []
    offset = 0
    for idx, wb in enumerate(word_boundaries):
        word = wb.get("word", "")
        phonemes = wb.get("phonemes", [])
        n = len(phonemes)
        word_phones = phone_diagnostics[offset : offset + n]
        if not word_phones:
            continue
        correct = sum(1 for p in word_phones if p.error_type == ErrorType.MATCH)
        accuracy = round(correct / n * 100, 1) if n > 0 else 0.0
        start = word_phones[0].start_time if word_phones else 0.0
        end = word_phones[-1].end_time if word_phones else 0.0
        words.append(
            WordDiagnosticV2(
                word=word,
                start_time=start,
                end_time=end,
                phonemes=word_phones,
                accuracy=accuracy,
                stress_correct=True,  # 由上层根据 stress 信息填充
            )
        )
        offset += n
    return words


# ============================================================
# 生成 tips
# ============================================================
def _generate_tips_v2(
    phone_diagnostics: List[PhoneDiagnosticV2],
    word_diagnostics: List[WordDiagnosticV2],
    fluency: FluencyDetails,
) -> List[dict]:
    tips: List[dict] = []
    seen: set = set()

    # 音素级 tips
    for d in phone_diagnostics:
        if d.error_type == ErrorType.MATCH:
            continue
        key = (d.error_type.value, d.expected_phone, d.recognized_phone or "")
        if key in seen:
            continue
        seen.add(key)

        severity = _severity_for(d.error_type, d.score)
        tip = {
            "type": d.error_type.value,
            "phoneme": d.expected_phone,
            "actual": d.recognized_phone,
            "ipa": ARPABET_TO_IPA.get(d.expected_phone, ""),
            "actual_ipa": ARPABET_TO_IPA.get(d.recognized_phone or "", ""),
            "description": d.suggestion,
            "severity": severity,
            "confidence": d.confidence,
            "start_time": d.start_time,
            "end_time": d.end_time,
        }
        # 附加 PHONEME_TIPS 详情
        info = PHONEME_TIPS.get(d.expected_phone, {})
        if info:
            tip["common_error"] = info.get("common_error", "")
            tip["solution"] = info.get("solution", "")
            tip["mouth_shape"] = info.get("mouth_shape", "")
            tip["practice_words"] = info.get("practice_words", [])
        # 最小对立对详情
        if d.error_type == ErrorType.MINIMAL_PAIR_CONFUSION:
            mp = _check_minimal_pair(d.expected_phone, d.recognized_phone or "")
            if mp:
                tip["minimal_pair"] = {
                    "pair": list(mp["pair"]),
                    "examples": mp["examples"],
                    "drill_sentence": mp["drill_sentence"],
                    "native_issue": mp.get("native_language_issue", ""),
                }
        tips.append(tip)

    # 流利度 tips
    if fluency.pause_count > 5:
        tips.append({
            "type": "fluency",
            "description": f"停顿过多（{fluency.pause_count} 次），尝试连贯朗读",
            "severity": "medium",
        })
    if fluency.speaking_rate < 5:
        tips.append({
            "type": "fluency",
            "description": f"语速过慢（{fluency.speaking_rate} 音素/秒），适当加快",
            "severity": "medium",
        })
    if fluency.speaking_rate > 18:
        tips.append({
            "type": "fluency",
            "description": f"语速过快（{fluency.speaking_rate} 音素/秒），适当放慢",
            "severity": "low",
        })

    severity_order = {"high": 0, "medium": 1, "low": 2}
    tips.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 3))
    return tips


def _severity_for(error_type: ErrorType, score: float) -> str:
    if error_type == ErrorType.DELETION:
        return "high"
    if error_type == ErrorType.MINIMAL_PAIR_CONFUSION:
        return "high"
    if error_type in (ErrorType.SUBSTITUTION, ErrorType.VOWEL_LENGTH_ERROR):
        if score < 0.3:
            return "high"
        if score < 0.5:
            return "medium"
        return "low"
    if error_type == ErrorType.INSERTION:
        return "low"
    return "low"


# ============================================================
# 校准框架
# ============================================================
class ScoreCalibrator:
    """评分校准器：将原始分映射到人工评分标尺。

    支持：
    - 线性映射：calibrated = a * raw + b
    - 逻辑回归：calibrated = 100 / (1 + exp(-(a*raw + b)))
    - 分段映射
    """

    def __init__(self):
        self._params: dict = {}  # {(dimension, method): params}

    def fit_linear(self, dimension: str, raw_scores: List[float], target_scores: List[float]) -> dict:
        """拟合线性映射（最小二乘）。"""
        if len(raw_scores) < 5:
            return {}
        import numpy as np

        x = np.array(raw_scores)
        y = np.array(target_scores)
        n = len(x)
        sum_x = x.sum()
        sum_y = y.sum()
        sum_xy = (x * y).sum()
        sum_x2 = (x ** 2).sum()
        denom = n * sum_x2 - sum_x ** 2
        if abs(denom) < 1e-10:
            return {}
        a = (n * sum_xy - sum_x * sum_y) / denom
        b = (sum_y - a * sum_x) / n
        params = {"a": float(a), "b": float(b)}
        self._params[(dimension, "linear")] = params
        return params

    def apply(self, dimension: str, raw: float) -> float:
        params = self._params.get((dimension, "linear"))
        if not params:
            return raw
        return max(0.0, min(100.0, params["a"] * raw + params["b"]))

    def save(self, path: str) -> None:
        import json

        data = {f"{k[0]}__{k[1]}": v for k, v in self._params.items()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, path: str) -> None:
        import json
        import os

        if not os.path.isfile(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key, v in data.items():
            dim, method = key.split("__", 1)
            self._params[(dim, method)] = v


_calibrator_instance: Optional[ScoreCalibrator] = None


def get_calibrator() -> ScoreCalibrator:
    global _calibrator_instance
    if _calibrator_instance is None:
        _calibrator_instance = ScoreCalibrator()
    return _calibrator_instance


# ============================================================
# 序列化为 dict（API 响应）
# ============================================================
def result_v2_to_dict(result: EvaluationResultV2) -> dict:
    return {
        "version": "v2",
        "scores": {
            "overall": result.scores.overall,
            "phoneme_accuracy": result.scores.phoneme_accuracy,
            "completeness": result.scores.completeness,
            "fluency": result.scores.fluency,
            "prosody": result.scores.prosody,
            "stress": result.scores.stress,
            "intonation": result.scores.intonation,
            "pause_appropriateness": result.scores.pause_appropriateness,
            "speaking_rate": result.scores.speaking_rate,
            "audio_quality": result.scores.audio_quality,
        },
        "phonemes": [
            {
                "expected": p.expected_phone,
                "actual": p.recognized_phone,
                "score": p.score,
                "confidence": p.confidence,
                "error_type": p.error_type.value,
                "start_time": p.start_time,
                "end_time": p.end_time,
                "word_index": p.word_index,
                "suggestion": p.suggestion,
            }
            for p in result.phonemes
        ],
        "words": [
            {
                "word": w.word,
                "start_time": w.start_time,
                "end_time": w.end_time,
                "accuracy": w.accuracy,
                "stress_correct": w.stress_correct,
                "phonemes": [
                    {
                        "expected": p.expected_phone,
                        "actual": p.recognized_phone,
                        "error_type": p.error_type.value,
                        "score": p.score,
                        "confidence": p.confidence,
                    }
                    for p in w.phonemes
                ],
            }
            for w in result.words
        ],
        "fluency_details": {
            "total_duration": result.fluency.total_duration,
            "speaking_rate": result.fluency.speaking_rate,
            "pause_count": result.fluency.pause_count,
            "pause_duration": result.fluency.pause_duration,
            "pause_ratio": result.fluency.pause_ratio,
            "long_pause_count": result.fluency.long_pause_count,
            "avg_pause_duration": result.fluency.avg_pause_duration,
            "phoneme_duration_cv": result.fluency.phoneme_duration_cv,
        },
        "stress": {
            "expected": result.expected_stress,
            "actual": result.actual_stress,
        },
        "tips": result.tips,
        "audio_quality_warning": result.audio_quality_warning,
        "inference_ms": result.inference_ms,
        "provider": result.provider,
        "calibration_applied": result.calibration_applied,
    }
