"""
动态词典服务 - 使用 ENDICT 高频词 + 免费网络API回退

数据源优先级：
1. ENDICT common.json（5万高频词，延迟加载，含英美音标、释义、例句）
2. 免费网络翻译API（MyMemory等，查不到的词自动回退）
3. G2P 自动解析（生成音标）

优化点：
- 不加载完整词典(full_dict 136MB)，精简版足够
- common.json 延迟加载（首次查询时才读取）
- 网络API异步查询，不阻塞主流程
- 查询结果缓存，避免重复请求
"""

import json
import os
import re
import aiohttp
import asyncio
from pathlib import Path
from typing import Optional, Dict
from functools import lru_cache

_DATA_DIR = Path(__file__).parent
_DICT_DIR = _DATA_DIR / "dict"

# ENDICT 数据目录
_ENDICT_DIR = _DICT_DIR / "endict"
_ENDICT_COMMON = _ENDICT_DIR / "common.json"

_dict_instance = None

# Free translation API URLs
_MYMEMORY_API = "https://api.mymemory.translated.net/get"


class DictService:
    """动态词典查询服务（精简版 + 网络API回退）"""

    def __init__(self):
        self._endict_common: Dict = {}
        self._common_loaded = False
        self._common_available = False
        # 单词详情缓存（避免重复查询）
        self._lookup_cache: Dict = {}
        # 网络 API 缓存（已查询过的词不再重复请求）
        self._api_cache: Dict = {}
        # aiohttp session (lazy init)
        self._http_session: Optional[aiohttp.ClientSession] = None

        # 检查 ENDICT common.json
        if _ENDICT_COMMON.exists() and _ENDICT_COMMON.stat().st_size > 100:
            self._common_available = True
            print(f"[词典] ENDICT 高频词库可用: {_ENDICT_COMMON.name}")
        else:
            print("[词典] 未找到 ENDICT common.json，将使用网络API + G2P 解析")

    def _ensure_common(self):
        """延迟加载 ENDICT 高频词库（约14MB，首次查询时才加载）"""
        if self._common_loaded:
            return
        self._common_loaded = True
        if not self._common_available:
            return

        try:
            with open(_ENDICT_COMMON, "r", encoding="utf-8") as f:
                self._endict_common = json.load(f)
            print(f"[词典] ENDICT 高频词库加载完成: {len(self._endict_common)} 个词条")
        except Exception as e:
            print(f"[词典] ENDICT 高频词库加载失败: {e}")

    def lookup_endict(self, word: str) -> Optional[dict]:
        """从 ENDICT 本地数据查找单词（仅查高频词库）"""
        word_lower = word.lower()

        # 查高频词库
        self._ensure_common()
        data = self._endict_common.get(word_lower)

        if not data:
            return None

        result = {
            "word": data.get("word", word),
            "pos": data.get("pos", ""),
            "meaning": data.get("meaning", ""),
            "ipa_us": data.get("ipa_us", ""),
            "ipa_uk": data.get("ipa_uk", ""),
            "arpabet": [],
            "example": "",
            "examples": data.get("examples", []),
            "exchange": data.get("exchange", []),
            "source": "endict",
        }

        # 取第一个例句作为 example
        if result["examples"]:
            result["example"] = result["examples"][0]

        return result

    async def _lookup_web_api(self, word: str) -> Optional[dict]:
        """通过免费网络API查询单词翻译（异步，不阻塞）"""
        word_lower = word.lower()

        # 检查缓存
        if word_lower in self._api_cache:
            return self._api_cache[word_lower]

        try:
            if self._http_session is None:
                self._http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))

            # MyMemory 免费翻译API（无需key，每月1万次）
            url = f"{_MYMEMORY_API}?q={word}&langpair=en|zh"
            async with self._http_session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    translated = data.get("responseData", {}).get("translatedText", "")
                    if translated and translated.lower() != word_lower and translated != "NO QUERY SPECIFIED":
                        result = {
                            "word": word,
                            "pos": "",
                            "meaning": translated,
                            "ipa_us": "",
                            "ipa_uk": "",
                            "arpabet": [],
                            "example": "",
                            "examples": [],
                            "source": "web-api",
                        }
                        self._api_cache[word_lower] = result
                        return result
        except Exception:
            pass  # 网络 API 失败不阻塞，静默回退

        self._api_cache[word_lower] = None  # 标记已查过但无结果
        return None

    def lookup(self, word: str, local_only: bool = True) -> dict:
        """
        同步查询单词（仅本地数据，快速返回）

        参数:
            word: 要查询的单词
            local_only: 仅使用本地数据（默认True，避免阻塞）

        返回格式:
        {
            "word": str,
            "pos": str,        # 词性
            "meaning": str,     # 中文释义
            "ipa": str,        # 美式音标
            "ipa_us": str,     # 美式音标
            "ipa_uk": str,     # 英式音标
            "arpabet": list,    # ARPAbet音素
            "example": str,    # 例句
            "examples": list,  # 例句列表
            "source": str,     # 数据来源
        }
        """
        word_clean = re.sub(r'[^a-zA-Z\'-]', '', word.lower())
        if not word_clean:
            return {"word": word, "pos": "", "meaning": "", "ipa": "", "ipa_us": "", "ipa_uk": "",
                    "arpabet": [], "example": "", "examples": [], "source": "none"}

        # 检查缓存
        if word_clean in self._lookup_cache:
            return self._lookup_cache[word_clean]

        # 1. 尝试 ENDICT 本地数据
        result = self.lookup_endict(word_clean)
        if result and (result.get("meaning") or result.get("ipa_us")):
            self._lookup_cache[word_clean] = result
            return result

        # 2. G2P 自动解析（快速，本地）
        from g2p_service import get_g2p_service
        g2p = get_g2p_service()
        arpabet = g2p.text_to_phonemes(word_clean)
        ipa = g2p.arpabet_to_ipa(arpabet) if arpabet else ""

        result = {
            "word": word_clean,
            "pos": "",
            "meaning": "",
            "ipa": f"/{ipa}/" if ipa else "",
            "ipa_us": f"/{ipa}/" if ipa else "",
            "ipa_uk": "",
            "arpabet": arpabet,
            "example": "",
            "examples": [],
            "source": "g2p",
        }
        self._lookup_cache[word_clean] = result
        return result

    async def lookup_async(self, word: str) -> dict:
        """
        异步查询单词（本地 + 网络API回退）

        先查本地，如果本地没有翻译，再查网络API补充释义
        """
        # 先走同步查询（本地数据）
        result = self.lookup(word, local_only=True)

        # 如果本地没有翻译，尝试网络API
        if not result.get("meaning") and result.get("source") == "g2p":
            web_result = await self._lookup_web_api(word)
            if web_result and web_result.get("meaning"):
                # 合并网络API结果到本地结果（保留G2P生成的音标）
                result["meaning"] = web_result["meaning"]
                result["source"] = "g2p+web-api"
                # 更新缓存
                word_clean = re.sub(r'[^a-zA-Z\'-]', '', word.lower())
                self._lookup_cache[word_clean] = result

        return result

    async def close(self):
        """关闭HTTP会话"""
        if self._http_session:
            await self._http_session.close()
            self._http_session = None


def get_dict_service() -> DictService:
    global _dict_instance
    if _dict_instance is None:
        _dict_instance = DictService()
    return _dict_instance
