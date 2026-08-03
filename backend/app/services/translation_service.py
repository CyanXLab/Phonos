"""英译中服务（本地 opus-mt-en-zh，无需联网）。

模型：Helsinki-NLP/opus-mt-en-zh
- 许可证：CC BY 4.0（模型）+ Apache 2.0（代码）
- 大小：约 300MB（PyTorch）
- 离线运行

替代方案：
- 在线 ModelScope LLM 翻译（如已配置 API key）
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..core.config import get_settings
from ..core.logging import get_logger


logger = get_logger("translator")


class TranslationService:
    """英译中服务（本地 opus-mt）。"""

    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._available = False
        self._load_attempted = False

    @property
    def available(self) -> bool:
        if not self._load_attempted:
            self._try_load()
        return self._available

    def _try_load(self) -> None:
        self._load_attempted = True
        settings = get_settings()
        model_dir = Path(settings.models_dir) / "opus_mt_en_zh"
        if not model_dir.exists():
            logger.info("translator_model_missing", path=str(model_dir))
            return

        try:
            from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
            import torch

            self._tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
            self._model = AutoModelForSeq2SeqLM.from_pretrained(str(model_dir))
            self._model.eval()
            self._available = True
            logger.info("translator_loaded", path=str(model_dir))
        except Exception as e:
            logger.warning("translator_load_failed", error=str(e))

    def translate(self, text: str, src_lang: str = "en", tgt_lang: str = "zh") -> str:
        """英译中。"""
        if not self.available:
            # 回退到在线 API
            return self._translate_online(text)

        try:
            import torch

            inputs = self._tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
            with torch.no_grad():
                outputs = self._model.generate(**inputs, max_length=512, num_beams=4)
            result = self._tokenizer.decode(outputs[0], skip_special_tokens=True)
            return result
        except Exception as e:
            logger.error("translate_failed", error=str(e))
            return self._translate_online(text)

    def _translate_online(self, text: str) -> str:
        """回退：用旧版 Edge/MyMemory 在线翻译。"""
        try:
            from translate_service import translate_text as _legacy_translate
            return _legacy_translate(text)
        except Exception:
            return text  # 最终回退：返回原文


_translator_instance: Optional[TranslationService] = None


def get_translator() -> TranslationService:
    global _translator_instance
    if _translator_instance is None:
        _translator_instance = TranslationService()
    return _translator_instance
