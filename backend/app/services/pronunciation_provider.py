"""发音诊断 Provider 抽象接口。

设计目标：
- 本地 HuPER 始终可用
- 商业 API（Azure/讯飞/有道）默认关闭，用户配置后才启用
- 统一返回 PhonemeDiagnostic 结构
- 支持高精度/平衡/低延迟三档
- 可缓存、可校验
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import numpy as np


class ModelMode(str, Enum):
    HIGH_PRECISION = "high_precision"
    BALANCED = "balanced"
    LOW_LATENCY = "low_latency"


class ProviderKind(str, Enum):
    LOCAL_HUPER = "local_huper"
    AZURE = "azure"
    XFYUN = "xfyun"
    YOUDAO = "youdao"
    MOCK = "mock"


@dataclass
class PhoneSegment:
    """单音素对齐结果。"""
    expected_phone: str
    recognized_phone: Optional[str]
    score: float  # 0-1，模型置信度或相似度
    confidence: float  # 0-1，模型预测置信度（来自 softmax）
    start_time: float  # 秒
    end_time: float
    error_type: str = "match"  # match/substitution/deletion/insertion/...
    word_index: int = -1
    suggestion: str = ""


@dataclass
class WordSegment:
    word: str
    start_time: float
    end_time: float
    phonemes: List[PhoneSegment]
    accuracy: float = 0.0


@dataclass
class AudioQualityReport:
    snr_db: float = 0.0
    clipping_ratio: float = 0.0
    silence_ratio: float = 0.0
    peak_dbfs: float = 0.0
    rms_dbfs: float = 0.0
    is_too_noisy: bool = False
    is_clipped: bool = False
    is_too_quiet: bool = False
    warning: str = ""


@dataclass
class PhonemeDiagnostic:
    """统一发音诊断输出（所有 Provider 实现此接口）。"""
    provider: ProviderKind
    phonemes: List[PhoneSegment]
    words: List[WordSegment]
    audio_quality: AudioQualityReport
    raw_phonemes: List[str]  # CTC 解码后的原始音素序列
    timeline: List[dict] = field(default_factory=list)
    blank_segments: List[dict] = field(default_factory=list)
    total_duration: float = 0.0
    inference_ms: float = 0.0
    model_name: str = ""
    mode: ModelMode = ModelMode.BALANCED
    extra: dict = field(default_factory=dict)


class PronunciationProvider(abc.ABC):
    """发音诊断 Provider 抽象。"""

    kind: ProviderKind = ProviderKind.LOCAL_HUPER
    requires_network: bool = False
    requires_api_key: bool = False
    is_enabled_by_default: bool = False

    @abc.abstractmethod
    def diagnose(
        self,
        audio: np.ndarray,
        sample_rate: int,
        expected_phonemes: List[str],
        word_boundaries: Optional[List[dict]] = None,
        mode: ModelMode = ModelMode.BALANCED,
    ) -> PhonemeDiagnostic:
        """诊断发音。"""

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Provider 是否可用（模型已加载、API key 已配置）。"""

    def health(self) -> dict:
        return {
            "provider": self.kind.value,
            "available": self.is_available(),
            "requires_network": self.requires_network,
            "requires_api_key": self.requires_api_key,
        }


class ProviderRegistry:
    """Provider 注册表，按优先级选择。"""

    def __init__(self):
        self._providers: dict[ProviderKind, PronunciationProvider] = {}
        self._priority: list[ProviderKind] = []

    def register(self, provider: PronunciationProvider, priority: int = 0) -> None:
        self._providers[provider.kind] = provider
        self._priority.append(provider.kind)
        self._priority.sort(key=lambda k: priority, reverse=True)

    def get(self, kind: ProviderKind) -> Optional[PronunciationProvider]:
        return self._providers.get(kind)

    def get_available(self, preferred: Optional[ProviderKind] = None) -> Optional[PronunciationProvider]:
        if preferred and preferred in self._providers:
            p = self._providers[preferred]
            if p.is_available():
                return p
        for kind in self._priority:
            p = self._providers[kind]
            if p.is_available():
                return p
        return None

    def list_providers(self) -> List[dict]:
        return [
            {
                "kind": p.kind.value,
                "available": p.is_available(),
                "requires_network": p.requires_network,
                "requires_api_key": p.requires_api_key,
                "enabled_by_default": p.is_enabled_by_default,
            }
            for p in self._providers.values()
        ]


_registry = ProviderRegistry()


def get_provider_registry() -> ProviderRegistry:
    return _registry


def register_default_providers() -> None:
    """注册默认 Provider 集合（本地优先）。"""
    from ..core.config import get_settings
    from ..core.logging import get_logger

    logger = get_logger("providers")
    settings = get_settings()

    # 1. 本地 HuPER（始终注册，优先级最高）
    try:
        from .local_huper_provider import LocalHuPERProvider

        path = settings.effective_huper_model_path()
        if path:
            _registry.register(LocalHuPERProvider(model_path=path), priority=100)
            logger.info("provider_registered", provider="local_huper", path=path)
        else:
            logger.warning("provider_register_failed", provider="local_huper", reason="model_not_found")
    except Exception as e:
        logger.error("provider_register_error", provider="local_huper", error=str(e))

    # 2. 商业 API（默认关闭）
    if settings.enable_azure_pronunciation and settings.azure_speech_key:
        try:
            from .azure_provider import AzurePronunciationProvider

            _registry.register(
                AzurePronunciationProvider(
                    key=settings.azure_speech_key,
                    region=settings.azure_speech_region,
                ),
                priority=50,
            )
            logger.info("provider_registered", provider="azure")
        except Exception as e:
            logger.error("provider_register_error", provider="azure", error=str(e))

    if settings.enable_xfyun_ise and settings.xfyun_app_id:
        try:
            from .xfyun_provider import XfyunISEProvider

            _registry.register(
                XfyunISEProvider(
                    app_id=settings.xfyun_app_id,
                    api_key=settings.xfyun_api_key,
                    api_secret=settings.xfyun_api_secret,
                ),
                priority=40,
            )
            logger.info("provider_registered", provider="xfyun")
        except Exception as e:
            logger.error("provider_register_error", provider="xfyun", error=str(e))

    if settings.enable_youdao and settings.youdao_app_key:
        try:
            from .youdao_provider import YoudaoPronunciationProvider

            _registry.register(
                YoudaoPronunciationProvider(
                    app_key=settings.youdao_app_key,
                    app_secret=settings.youdao_app_secret,
                ),
                priority=30,
            )
            logger.info("provider_registered", provider="youdao")
        except Exception as e:
            logger.error("provider_register_error", provider="youdao", error=str(e))
