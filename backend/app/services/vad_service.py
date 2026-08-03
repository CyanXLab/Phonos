"""Silero VAD 服务（语音活动检测）。

特性：
- 优先使用 silero-vad（ONNX，~2MB）
- 不可用时回退到能量阈值法
- 输出语音段、停顿段
- 用于：降噪前定位、流利度可靠停顿、音质检测

许可证：silero-vad 模型为 CC BY 4.0 / MIT（代码）
下载：首次使用自动从 silero CDN 下载，或预置到 models/silero_vad.onnx
回退：能量阈值法（无依赖）
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

from ..core.config import get_settings
from ..core.logging import get_logger


logger = get_logger("vad")


@dataclass
class VoiceSegment:
    start: float  # 秒
    end: float
    duration: float


@dataclass
class VADResult:
    speech_segments: List[VoiceSegment]
    silence_segments: List[VoiceSegment]
    total_speech_sec: float
    total_silence_sec: float
    speech_ratio: float
    method: str  # silero / energy


class SileroVADService:
    """Silero VAD 包装。"""

    def __init__(self):
        self._model = None
        self._available = False
        self._load_attempted = False
        self._method = "energy"  # 默认回退

    @property
    def available(self) -> bool:
        if not self._load_attempted:
            self._try_load()
        return self._available

    def _try_load(self) -> None:
        self._load_attempted = True
        settings = get_settings()
        try:
            import torch  # noqa: F401
            model_path = settings.vad_model_path or self._find_default_model()
            if model_path and os.path.isfile(model_path):
                import torch

                self._model = torch.hub.load(
                    repo_or_dir="snakers4/silero-vad",
                    model="silero_vad",
                    source="local",
                    force_reload=False,
                ) if False else self._load_from_file(model_path)
                self._available = True
                self._method = "silero"
                logger.info("vad_loaded", method="silero", path=model_path)
                return

            # 尝试在线下载（首次）
            try:
                import torch

                self._model = torch.hub.load(
                    repo_or_dir="snakers4/silero-vad",
                    model="silero_vad",
                    trust_repo=True,
                )
                self._available = True
                self._method = "silero"
                logger.info("vad_loaded_online", method="silero")
                return
            except Exception as e:
                logger.warning("vad_load_online_failed", error=str(e))

        except ImportError:
            logger.warning("vad_torch_unavailable", msg="silero-vad needs torch; falling back to energy")
        except Exception as e:
            logger.warning("vad_load_failed", error=str(e))

        self._available = False
        self._method = "energy"

    def _find_default_model(self) -> str:
        candidates = [
            Path(get_settings().models_dir) / "silero_vad.onnx",
            Path(get_settings().models_dir) / "silero" / "silero_vad.onnx",
        ]
        for p in candidates:
            if p.is_file():
                return str(p)
        return ""

    def _load_from_file(self, model_path: str):
        """从本地 ONNX 文件加载 silero-vad（不依赖 torch hub）。"""
        try:
            import onnxruntime as ort

            sess = ort.InferenceSession(
                model_path,
                providers=["CPUExecutionProvider"],
            )
            return {"session": sess, "type": "onnx"}
        except Exception as e:
            logger.warning("vad_onnx_load_failed", error=str(e))
            return None

    def detect(self, audio: np.ndarray, sample_rate: int = 16000) -> VADResult:
        """检测语音段与静音段。"""
        if self.available and self._method == "silero" and self._model is not None:
            try:
                return self._detect_silero(audio, sample_rate)
            except Exception as e:
                logger.warning("vad_silero_error", error=str(e), fallback="energy")

        return self._detect_energy(audio, sample_rate)

    def _detect_silero(self, audio: np.ndarray, sample_rate: int) -> VADResult:
        """使用 silero-vad 检测。"""
        # 简化实现：调用 torch hub 模型
        # 完整实现需要 chunked 推理 + 阈值后处理
        # 这里给出可工作的最小实现
        import torch

        settings = get_settings()
        threshold = settings.vad_threshold
        min_speech = settings.vad_min_speech_duration_ms
        min_silence = settings.vad_min_silence_duration_ms
        speech_pad = settings.vad_speech_pad_ms

        wav = torch.from_numpy(audio.astype(np.float32))
        if wav.dim() > 1:
            wav = wav.mean(dim=-1)

        # silero-vad 期望 16kHz
        if sample_rate != 16000:
            import torchaudio

            wav = torchaudio.functional.resample(wav, sample_rate, 16000)
            sample_rate = 16000

        # 滑窗预测
        window = 512  # silero v4
        speech_probs = []
        for i in range(0, len(wav) - window, window):
            chunk = wav[i : i + window]
            with torch.no_grad():
                p = self._model(chunk, sample_rate).item()
            speech_probs.append(p)

        # 阈值化
        is_speech = [p > threshold for p in speech_probs]
        return self._postprocess(
            is_speech, len(wav), sample_rate, window,
            min_speech, min_silence, speech_pad,
        )

    def _detect_energy(self, audio: np.ndarray, sample_rate: int) -> VADResult:
        """能量阈值法回退。"""
        frame_len = int(sample_rate * 0.02)  # 20ms
        if len(audio) < frame_len:
            return VADResult([], [], 0.0, 0.0, 0.0, "energy")

        n_frames = len(audio) // frame_len
        frames = audio[: n_frames * frame_len].reshape(n_frames, frame_len).astype(np.float64)
        rms = np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-12
        db = 20 * np.log10(rms)

        # 自适应阈值：噪声 floor + 10dB
        noise_floor = np.percentile(db, 20)
        threshold = noise_floor + 10

        is_speech = db > threshold
        window_sec = frame_len / sample_rate * 1000  # ms

        return self._postprocess(
            is_speech.tolist(), len(audio), sample_rate, frame_len,
            250, 100, 30,
        )

    def _postprocess(
        self,
        is_speech: List[bool],
        total_samples: int,
        sample_rate: int,
        window: int,
        min_speech_ms: int,
        min_silence_ms: int,
        speech_pad_ms: int,
    ) -> VADResult:
        """后处理：合并相邻段、过滤过短段、添加 padding。"""
        min_speech_frames = max(1, int(min_speech_ms / (window / sample_rate * 1000)))
        min_silence_frames = max(1, int(min_silence_ms / (window / sample_rate * 1000)))
        pad_samples = int(speech_pad_ms / 1000 * sample_rate)

        # 找连续语音段
        segments: List[tuple[int, int]] = []
        in_speech = False
        start = 0
        for i, s in enumerate(is_speech):
            if s and not in_speech:
                start = i
                in_speech = True
            elif not s and in_speech:
                end = i
                if end - start >= min_speech_frames:
                    segments.append((start, end))
                in_speech = False
        if in_speech:
            segments.append((start, len(is_speech)))

        # 转 VoiceSegment
        speech_segments: List[VoiceSegment] = []
        for s_idx, e_idx in segments:
            s_sample = max(0, s_idx * window - pad_samples)
            e_sample = min(total_samples, e_idx * window + pad_samples)
            start_sec = s_sample / sample_rate
            end_sec = e_sample / sample_rate
            speech_segments.append(
                VoiceSegment(
                    start=round(start_sec, 3),
                    end=round(end_sec, 3),
                    duration=round(end_sec - start_sec, 3),
                )
            )

        # 静音段（语音段之间的间隔）
        silence_segments: List[VoiceSegment] = []
        prev_end = 0.0
        for seg in speech_segments:
            if seg.start > prev_end:
                dur = seg.start - prev_end
                if dur >= min_silence_ms / 1000:
                    silence_segments.append(
                        VoiceSegment(
                            start=round(prev_end, 3),
                            end=round(seg.start, 3),
                            duration=round(dur, 3),
                        )
                    )
            prev_end = seg.end
        if prev_end < total_samples / sample_rate:
            dur = total_samples / sample_rate - prev_end
            if dur >= min_silence_ms / 1000:
                silence_segments.append(
                    VoiceSegment(
                        start=round(prev_end, 3),
                        end=round(total_samples / sample_rate, 3),
                        duration=round(dur, 3),
                    )
                )

        total_speech = sum(s.duration for s in speech_segments)
        total_silence = sum(s.duration for s in silence_segments)
        total = total_speech + total_silence
        speech_ratio = total_speech / total if total > 0 else 0.0

        return VADResult(
            speech_segments=speech_segments,
            silence_segments=silence_segments,
            total_speech_sec=round(total_speech, 3),
            total_silence_sec=round(total_silence, 3),
            speech_ratio=round(speech_ratio, 3),
            method=self._method,
        )


_vad_instance: Optional[SileroVADService] = None


def get_vad_service() -> SileroVADService:
    global _vad_instance
    if _vad_instance is None:
        _vad_instance = SileroVADService()
    return _vad_instance
