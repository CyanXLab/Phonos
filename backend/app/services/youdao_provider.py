"""有道智云口语评测 Provider 骨架。

许可证：有道智云（商业，按调用计费）
隐私：音频上传到有道云端
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


logger = get_logger("youdao_provider")


class YoudaoPronunciationProvider(PronunciationProvider):
    """有道智云口语评测 Provider。"""

    kind = ProviderKind.YOUDAO
    requires_network = True
    requires_api_key = True
    is_enabled_by_default = False

    def __init__(self, app_key: str, app_secret: str):
        self.app_key = app_key
        self.app_secret = app_secret
        self._available = bool(app_key and app_secret)

    def is_available(self) -> bool:
        return self._available

    def diagnose(
        self,
        audio: np.ndarray,
        sample_rate: int,
        expected_phonemes: List[str],
        word_boundaries: Optional[List[dict]] = None,
        mode: ModelMode = ModelMode.BALANCED,
    ) -> PhonemeDiagnostic:
        if not self.is_available():
            raise RuntimeError("有道智云未配置")
        logger.warning("youdao_not_implemented", msg="骨架，需完成 HTTP API 实现")
        raise NotImplementedError("有道智云 HTTP 实现待完成")
