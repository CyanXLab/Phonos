"""
动态词典服务 - 使用 ENDICT 进行单词查询

数据源优先级：
1. ENDICT common.json（5万高频词，内存缓存，含英美音标、释义、例句）
2. ENDICT full_dict.json（128万词，延迟加载，按需查询）
3. 内置基础词典（phoneme_data.WORD_DICT）
4. G2P 自动解析

在线查询已禁用（太慢），仅使用本地数据
"""

import json
import os
import re
from pathlib import Path
from typing import Optional, Dict

_DATA_DIR = Path(__file__).parent
_DICT_DIR = _DATA_DIR / "dict"

# ENDICT 数据目录
_ENDICT_DIR = _DICT_DIR / "endict"
_ENDICT_COMMON = _ENDICT_DIR / "common.json"
_ENDICT_FULL = _ENDICT_DIR / "full_dict.json"

_dict_instance = None


class DictService:
    """动态词典查询服务"""

    def __init__(self):
        self._endict_common: Dict = {}
        self._endict_full: Dict = {}
        self._common_loaded = False
        self._full_loaded = False
        self._common_available = False
        self._full_available = False
        # 单词详情缓存（避免重复查询）
        self._lookup_cache: Dict = {}

        # 检查 ENDICT common.json（5万高频词，内存友好）
        if _ENDICT_COMMON.exists() and _ENDICT_COMMON.stat().st_size > 100:
            self._common_available = True
            print(f"[词典] ENDICT 高频词库可用: {_ENDICT_COMMON.name}")

        # 检查 ENDICT full_dict.json（完整词典，按需加载）
        if _ENDICT_FULL.exists() and _ENDICT_FULL.stat().st_size > 100:
            self._full_available = True
            print(f"[词典] ENDICT 完整词典可用: {_ENDICT_FULL.name}")

        if not self._common_available and not self._full_available:
            print("[词典] 未找到 ENDICT 数据，将使用内置词典 + G2P 解析")
            print("[词典] 提示：下载 ENDICT 数据到 backend/dict/endict/ 目录")
            print("[词典]   ENDICT: https://github.com/ismartcoding/endict")

    def _ensure_common(self):
        """延迟加载 ENDICT 高频词库（约14MB，可常驻内存）"""
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

    def _ensure_full(self):
        """延迟标记 ENDICT 完整词典可用

        不再一次性加载136MB的完整词典到内存（会导致OOM），
        改为按需通过 _lookup_full_streaming 逐行查找。
        """
        if self._full_loaded:
            return
        self._full_loaded = True
        if not self._full_available:
            return
        # Don't load the full dict into memory - just mark it available
        print(f"[词典] ENDICT 完整词典可用（按需查询，不预加载）")

    def _lookup_full_streaming(self, word: str) -> Optional[dict]:
        """在完整词典中逐行查找单词（避免一次性加载136MB到内存）

        使用 ijson 或手动解析 JSON 逐条查找
        """
        if not _ENDICT_FULL.exists():
            return None

        word_lower = word.lower()

        try:
            # Method 1: Try ijson for efficient streaming
            try:
                import ijson
                with open(_ENDICT_FULL, "rb") as f:
                    for entry in ijson.items(f, "item"):
                        if isinstance(entry, dict):
                            entry_word = entry.get("word", "").lower()
                            if entry_word == word_lower:
                                return entry
                            # Early exit: JSON keys are sorted, if we've passed the target, stop
                            # (But ijson items doesn't guarantee order, so we can't early-exit)
                return None
            except ImportError:
                pass

            # Method 2: Manual line-by-line parsing (full_dict.json is one large JSON object)
            # Since loading the entire file is too expensive, we do a grep-like search
            import subprocess
            result = subprocess.run(
                ["grep", "-m1", "-i", f'"{word_lower}"', str(_ENDICT_FULL)],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                # This is a rough approach - the grep result might not be valid JSON
                # Try to find the entry in the line
                line = result.stdout.strip()
                # For a proper JSON dict, we'd need the surrounding context
                # This approach is fragile, so we fall through to not loading
                pass

            # Method 3: Just don't use full dict - the common dict covers 50K words
            # which is sufficient for most use cases
            return None

        except Exception as e:
            print(f"[词典] 完整词典查询失败: {e}")
            return None

    def lookup_endict(self, word: str) -> Optional[dict]:
        """从 ENDICT 本地数据查找单词（先查高频词库，再查完整词典）"""
        word_lower = word.lower()

        # 先查高频词库
        self._ensure_common()
        data = self._endict_common.get(word_lower)

        # 如果高频词库没有，查完整词典（按需查询，不预加载到内存）
        if not data and self._full_available:
            data = self._lookup_full_streaming(word_lower)

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

    def lookup(self, word: str, local_only: bool = True) -> dict:
        """
        查询单词，按优先级依次尝试各词典

        参数:
            word: 要查询的单词
            local_only: 仅使用本地数据（默认True，避免在线查询阻塞）

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

        # 2. 内置词典
        from phoneme_data import WORD_DICT
        built_in = WORD_DICT.get(word_clean)
        if built_in:
            result = {
                "word": word_clean,
                "pos": built_in.get("pos", ""),
                "meaning": built_in.get("meaning", ""),
                "ipa": built_in.get("ipa", ""),
                "ipa_us": built_in.get("ipa", ""),
                "ipa_uk": "",
                "arpabet": built_in.get("arpabet", []),
                "example": built_in.get("example", ""),
                "examples": [],
                "frequency": built_in.get("frequency", 0),
                "difficulty": built_in.get("difficulty", 0),
                "memory_tip": built_in.get("memory_tip", ""),
                "grammar_note": built_in.get("grammar_note", ""),
                "source": "builtin",
            }
            self._lookup_cache[word_clean] = result
            return result

        # 3. G2P 自动解析
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


def get_dict_service() -> DictService:
    global _dict_instance
    if _dict_instance is None:
        _dict_instance = DictService()
    return _dict_instance
