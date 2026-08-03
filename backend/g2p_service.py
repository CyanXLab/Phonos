"""
G2P 服务 - 文本转音素 + IPA 支持

v3 升级点：
1. 保留重音标记（0/1/2），用于重音错误检测
2. 修复元音回退 bug（旧版字母级回退完全无元音）
3. 增加自定义词典支持（上海教材高频词）
4. 单词级 LRU 缓存
5. 兼容旧接口：text_to_phonemes 仍返回无重音 ARPAbet
6. 新接口：text_to_phonemes_with_stress 返回带重音的列表
"""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

from phoneme_data import ARPABET_TO_IPA


class G2PService:
    """文本到音素的转换服务（v3）。"""

    def __init__(self):
        try:
            from g2p_en import G2p

            self.g2p = G2p()
            self._available = True
            print("[G2P] g2p_en 加载成功")
        except ImportError:
            self._available = False
            print("[G2P] g2p_en 未安装，将使用内置词典")

        self._fallback_dict = self._build_fallback_dict()
        self._custom_dict = self._load_custom_dict()

    def _build_fallback_dict(self) -> dict:
        return {
            "the": ["DH", "AH"], "weather": ["W", "EH", "DH", "ER"],
            "is": ["IH", "Z"], "beautiful": ["B", "Y", "UW", "T", "AH", "F", "AH", "L"],
            "today": ["T", "AH", "D", "EY"], "i": ["AY"], "would": ["W", "UH", "D"],
            "like": ["L", "AY", "K"], "a": ["AH"], "cup": ["K", "AH", "P"],
            "of": ["AH", "V"], "coffee": ["K", "AO", "F", "IY"],
            "please": ["P", "L", "IY", "Z"], "she": ["SH", "IY"],
            "sells": ["S", "EH", "L", "Z"], "seashells": ["S", "IY", "SH", "EH", "L", "Z"],
            "by": ["B", "AY"], "seashore": ["S", "IY", "SH", "AO", "R"],
            "how": ["HH", "AW"], "are": ["AA", "R"], "you": ["Y", "UW"],
            "doing": ["D", "UW", "IH", "NG"], "this": ["DH", "IH", "S"],
            "morning": ["M", "AO", "R", "N", "IH", "NG"],
            "children": ["CH", "IH", "L", "D", "R", "AH", "N"],
            "playing": ["P", "L", "EY", "IH", "NG"], "in": ["IH", "N"],
            "garden": ["G", "AA", "R", "D", "AH", "N"],
            "can": ["K", "AE", "N"], "help": ["HH", "EH", "L", "P"],
            "me": ["M", "IY"], "find": ["F", "AY", "N", "D"], "my": ["M", "AY"],
            "way": ["W", "EY"], "enjoy": ["EH", "N", "JH", "OY"],
            "reading": ["R", "IY", "D", "IH", "NG"], "books": ["B", "UH", "K", "S"],
            "evening": ["IY", "V", "N", "IH", "NG"],
            "restaurant": ["R", "EH", "S", "T", "R", "AA", "N", "T"],
            "serves": ["S", "ER", "V", "Z"],
            "delicious": ["D", "IH", "L", "IH", "SH", "AH", "S"],
            "food": ["F", "UW", "D"], "we": ["W", "IY"], "went": ["W", "EH", "N", "T"],
            "to": ["T", "AH"], "park": ["P", "AA", "R", "K"],
            "yesterday": ["Y", "EH", "S", "T", "ER", "D", "EY"],
            "learning": ["L", "ER", "N", "IH", "NG"],
            "english": ["IH", "NG", "G", "L", "IH", "SH"],
            "takes": ["T", "EY", "K", "S"], "time": ["T", "AY", "M"],
            "and": ["AE", "N", "D"], "practice": ["P", "R", "AE", "K", "T", "IH", "S"],
        }

    def _load_custom_dict(self) -> dict:
        """加载自定义词典（上海教材高频词、专有名词等）。"""
        try:
            from app.core.config import get_settings

            path = Path(get_settings().g2p_custom_dict_path)
            if path.is_file():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    @property
    def available(self):
        return self._available

    @lru_cache(maxsize=10000)
    def _word_to_phonemes_cached(self, word: str) -> Tuple[str, ...]:
        """单词级 LRU 缓存。"""
        return tuple(self._word_to_phonemes_uncached(word))

    def _word_to_phonemes_uncached(self, word: str) -> List[str]:
        # 1. 自定义词典优先
        if word in self._custom_dict:
            return list(self._custom_dict[word])

        # 2. 内置回退词典
        if word in self._fallback_dict:
            return list(self._fallback_dict[word])

        # 3. g2p_en
        if self._available:
            result = self.g2p(word)
            phonemes = []
            for p in result:
                if p in (" ", "", ",", ".", "!", "?", ";", ":"):
                    continue
                # v3：去除重音数字（兼容旧接口）
                clean = re.sub(r"\d+", "", p)
                if clean and clean.isupper() and len(clean) <= 3:
                    phonemes.append(clean)
            if phonemes:
                return phonemes

        # 4. 字母级回退（v3 修复：包含元音）
        return self._letter_fallback(word)

    def _letter_fallback(self, word: str) -> List[str]:
        """字母级回退（v3 修复：包含元音）。

        旧版只映射辅音字母，元音被丢弃，导致 expected_phonemes 严重失真。
        新版根据字母所在位置（首/中/末）给出合理近似。
        """
        # 元音字母到 ARPAbet 的近似映射
        vowel_map = {
            "a": ["AE"], "e": ["EH"], "i": ["IH"],
            "o": ["AA"], "u": ["AH"],
            "y": ["IY"],  # 词尾 y 通常读 /iː/
        }
        # 辅音字母映射
        consonant_map = {
            "b": "B", "c": "K", "d": "D", "f": "F", "g": "G",
            "h": "HH", "j": "JH", "k": "K", "l": "L", "m": "M",
            "n": "N", "p": "P", "q": "K", "r": "R", "s": "S",
            "t": "T", "v": "V", "w": "W", "x": ["K", "S"],
            "z": "Z",
        }

        phonemes: List[str] = []
        w = word.lower()
        for i, ch in enumerate(w):
            if ch in vowel_map:
                # 词尾 e 不发音
                if i == len(w) - 1 and ch == "e" and len(w) > 2:
                    continue
                phonemes.extend(vowel_map[ch])
            elif ch in consonant_map:
                # c 在 e/i/y 前发 /s/
                if ch == "c" and i + 1 < len(w) and w[i + 1] in ("e", "i", "y"):
                    phonemes.append("S")
                else:
                    val = consonant_map[ch]
                    if isinstance(val, list):
                        phonemes.extend(val)
                    else:
                        phonemes.append(val)
        return phonemes

    def text_to_phonemes(self, text: str) -> List[str]:
        """将文本转换为 ARPAbet 音素列表（兼容旧接口，无重音）。"""
        text = text.strip().lower()
        text = re.sub(r"[^a-z\s']", "", text)
        words = text.split()
        phonemes: List[str] = []
        for word in words:
            phonemes.extend(self._word_to_phonemes_cached(word))
        return phonemes

    def text_to_phonemes_with_stress(self, text: str) -> List[str]:
        """v3 新接口：保留重音标记（如 AE1, IH0）。"""
        if not self._available:
            return self.text_to_phonemes(text)
        text = text.strip().lower()
        text = re.sub(r"[^a-z\s']", "", text)
        result = self.g2p(text)
        phonemes = []
        for p in result:
            if p in (" ", "", ",", ".", "!", "?", ";", ":"):
                continue
            # 保留 0/1/2 数字
            if re.match(r"^[A-Z]{1,3}[012]?$", p):
                phonemes.append(p)
        return phonemes

    def text_to_phonemes_with_words(self, text: str) -> List[dict]:
        """将文本转换为带单词边界的音素列表。"""
        text = text.strip().lower()
        text = re.sub(r"[^a-z\s']", "", text)
        words = text.split()
        result = []
        for word in words:
            word_phonemes = list(self._word_to_phonemes_cached(word))
            result.append({"word": word, "phonemes": word_phonemes})
        return result

    def text_to_phonemes_with_words_and_stress(self, text: str) -> List[dict]:
        """v3 新接口：带重音的单词边界。"""
        if not self._available:
            return self.text_to_phonemes_with_words(text)
        text = text.strip().lower()
        text = re.sub(r"[^a-z\s']", "", text)
        words = text.split()
        result = []
        for word in words:
            raw = self.g2p(word)
            word_phonemes = []
            for p in raw:
                if p in (" ", "", ",", ".", "!", "?", ";", ":"):
                    continue
                if re.match(r"^[A-Z]{1,3}[012]?$", p):
                    word_phonemes.append(p)
            result.append({"word": word, "phonemes": word_phonemes})
        return result

    def get_stress_pattern(self, text: str) -> List[int]:
        """提取重音模式（用于重音错误检测）。

        返回每个元音的重音等级：0=无重音, 1=主重音, 2=次重音
        """
        stressed = self.text_to_phonemes_with_stress(text)
        pattern = []
        for p in stressed:
            if p and p[-1] in "012":
                pattern.append(int(p[-1]))
        return pattern

    @staticmethod
    def arpabet_to_ipa(phonemes: List[str]) -> str:
        """将 ARPAbet 音素列表转换为 IPA 字符串。"""
        ipa_parts = []
        for p in phonemes:
            # 去除重音数字后查表
            base = re.sub(r"\d+$", "", p)
            ipa = ARPABET_TO_IPA.get(base, base)
            # 重音标记：1 → 主重音符号 ˈ，2 → 次重音 ˌ
            if p and p[-1] == "1":
                ipa_parts.append("ˈ")
            elif p and p[-1] == "2":
                ipa_parts.append("ˌ")
            ipa_parts.append(ipa)
        return "".join(ipa_parts)


_g2p_instance: Optional[G2PService] = None


def get_g2p_service() -> G2PService:
    global _g2p_instance
    if _g2p_instance is None:
        _g2p_instance = G2PService()
    return _g2p_instance
