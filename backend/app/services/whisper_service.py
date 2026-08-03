"""Faster-Whisper ASR 服务。

特性：
- small / medium / large-v3 模型切换
- int8 / int8_float16 / float16 / float32 量化
- 词级时间戳、句子分段、置信度
- 自动下载（首次）+ 本地缓存
- 默认关闭，按需启用

许可证：faster-whisper（MIT）+ Whisper 模型（MIT）
下载：首次自动从 HuggingFace 下载，约 75MB(small) ~ 1.5GB(large)
回退：本地 HuPER 仍可用作音素级回退
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from ..core.config import get_settings
from ..core.logging import get_logger


logger = get_logger("whisper")


@dataclass
class ASRSegment:
    text: str
    start: float
    end: float
    avg_logprob: float
    no_speech_prob: float
    words: List[dict]  # 每个词 {word, start, end, probability}


@dataclass
class ASRResult:
    text: str
    language: str
    segments: List[ASRSegment]
    duration: float
    model_size: str
    compute_type: str
    inference_ms: float


class FasterWhisperService:
    """faster-whisper 包装。"""

    def __init__(self):
        self._model = None
        self._available = False
        self._load_attempted = False
        self._model_size = ""
        self._compute_type = ""

    @property
    def available(self) -> bool:
        if not self._load_attempted:
            self._try_load()
        return self._available

    def _try_load(self) -> None:
        self._load_attempted = True
        settings = get_settings()
        if not settings.whisper_enabled:
            self._available = False
            return

        try:
            from faster_whisper import WhisperModel

            model_path = settings.effective_whisper_model_path()
            device = settings.whisper_device
            if device == "auto":
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"

            self._model = WhisperModel(
                settings.whisper_model_size,
                device=device,
                compute_type=settings.whisper_compute_type,
                download_root=model_path,
                cpu_threads=settings.whisper_cpu_threads,
                num_workers=settings.whisper_num_workers,
            )
            self._available = True
            self._model_size = settings.whisper_model_size
            self._compute_type = settings.whisper_compute_type
            logger.info(
                "whisper_loaded",
                model=settings.whisper_model_size,
                device=device,
                compute_type=settings.whisper_compute_type,
            )
        except ImportError:
            logger.warning("whisper_unavailable", msg="faster-whisper not installed")
        except Exception as e:
            logger.error("whisper_load_failed", error=str(e))

    def transcribe(
        self,
        audio_path: str,
        language: str = "en",
        word_timestamps: bool = True,
        beam_size: int = 5,
    ) -> ASRResult:
        """转录音频文件。"""
        import time as _time

        if not self.available:
            raise RuntimeError("Whisper 服务不可用")

        t0 = _time.perf_counter()
        segments_gen, info = self._model.transcribe(
            audio_path,
            language=language,
            word_timestamps=word_timestamps,
            beam_size=beam_size,
            vad_filter=True,
        )

        segments: List[ASRSegment] = []
        full_text_parts: List[str] = []
        for seg in segments_gen:
            words = []
            if word_timestamps and seg.words:
                for w in seg.words:
                    words.append(
                        {
                            "word": w.word,
                            "start": round(w.start, 3),
                            "end": round(w.end, 3),
                            "probability": round(w.probability, 3),
                        }
                    )
            segments.append(
                ASRSegment(
                    text=seg.text.strip(),
                    start=round(seg.start, 3),
                    end=round(seg.end, 3),
                    avg_logprob=round(seg.avg_logprob, 3),
                    no_speech_prob=round(seg.no_speech_prob, 3),
                    words=words,
                )
            )
            full_text_parts.append(seg.text.strip())

        inference_ms = (_time.perf_counter() - t0) * 1000

        return ASRResult(
            text=" ".join(full_text_parts),
            language=info.language,
            segments=segments,
            duration=round(info.duration, 2),
            model_size=self._model_size,
            compute_type=self._compute_type,
            inference_ms=round(inference_ms, 1),
        )

    def health(self) -> dict:
        return {
            "available": self.available,
            "model_size": self._model_size or get_settings().whisper_model_size,
            "compute_type": self._compute_type or get_settings().whisper_compute_type,
            "enabled": get_settings().whisper_enabled,
        }


_whisper_instance: Optional[FasterWhisperService] = None


def get_whisper_service() -> FasterWhisperService:
    global _whisper_instance
    if _whisper_instance is None:
        _whisper_instance = FasterWhisperService()
    return _whisper_instance
