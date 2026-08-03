"""本地 HuPER Provider：包装原 onnx_service，扩展置信度、音质检测、IPA→ARPAbet 转换。"""

from __future__ import annotations

import time
from typing import List, Optional

import numpy as np

from ..core.config import get_settings
from ..core.logging import get_logger
from .ipa_mapping import ipa_to_arpabet
from .pronunciation_provider import (
    AudioQualityReport,
    ModelMode,
    PhoneSegment,
    PhonemeDiagnostic,
    ProviderKind,
    PronunciationProvider,
    WordSegment,
)


logger = get_logger("local_huper")


class LocalHuPERProvider(PronunciationProvider):
    """本地 HuPER 音素识别 Provider。

    升级点：
    1. softmax 置信度保留（不再仅 argmax）
    2. 音频质量检测（SNR/clipping/silence）
    3. forced alignment 输出 word-level 时间戳
    4. 三档性能模式（high/balanced/low）
    """

    kind = ProviderKind.LOCAL_HUPER
    requires_network = False
    requires_api_key = False
    is_enabled_by_default = True

    def __init__(self, model_path: str):
        self.model_path = model_path
        self._recognizer = None
        self._mode = ModelMode.BALANCED

    def _ensure_loaded(self):
        if self._recognizer is None:
            from onnx_service import HuPERRecognizer

            settings = get_settings()
            # 应用 provider 配置
            providers = settings.get_provider_list()
            self._recognizer = HuPERRecognizer(
                self.model_path,
                providers=providers,
                intra_op_threads=settings.huper_intra_op_threads,
                inter_op_threads=settings.huper_inter_op_threads,
            )
            logger.info(
                "huper_loaded",
                path=self.model_path,
                provider=self._recognizer.provider,
                mode=self._mode.value,
            )

    def is_available(self) -> bool:
        try:
            self._ensure_loaded()
            return self._recognizer is not None
        except Exception:
            return False

    def diagnose(
        self,
        audio: np.ndarray,
        sample_rate: int,
        expected_phonemes: List[str],
        word_boundaries: Optional[List[dict]] = None,
        mode: ModelMode = ModelMode.BALANCED,
    ) -> PhonemeDiagnostic:
        self._mode = mode
        self._ensure_loaded()
        t0 = time.perf_counter()

        # 1. 音频质量检测
        quality = _detect_audio_quality(audio, sample_rate)

        # 2. 推理（含 softmax 置信度）
        result = self._recognizer.recognize_with_confidence(audio, sample_rate)
        ipa_phonemes = result["phonemes"]  # IPA 音素列表
        timeline = result["timeline"]
        frame_confidences = result.get("frame_confidences", [])

        # 3. IPA → ARPAbet 转换（兼容原评分逻辑）
        arpabet_phonemes = ipa_to_arpabet(ipa_phonemes)

        # 4. forced alignment：将 expected 与 actual 对齐并分配时间戳
        phone_segments = _align_with_timestamps(
            expected_phonemes, arpabet_phonemes, timeline, frame_confidences
        )

        # 5. word-level 时间戳
        words = _build_word_segments(word_boundaries or [], phone_segments)

        inference_ms = (time.perf_counter() - t0) * 1000

        return PhonemeDiagnostic(
            provider=self.kind,
            phonemes=phone_segments,
            words=words,
            audio_quality=quality,
            raw_phonemes=arpabet_phonemes,
            timeline=timeline,
            blank_segments=result["blank_segments"],
            total_duration=result["total_duration"],
            inference_ms=inference_ms,
            model_name=f"wav2vec2-xls-r-300m-timit-phoneme INT8 ({mode.value})",
            mode=mode,
            extra={
                "sample_rate": sample_rate,
                "num_frames": result.get("num_frames", 0),
                "ipa_phonemes": ipa_phonemes,
                "arpabet_phonemes": arpabet_phonemes,
            },
        )


# ============================================================
# 音频质量检测
# ============================================================
def _detect_audio_quality(audio: np.ndarray, sr: int) -> AudioQualityReport:
    """检测音频质量：SNR、削峰、静音比例、峰值/RMS dBFS。"""
    if audio.size == 0:
        return AudioQualityReport(is_too_quiet=True, warning="空音频")

    audio_f = audio.astype(np.float64)
    peak = float(np.max(np.abs(audio_f)))
    rms = float(np.sqrt(np.mean(audio_f ** 2)) + 1e-12)

    # dBFS
    peak_dbfs = 20 * np.log10(peak + 1e-12)
    rms_dbfs = 20 * np.log10(rms + 1e-12)

    # 削峰：超过 0.99 的样本比例
    clipping_ratio = float(np.mean(np.abs(audio_f) > 0.99))
    is_clipped = clipping_ratio > 0.01

    # 静音比例：RMS < -50 dBFS 的帧
    frame_len = int(sr * 0.02)  # 20ms
    if frame_len > 0 and len(audio_f) >= frame_len:
        n_frames = len(audio_f) // frame_len
        frames = audio_f[: n_frames * frame_len].reshape(n_frames, frame_len)
        frame_rms = np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-12
        frame_db = 20 * np.log10(frame_rms)
        silence_ratio = float(np.mean(frame_db < -50))
    else:
        silence_ratio = 0.0

    # SNR 估计：用最高 10% RMS 与最低 10% RMS 之比
    if frame_len > 0 and len(audio_f) >= frame_len:
        sorted_db = np.sort(frame_db)
        if len(sorted_db) >= 10:
            noise_floor = np.mean(sorted_db[: max(1, len(sorted_db) // 10)])
            signal_level = np.mean(sorted_db[-max(1, len(sorted_db) // 10):])
            snr_db = float(signal_level - noise_floor)
        else:
            snr_db = 0.0
    else:
        snr_db = 0.0

    is_too_quiet = rms_dbfs < -35
    is_too_noisy = snr_db < 10

    warnings = []
    if is_clipped:
        warnings.append("音频削峰，请降低录音音量")
    if is_too_quiet:
        warnings.append("音量过低，请靠近麦克风")
    if is_too_noisy:
        warnings.append("环境噪声过大，请到安静场所")
    if silence_ratio > 0.6:
        warnings.append("静音比例过高，请确认麦克风正常")

    return AudioQualityReport(
        snr_db=round(snr_db, 2),
        clipping_ratio=round(clipping_ratio, 4),
        silence_ratio=round(silence_ratio, 4),
        peak_dbfs=round(peak_dbfs, 2),
        rms_dbfs=round(rms_dbfs, 2),
        is_too_noisy=is_too_noisy,
        is_clipped=is_clipped,
        is_too_quiet=is_too_quiet,
        warning="; ".join(warnings),
    )


# ============================================================
# 带时间戳的音素对齐
# ============================================================
def _align_with_timestamps(
    expected: List[str],
    actual: List[str],
    timeline: List[dict],
    frame_confidences: List[float],
) -> List[PhoneSegment]:
    """DP 对齐 + 时间戳分配。

    返回每个 expected 音素对应的 PhoneSegment：
    - match: expected == actual，时间戳来自 actual timeline
    - substitution: expected != actual，时间戳来自 actual timeline
    - deletion: expected 漏读，无时间戳
    - insertion: actual 多读（不对应 expected）
    """
    from scoring import align_phonemes
    from phoneme_data import SIMILARITY_FUNC

    if not expected:
        return []

    alignment, _ = align_phonemes(expected, actual)

    # 把 timeline 索引到 actual 序列（去重后的音素）
    # timeline 与 actual 顺序应一致（都是 CTC 解码结果）
    segments: List[PhoneSegment] = []
    actual_idx = 0
    expected_idx = 0

    for exp, act in alignment:
        if exp is not None and act is not None:
            # 取对应 actual 的时间戳
            ts = timeline[actual_idx] if actual_idx < len(timeline) else {}
            conf = ts.get("confidence", 0.8)
            if exp == act:
                et = "match"
                score = 1.0
            else:
                et = "substitution"
                score = SIMILARITY_FUNC(exp, act)
            segments.append(
                PhoneSegment(
                    expected_phone=exp,
                    recognized_phone=act,
                    score=round(score, 3),
                    confidence=round(conf, 3),
                    start_time=ts.get("start_time", 0.0),
                    end_time=ts.get("end_time", 0.0),
                    error_type=et,
                    word_index=-1,
                )
            )
            actual_idx += 1
            expected_idx += 1
        elif exp is not None and act is None:
            segments.append(
                PhoneSegment(
                    expected_phone=exp,
                    recognized_phone=None,
                    score=0.0,
                    confidence=0.0,
                    start_time=0.0,
                    end_time=0.0,
                    error_type="deletion",
                    word_index=-1,
                )
            )
            expected_idx += 1
        elif exp is None and act is not None:
            ts = timeline[actual_idx] if actual_idx < len(timeline) else {}
            segments.append(
                PhoneSegment(
                    expected_phone="",
                    recognized_phone=act,
                    score=0.0,
                    confidence=round(ts.get("confidence", 0.5), 3),
                    start_time=ts.get("start_time", 0.0),
                    end_time=ts.get("end_time", 0.0),
                    error_type="insertion",
                    word_index=-1,
                )
            )
            actual_idx += 1

    return segments


def _build_word_segments(
    word_boundaries: List[dict],
    phone_segments: List[PhoneSegment],
) -> List[WordSegment]:
    """根据 word_boundaries 把 phone_segments 分组到单词。"""
    if not word_boundaries:
        return []

    words: List[WordSegment] = []
    offset = 0
    for wb in word_boundaries:
        word = wb.get("word", "")
        phonemes = wb.get("phonemes", [])
        n = len(phonemes)
        # 取该词范围内的 phone_segments（按 expected 索引）
        word_phones = [p for p in phone_segments if offset <= _expected_index(p, phone_segments) < offset + n]
        # 简化：直接按 expected_phone 在 phonemes 列表中切片
        # 更稳健的做法是用 word_index 字段，由上层评分器填充
        accuracy = _compute_word_accuracy(word_phones)
        words.append(
            WordSegment(
                word=word,
                start_time=word_phones[0].start_time if word_phones else 0.0,
                end_time=word_phones[-1].end_time if word_phones else 0.0,
                phonemes=word_phones,
                accuracy=accuracy,
            )
        )
        offset += n
    return words


def _expected_index(p: PhoneSegment, all_phones: List[PhoneSegment]) -> int:
    """返回 p 在所有 expected 音素中的索引。"""
    return all_phones.index(p)


def _compute_word_accuracy(phones: List[PhoneSegment]) -> float:
    if not phones:
        return 0.0
    correct = sum(1 for p in phones if p.error_type == "match")
    return round(correct / len(phones) * 100, 1)
