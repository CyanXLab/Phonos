"""
G2P 服务 - 文本转音素 + IPA 支持
"""

import re
from typing import List, Optional

from phoneme_data import ARPABET_TO_IPA


class G2PService:
    """文本到音素的转换服务"""

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

    @property
    def available(self):
        return self._available

    def text_to_phonemes(self, text: str) -> List[str]:
        """将文本转换为 ARPAbet 音素列表"""
        text = text.strip().lower()
        text = re.sub(r'[^a-z\s]', '', text)
        if self._available:
            return self._g2p_with_lib(text)
        else:
            return self._g2p_with_dict(text)

    def _g2p_with_lib(self, text: str) -> List[str]:
        result = self.g2p(text)
        phonemes = []
        for p in result:
            if p in (' ', '', ',', '.', '!', '?', ';', ':'):
                continue
            clean = re.sub(r'\d+', '', p)
            if clean and clean.isupper() and len(clean) <= 3:
                phonemes.append(clean)
        return phonemes

    def _g2p_with_dict(self, text: str) -> List[str]:
        words = text.split()
        phonemes = []
        for word in words:
            if word in self._fallback_dict:
                phonemes.extend(self._fallback_dict[word])
            else:
                simple_map = {
                    'B': 'B', 'D': 'D', 'F': 'F', 'G': 'G', 'H': 'HH',
                    'J': 'JH', 'K': 'K', 'L': 'L', 'M': 'M', 'N': 'N',
                    'P': 'P', 'R': 'R', 'S': 'S', 'T': 'T', 'V': 'V',
                    'W': 'W', 'Y': 'Y', 'Z': 'Z',
                }
                for ch in word.upper():
                    if ch in simple_map:
                        phonemes.append(simple_map[ch])
        return phonemes

    def text_to_phonemes_with_words(self, text: str) -> List[dict]:
        """将文本转换为带单词边界的音素列表"""
        text = text.strip().lower()
        text = re.sub(r'[^a-z\s]', '', text)
        words = text.split()
        result = []
        for word in words:
            word_phonemes = self.text_to_phonemes(word)
            result.append({
                "word": word,
                "phonemes": word_phonemes,
            })
        return result

    @staticmethod
    def arpabet_to_ipa(phonemes: List[str]) -> str:
        """将 ARPAbet 音素列表转换为 IPA 字符串"""
        ipa_parts = []
        for p in phonemes:
            ipa = ARPABET_TO_IPA.get(p, p)
            ipa_parts.append(ipa)
        return ''.join(ipa_parts)


_g2p_instance: Optional[G2PService] = None


def get_g2p_service() -> G2PService:
    global _g2p_instance
    if _g2p_instance is None:
        _g2p_instance = G2PService()
    return _g2p_instance
