"""科大讯飞 ISE（口语评测）Provider 骨架。

许可证：讯飞 ISE（商业，按调用计费）
隐私：音频上传到讯飞云端
启用条件：enable_xfyun_ise=true + 配置 APP_ID/API_KEY/API_SECRET
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


logger = get_logger("xfyun_provider")


class XfyunISEProvider(PronunciationProvider):
    """讯飞 ISE 口语评测 Provider。

    SDK：使用 WebSocket 直连（不依赖讯飞 SDK，避免 GPL 污染）
    文档：https://www.xfyun.cn/doc/Ise/IseAPI.html
    """

    kind = ProviderKind.XFYUN
    requires_network = True
    requires_api_key = True
    is_enabled_by_default = False

    def __init__(self, app_id: str, api_key: str, api_secret: str):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self._available = bool(app_id and api_key and api_secret)

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
            raise RuntimeError("讯飞 ISE 未配置")

        # 简化实现骨架：实际需实现 WebSocket 协议
        # 1. 生成鉴权 URL（HMAC-SHA256）
        # 2. 建立 WebSocket 连接
        # 3. 分帧发送音频（每帧 1280 bytes）
        # 4. 接收评测结果 JSON
        # 5. 解析 phoneme/word 评分

        logger.warning("xfyun_ise_not_implemented", msg="骨架，需完成 WebSocket 实现")
        raise NotImplementedError("讯飞 ISE WebSocket 实现待完成")
