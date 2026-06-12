"""
G2P 服务 - 文本转音素

使用 g2p_en 库将英文文本转换为 ARPAbet 音素序列
"""

from typing import List, Tuple, Optional
import re


class G2PService:
    """文本到音素的转换服务"""

    def __init__(self):
        """初始化 G2P 模型"""
        try:
            from g2p_en import G2p
            self.g2p = G2p()
            self._available = True
            print("[G2P] g2p_en 加载成功")
        except ImportError:
            self._available = False
            print("[G2P] g2p_en 未安装，将使用内置词典")

        # 内置常用词音素词典 (ARPAbet)
        # 作为 g2p_en 不可用时的后备
        self._fallback_dict = self._build_fallback_dict()

    def _build_fallback_dict(self) -> dict:
        """构建后备词典"""
        return {
            "the": ["DH", "AH"],
            "weather": ["W", "EH", "DH", "ER"],
            "is": ["IH", "Z"],
            "beautiful": ["B", "Y", "UW", "T", "AH", "F", "AH", "L"],
            "today": ["T", "AH", "D", "EY"],
            "i": ["AY"],
            "would": ["W", "UH", "D"],
            "like": ["L", "AY", "K"],
            "a": ["AH"],
            "cup": ["K", "AH", "P"],
            "of": ["AH", "V"],
            "coffee": ["K", "AO", "F", "IY"],
            "please": ["P", "L", "IY", "Z"],
            "she": ["SH", "IY"],
            "sells": ["S", "EH", "L", "Z"],
            "seashells": ["S", "IY", "SH", "EH", "L", "Z"],
            "by": ["B", "AY"],
            "seashore": ["S", "IY", "SH", "AO", "R"],
            "how": ["HH", "AW"],
            "are": ["AA", "R"],
            "you": ["Y", "UW"],
            "doing": ["D", "UW", "IH", "NG"],
            "this": ["DH", "IH", "S"],
            "morning": ["M", "AO", "R", "N", "IH", "NG"],
            "children": ["CH", "IH", "L", "D", "R", "AH", "N"],
            "playing": ["P", "L", "EY", "IH", "NG"],
            "in": ["IH", "N"],
            "garden": ["G", "AA", "R", "D", "AH", "N"],
            "can": ["K", "AE", "N"],
            "help": ["HH", "EH", "L", "P"],
            "me": ["M", "IY"],
            "find": ["F", "AY", "N", "D"],
            "my": ["M", "AY"],
            "way": ["W", "EY"],
            "enjoy": ["EH", "N", "JH", "OY"],
            "reading": ["R", "IY", "D", "IH", "NG"],
            "books": ["B", "UH", "K", "S"],
            "evening": ["IY", "V", "N", "IH", "NG"],
            "restaurant": ["R", "EH", "S", "T", "R", "AA", "N", "T"],
            "serves": ["S", "ER", "V", "Z"],
            "delicious": ["D", "IH", "L", "IH", "SH", "AH", "S"],
            "food": ["F", "UW", "D"],
            "we": ["W", "IY"],
            "went": ["W", "EH", "N", "T"],
            "to": ["T", "AH"],
            "park": ["P", "AA", "R", "K"],
            "yesterday": ["Y", "EH", "S", "T", "ER", "D", "EY"],
            "learning": ["L", "ER", "N", "IH", "NG"],
            "english": ["IH", "NG", "G", "L", "IH", "SH"],
            "takes": ["T", "EY", "K", "S"],
            "time": ["T", "AY", "M"],
            "and": ["AE", "N", "D"],
            "practice": ["P", "R", "AE", "K", "T", "IH", "S"],
        }

    @property
    def available(self):
        return self._available

    def text_to_phonemes(self, text: str) -> List[str]:
        """
        将文本转换为 ARPAbet 音素列表

        参数:
            text: 英文文本

        返回:
            ARPAbet 音素列表，例如 ["DH", "AH", "W", "EH", "DH", "ER"]
        """
        # 清理文本
        text = text.strip().lower()
        text = re.sub(r'[^a-z\s]', '', text)

        if self._available:
            return self._g2p_with_lib(text)
        else:
            return self._g2p_with_dict(text)

    def _g2p_with_lib(self, text: str) -> List[str]:
        """使用 g2p_en 库转换"""
        result = self.g2p(text)

        # g2p_en 返回的音素格式如 "AA0", "B1" 等
        # 需要去除数字（重音标记）
        phonemes = []
        for p in result:
            # 跳过标点和空格
            if p in (' ', '', ',', '.', '!', '?', ';', ':'):
                continue
            # 去除重音数字
            clean = re.sub(r'\d+', '', p)
            if clean and clean.isupper() and len(clean) <= 3:
                phonemes.append(clean)

        return phonemes

    def _g2p_with_dict(self, text: str) -> List[str]:
        """使用内置词典转换"""
        words = text.split()
        phonemes = []
        for word in words:
            if word in self._fallback_dict:
                phonemes.extend(self._fallback_dict[word])
            else:
                # 简单的字母到音素映射（非常粗略的后备）
                # 实际使用中应该安装 g2p_en
                for ch in word.upper():
                    # 只添加辅音字母的粗略映射
                    simple_map = {
                        'B': 'B', 'D': 'D', 'F': 'F', 'G': 'G',
                        'H': 'HH', 'J': 'JH', 'K': 'K', 'L': 'L',
                        'M': 'M', 'N': 'N', 'P': 'P', 'R': 'R',
                        'S': 'S', 'T': 'T', 'V': 'V', 'W': 'W',
                        'Y': 'Y', 'Z': 'Z',
                    }
                    if ch in simple_map:
                        phonemes.append(simple_map[ch])

        return phonemes

    def text_to_phonemes_with_words(self, text: str) -> List[dict]:
        """
        将文本转换为带单词边界的音素列表

        参数:
            text: 英文文本

        返回:
            列表，每个元素为 {"word": str, "phonemes": [str]}
        """
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


# 全局 G2P 服务实例
_g2p_instance: Optional[G2PService] = None


def get_g2p_service() -> G2PService:
    """获取全局 G2P 服务实例"""
    global _g2p_instance
    if _g2p_instance is None:
        _g2p_instance = G2PService()
    return _g2p_instance
