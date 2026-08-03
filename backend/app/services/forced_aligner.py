"""强制对齐服务：将文本与音频对齐到音素/单词级时间戳。

策略优先级：
1. ctc_segmentation（CTC 输出 + DP 对齐，纯 Python，无外部依赖）
2. whisperx（基于 faster-whisper + wav2vec2，需联网下载模型）
3. mfa（Montreal Forced Aligner，需独立安装，最准但最重）

默认使用 ctc_segmentation（本地、零依赖）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from ..core.config import get_settings
from ..core.logging import get_logger
from .pronunciation_provider import PhoneSegment


logger = get_logger("aligner")


@dataclass
class WordAlignment:
    word: str
    start: float
    end: float
    score: float
    phonemes: List[dict]  # {phone, start, end, score}


@dataclass
class AlignmentResult:
    words: List[WordAlignment]
    phonemes: List[dict]
    method: str
    total_duration: float


class CTCAlignmentService:
    """CTC segmentation 强制对齐。

    利用 HuPER 模型的 CTC 输出（帧级 logits）+ DP 对齐文本音素序列。
    """

    def __init__(self):
        self._available = True  # 纯 Python 实现

    @property
    def available(self) -> bool:
        return self._available

    def align(
        self,
        logits: np.ndarray,  # [T, V] CTC logits
        expected_phonemes: List[str],
        frame_duration: float,
        word_boundaries: Optional[List[dict]] = None,
    ) -> AlignmentResult:
        """对齐 expected_phonemes 到 CTC 帧序列。

        使用 Viterbi 风格的 DP：每帧选择最可能的音素，约束为 expected_phonemes 序列。
        """
        from phoneme_data import VOCAB, BLANK_ID

        T, V = logits.shape
        N = len(expected_phonemes)
        if N == 0 or T == 0:
            return AlignmentResult([], [], "ctc_segmentation", 0.0)

        # softmax
        probs = _softmax(logits)

        # DP: dp[i, t] = 对齐到 expected[i] 在帧 t 结束的最大概率
        # 转移：dp[i, t] = max(
        #   dp[i, t-1] * p(blank|t)  # 重复当前音素
        #   dp[i-1, t-1] * p(phoneme_i | t)  # 切换到下一个音素
        # )
        # 起始：dp[0, 0] = p(phoneme_0 | 0)
        # 用 log prob 避免下溢

        log_probs = np.log(probs + 1e-12)
        blank_logp = log_probs[:, BLANK_ID]  # [T]

        # 每个音素在每帧的 log prob
        phone_logp = np.zeros((N, T))
        for i, ph in enumerate(expected_phonemes):
            pid = VOCAB.get(ph, 1)  # UNK
            phone_logp[i] = log_probs[:, pid]

        NEG_INF = -1e18
        dp = np.full((N, T), NEG_INF, dtype=np.float64)
        back = np.zeros((N, T), dtype=np.int8)  # 0=stay, 1=advance

        # 初始化
        dp[0, 0] = phone_logp[0, 0]
        for t in range(1, T):
            # 停留在 phoneme 0
            dp[0, t] = dp[0, t - 1] + blank_logp[t]
            back[0, t] = 0
            # 实际上 phoneme 0 也可以在帧 t 出现
            alt = dp[0, t - 1] + phone_logp[0, t]
            if alt > dp[0, t]:
                dp[0, t] = alt
                back[0, t] = 0

        for i in range(1, N):
            for t in range(1, T):
                # 选项 1: 停留在 phoneme i，帧 t 是 blank
                stay = dp[i, t - 1] + blank_logp[t]
                # 选项 2: 从 i-1 推进到 i，帧 t 是 phoneme i
                advance = dp[i - 1, t - 1] + phone_logp[i, t]
                if stay >= advance:
                    dp[i, t] = stay
                    back[i, t] = 0
                else:
                    dp[i, t] = advance
                    back[i, t] = 1

        # 回溯
        phone_segments: List[dict] = []
        i, t = N - 1, T - 1
        current_start = t
        while i >= 0 and t >= 0:
            if i == 0 and t == 0:
                break
            if back[i, t] == 1:
                # 推进到 i 时，帧 t 是 phoneme i 的最后一帧
                phone_segments.append(
                    {
                        "phone": expected_phonemes[i],
                        "start_frame": t,
                        "end_frame": current_start + 1,
                        "start_time": round(t * frame_duration, 3),
                        "end_time": round((current_start + 1) * frame_duration, 3),
                        "score": round(float(np.exp(phone_logp[i, t])), 3),
                    }
                )
                i -= 1
                current_start = t - 1
            else:
                t -= 1
        # 处理 i=0
        if i == 0:
            phone_segments.append(
                {
                    "phone": expected_phonemes[0],
                    "start_frame": 0,
                    "end_frame": current_start + 1,
                    "start_time": 0.0,
                    "end_time": round((current_start + 1) * frame_duration, 3),
                    "score": round(float(np.exp(phone_logp[0, 0])), 3),
                }
            )

        phone_segments.reverse()

        # 聚合到 word-level
        word_alignments = _aggregate_words(word_boundaries or [], phone_segments, frame_duration)

        return AlignmentResult(
            words=word_alignments,
            phonemes=phone_segments,
            method="ctc_segmentation",
            total_duration=round(T * frame_duration, 3),
        )


def _softmax(logits: np.ndarray) -> np.ndarray:
    x = logits - np.max(logits, axis=-1, keepdims=True)
    e = np.exp(x)
    return e / np.sum(e, axis=-1, keepdims=True)


def _aggregate_words(
    word_boundaries: List[dict],
    phone_segments: List[dict],
    frame_duration: float,
) -> List[WordAlignment]:
    words: List[WordAlignment] = []
    offset = 0
    for wb in word_boundaries:
        word = wb.get("word", "")
        phonemes = wb.get("phonemes", [])
        n = len(phonemes)
        word_phones = phone_segments[offset : offset + n]
        if not word_phones:
            continue
        start = word_phones[0]["start_time"]
        end = word_phones[-1]["end_time"]
        score = float(np.mean([p["score"] for p in word_phones])) if word_phones else 0.0
        words.append(
            WordAlignment(
                word=word,
                start=start,
                end=end,
                score=round(score, 3),
                phonemes=word_phones,
            )
        )
        offset += n
    return words


_aligner_instance: Optional[CTCAlignmentService] = None


def get_aligner() -> CTCAlignmentService:
    global _aligner_instance
    if _aligner_instance is None:
        _aligner_instance = CTCAlignmentService()
    return _aligner_instance
