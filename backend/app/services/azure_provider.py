"""Azure Pronunciation Assessment Provider。

特性：
- 调用 Azure Speech Service 的 Pronunciation Assessment API
- 需用户提供 subscription key 和 region
- 默认关闭，仅在 .env 中 enable_azure_pronunciation=true 时启用
- 联网服务，音频会上传到 Azure
- 输出统一映射到 PhonemeDiagnostic

许可证：Azure Speech Service（商业，按调用计费）
隐私：调用时音频会上传到 Azure 云端，需在 UI 明确告知用户
回退：失败时本地 HuPER 仍可用
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np

from ..core.logging import get_logger
from .pronunciation_provider import (
    AudioQualityReport,
    ModelMode,
    PhoneSegment,
    PhonemeDiagnostic,
    ProviderKind,
    PronunciationProvider,
    WordSegment,
)


logger = get_logger("azure_provider")


class AzurePronunciationProvider(PronunciationProvider):
    """Azure 发音评估 Provider。

    需要：azure-cognitiveservices-speech SDK
    安装：pip install azure-cognitiveservices-speech
    """

    kind = ProviderKind.AZURE
    requires_network = True
    requires_api_key = True
    is_enabled_by_default = False

    def __init__(self, key: str, region: str):
        self.key = key
        self.region = region
        self._sdk = None
        self._available = False
        try:
            import azure.cognitiveservices.speech as speechsdk  # noqa: F401

            self._available = True
        except ImportError:
            logger.warning("azure_sdk_missing", msg="pip install azure-cognitiveservices-speech")

    def is_available(self) -> bool:
        return self._available and bool(self.key)

    def diagnose(
        self,
        audio: np.ndarray,
        sample_rate: int,
        expected_phonemes: List[str],
        word_boundaries: Optional[List[dict]] = None,
        mode: ModelMode = ModelMode.BALANCED,
    ) -> PhonemeDiagnostic:
        """调用 Azure Pronunciation Assessment。

        实际实现需：
        1. 将音频保存为 wav 临时文件
        2. 构造 PronunciationAssessmentConfig
        3. 调用 SpeechRecognizer.recognize_once
        4. 解析详细评分结果
        """
        if not self.is_available():
            raise RuntimeError("Azure provider not available")

        import azure.cognitiveservices.speech as speechsdk
        import tempfile
        import os
        import time

        t0 = time.perf_counter()

        # 1. 保存音频到临时文件
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name
        _save_wav(audio, sample_rate, temp_path)

        try:
            # 2. 配置
            speech_config = speechsdk.SpeechConfig(
                subscription=self.key, region=self.region
            )
            audio_config = speechsdk.audio.AudioConfig(filename=temp_path)

            # 3. 评估配置
            reference_text = " ".join(
                [wb["word"] for wb in (word_boundaries or [])]
            )
            pronunciation_config = speechsdk.PronunciationAssessmentConfig(
                reference_text=reference_text,
                grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
                granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
            )

            # 4. 识别
            recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config, audio_config=audio_config
            )
            pronunciation_config.apply_to(recognizer)

            result = recognizer.recognize_once()

            # 5. 解析
            pronunciation_result = speechsdk.PronunciationAssessmentResult(result)
            detail = result.properties.get(
                speechsdk.PropertyId.SpeechServiceResponse_JsonResult
            )

            inference_ms = (time.perf_counter() - t0) * 1000

            phone_segments, word_segments = self._parse_azure_detail(detail, expected_phonemes)

            return PhonemeDiagnostic(
                provider=self.kind,
                phonemes=phone_segments,
                words=word_segments,
                audio_quality=AudioQualityReport(),  # Azure 不提供音质检测
                raw_phonemes=[p.expected_phone for p in phone_segments],
                total_duration=float(len(audio)) / sample_rate,
                inference_ms=inference_ms,
                model_name="azure_pronunciation",
                mode=mode,
                extra={
                    "accuracy_score": pronunciation_result.accuracy_score,
                    "fluency_score": pronunciation_result.fluency_score,
                    "completeness_score": pronunciation_result.completeness_score,
                    "prosody_score": pronunciation_result.prosody_score,
                },
            )
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    def _parse_azure_detail(self, detail_json: str, expected_phonemes: List[str]):
        """解析 Azure 返回的 JSON 详情。"""
        import json

        if not detail_json:
            return [], []
        try:
            data = json.loads(detail_json)
        except json.JSONDecodeError:
            return [], []

        phone_segments: List[PhoneSegment] = []
        word_segments: List[WordSegment] = []

        for w in data.get("NBest", []):
            word = w.get("Word", "")
            w_start = w.get("Offset", 0) / 1e7  # Azure offset 单位是 100ns
            w_duration = w.get("Duration", 0) / 1e7
            w_end = w_start + w_duration
            w_phones: List[PhoneSegment] = []
            for p in w.get("Phonemes", []):
                ph = p.get("Phoneme", "").upper()
                p_start = p.get("Offset", 0) / 1e7
                p_duration = p.get("Duration", 0) / 1e7
                p_score = p.get("PronunciationAssessment", {}).get("AccuracyScore", 50)
                phone_segments.append(
                    PhoneSegment(
                        expected_phone=ph,
                        recognized_phone=ph,
                        score=round(p_score / 100, 3),
                        confidence=1.0,
                        start_time=round(p_start, 3),
                        end_time=round(p_start + p_duration, 3),
                        error_type="match" if p_score >= 80 else "substitution",
                    )
                )
                w_phones.append(phone_segments[-1])
            word_segments.append(
                WordSegment(
                    word=word,
                    start_time=round(w_start, 3),
                    end_time=round(w_end, 3),
                    phonemes=w_phones,
                    accuracy=round(w.get("PronunciationAssessment", {}).get("AccuracyScore", 50), 1),
                )
            )
        return phone_segments, word_segments


def _save_wav(audio: np.ndarray, sample_rate: int, path: str) -> None:
    import soundfile as sf

    sf.write(path, audio.astype(np.float32), sample_rate)
