"""
Phonos 口语练习平台 - 语言学数据层

包含：
- 句子数据（从 sentences.json 动态加载，支持增量更新）
- G2P 音素缓存（首次生成，后续增量更新）
- 完整单词词典（音标、释义、词性、例句）
- 44个ARPAbet音素的详细发音指南
- IPA-ARPAbet映射
- 最小对立对(Minimal Pairs)数据
- FSRS间隔重复数据库
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Optional

_DATA_DIR = Path(__file__).parent
_SENTENCES_FILE = _DATA_DIR / "sentences.json"
_PHONEME_CACHE_FILE = _DATA_DIR / "phoneme_cache.json"


# ============================================================
# 句子数据：从本地文件加载
# ============================================================
def load_sentences() -> List[dict]:
    """从 sentences.json 加载句子，文件不存在则返回空列表"""
    if _SENTENCES_FILE.exists():
        try:
            with open(_SENTENCES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[数据] 加载 sentences.json 失败: {e}")
    return []


def save_sentences(sentences: List[dict]):
    """保存句子到 sentences.json"""
    with open(_SENTENCES_FILE, "w", encoding="utf-8") as f:
        json.dump(sentences, f, ensure_ascii=False, indent=2)


# 延迟加载：PRESET_SENTENCES 在首次访问时从文件读取
_PRESET_SENTENCES_CACHE = None

def get_preset_sentences() -> List[dict]:
    global _PRESET_SENTENCES_CACHE
    if _PRESET_SENTENCES_CACHE is None:
        _PRESET_SENTENCES_CACHE = load_sentences()
    return _PRESET_SENTENCES_CACHE


# 兼容旧代码：PRESET_SENTENCES 作为属性访问
class _PresetSentences(list):
    def __init__(self):
        super().__init__()
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.extend(load_sentences())
            self._loaded = True

    def __iter__(self):
        self._ensure_loaded()
        return super().__iter__()

    def __len__(self):
        self._ensure_loaded()
        return super().__len__()

    def __getitem__(self, index):
        self._ensure_loaded()
        return super().__getitem__(index)

    def __bool__(self):
        self._ensure_loaded()
        return super().__bool__()

PRESET_SENTENCES = _PresetSentences()


# ============================================================
# G2P 音素缓存：首次生成，后续增量更新
# ============================================================
def load_phoneme_cache() -> Dict:
    """从 phoneme_cache.json 加载音素缓存"""
    if _PHONEME_CACHE_FILE.exists():
        try:
            with open(_PHONEME_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_phoneme_cache(cache: Dict):
    """保存音素缓存"""
    with open(_PHONEME_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def update_phoneme_cache(sentences: List[dict], g2p_service) -> Dict:
    """
    增量更新音素缓存

    - 新增句子的音素会被计算
    - 已有且文本未变的句子保留缓存
    - 已删除的句子移除缓存
    """
    cache = load_phoneme_cache()
    current_texts = {s["text"] for s in sentences}

    # 移除已删除句子的缓存
    removed = [k for k in cache if k not in current_texts]
    for k in removed:
        del cache[k]
        print(f"  [缓存] 移除: '{k}'")

    # 为新句子或修改的句子生成音素
    added = 0
    for s in sentences:
        text = s["text"]
        if text not in cache:
            phonemes = g2p_service.text_to_phonemes(text)
            word_phonemes = g2p_service.text_to_phonemes_with_words(text)
            ipa = g2p_service.arpabet_to_ipa(phonemes)
            cache[text] = {
                "phonemes": phonemes,
                "word_phonemes": word_phonemes,
                "ipa": ipa,
            }
            added += 1
            print(f"  [缓存] 新增: '{text}' -> {' '.join(phonemes)}")

    if added > 0 or removed:
        save_phoneme_cache(cache)
        print(f"[缓存] 更新完成: +{added} 新增, -{len(removed)} 移除")

    return cache


# ============================================================
# 音素→示例词映射（用于点击发音）
# ============================================================
PHONEME_EXAMPLE_WORD = {}
# 从 PHONEME_TIPS 中自动构建（在 PHONEME_TIPS 定义之后设置）

# ============================================================
# 单词词典（覆盖10个句子中的所有单词）
# ============================================================
WORD_DICT = {
    "the": {
        "pos": "art.",
        "meaning": "这/那/这些/那些（定冠词）",
        "ipa": "/ðə/",
        "arpabet": ["DH", "AH"],
        "example": "The book is on the table.",
        "frequency": 5,
        "difficulty": 1,
    },
    "weather": {
        "pos": "n.",
        "meaning": "天气",
        "ipa": "/ˈwɛðər/",
        "arpabet": ["W", "EH", "DH", "ER"],
        "example": "What's the weather like today?",
        "frequency": 4,
        "difficulty": 2,
    },
    "is": {
        "pos": "v.",
        "meaning": "是（be动词第三人称单数）",
        "ipa": "/ɪz/",
        "arpabet": ["IH", "Z"],
        "example": "She is a teacher.",
        "frequency": 5,
        "difficulty": 1,
    },
    "beautiful": {
        "pos": "adj.",
        "meaning": "美丽的，漂亮的",
        "ipa": "/ˈbjuːtɪfəl/",
        "arpabet": ["B", "Y", "UW", "T", "AH", "F", "AH", "L"],
        "example": "What a beautiful sunset!",
        "frequency": 4,
        "difficulty": 2,
        "memory_tip": "beauty(美) + ful(形容词后缀) → 充满美的 → 美丽的",
    },
    "today": {
        "pos": "n./adv.",
        "meaning": "今天",
        "ipa": "/təˈdeɪ/",
        "arpabet": ["T", "AH", "D", "EY"],
        "example": "I have a meeting today.",
        "frequency": 5,
        "difficulty": 1,
    },
    "i": {
        "pos": "pron.",
        "meaning": "我",
        "ipa": "/aɪ/",
        "arpabet": ["AY"],
        "example": "I am a student.",
        "frequency": 5,
        "difficulty": 1,
    },
    "would": {
        "pos": "v.",
        "meaning": "愿意，将会（will的过去式/虚拟语气）",
        "ipa": "/wʊd/",
        "arpabet": ["W", "UH", "D"],
        "example": "I would like some water.",
        "frequency": 5,
        "difficulty": 2,
        "memory_tip": "与 will 对应，would 是其过去式/更礼貌的形式",
    },
    "like": {
        "pos": "v./prep.",
        "meaning": "喜欢/像",
        "ipa": "/laɪk/",
        "arpabet": ["L", "AY", "K"],
        "example": "I like reading books.",
        "frequency": 5,
        "difficulty": 1,
    },
    "a": {
        "pos": "art.",
        "meaning": "一个（不定冠词）",
        "ipa": "/ə/",
        "arpabet": ["AH"],
        "example": "I have a dog.",
        "frequency": 5,
        "difficulty": 1,
    },
    "cup": {
        "pos": "n.",
        "meaning": "杯子",
        "ipa": "/kʌp/",
        "arpabet": ["K", "AH", "P"],
        "example": "A cup of tea, please.",
        "frequency": 3,
        "difficulty": 1,
    },
    "of": {
        "pos": "prep.",
        "meaning": "...的（表示所属/数量）",
        "ipa": "/ʌv/",
        "arpabet": ["AH", "V"],
        "example": "A glass of water.",
        "frequency": 5,
        "difficulty": 1,
    },
    "coffee": {
        "pos": "n.",
        "meaning": "咖啡",
        "ipa": "/ˈkɔːfi/",
        "arpabet": ["K", "AO", "F", "IY"],
        "example": "I need my morning coffee.",
        "frequency": 4,
        "difficulty": 1,
    },
    "please": {
        "pos": "adv.",
        "meaning": "请（礼貌用语）",
        "ipa": "/pliːz/",
        "arpabet": ["P", "L", "IY", "Z"],
        "example": "Sit down, please.",
        "frequency": 5,
        "difficulty": 1,
    },
    "how": {
        "pos": "adv.",
        "meaning": "怎样，多么",
        "ipa": "/haʊ/",
        "arpabet": ["HH", "AW"],
        "example": "How do you do?",
        "frequency": 5,
        "difficulty": 1,
    },
    "are": {
        "pos": "v.",
        "meaning": "是（be动词复数/第二人称）",
        "ipa": "/ɑːr/",
        "arpabet": ["AA", "R"],
        "example": "You are welcome.",
        "frequency": 5,
        "difficulty": 1,
    },
    "you": {
        "pos": "pron.",
        "meaning": "你，你们",
        "ipa": "/juː/",
        "arpabet": ["Y", "UW"],
        "example": "How are you?",
        "frequency": 5,
        "difficulty": 1,
    },
    "doing": {
        "pos": "v.",
        "meaning": "做（do的现在分词）",
        "ipa": "/ˈduːɪŋ/",
        "arpabet": ["D", "UW", "IH", "NG"],
        "example": "What are you doing?",
        "frequency": 4,
        "difficulty": 2,
    },
    "this": {
        "pos": "pron./det.",
        "meaning": "这个",
        "ipa": "/ðɪs/",
        "arpabet": ["DH", "IH", "S"],
        "example": "This is my friend.",
        "frequency": 5,
        "difficulty": 1,
    },
    "morning": {
        "pos": "n.",
        "meaning": "早晨，上午",
        "ipa": "/ˈmɔːrnɪŋ/",
        "arpabet": ["M", "AO", "R", "N", "IH", "NG"],
        "example": "Good morning!",
        "frequency": 5,
        "difficulty": 1,
    },
    "can": {
        "pos": "v.",
        "meaning": "能，可以",
        "ipa": "/kæn/",
        "arpabet": ["K", "AE", "N"],
        "example": "Can I help you?",
        "frequency": 5,
        "difficulty": 1,
    },
    "help": {
        "pos": "v./n.",
        "meaning": "帮助",
        "ipa": "/hɛlp/",
        "arpabet": ["HH", "EH", "L", "P"],
        "example": "Can you help me?",
        "frequency": 5,
        "difficulty": 1,
    },
    "me": {
        "pos": "pron.",
        "meaning": "我（宾格）",
        "ipa": "/miː/",
        "arpabet": ["M", "IY"],
        "example": "Tell me about it.",
        "frequency": 5,
        "difficulty": 1,
    },
    "find": {
        "pos": "v.",
        "meaning": "找到，发现",
        "ipa": "/faɪnd/",
        "arpabet": ["F", "AY", "N", "D"],
        "example": "I can't find my keys.",
        "frequency": 4,
        "difficulty": 2,
    },
    "my": {
        "pos": "pron.",
        "meaning": "我的",
        "ipa": "/maɪ/",
        "arpabet": ["M", "AY"],
        "example": "My name is John.",
        "frequency": 5,
        "difficulty": 1,
    },
    "way": {
        "pos": "n.",
        "meaning": "路，方式",
        "ipa": "/weɪ/",
        "arpabet": ["W", "EY"],
        "example": "Which way is the station?",
        "frequency": 4,
        "difficulty": 2,
    },
    "children": {
        "pos": "n.",
        "meaning": "孩子们（child的复数）",
        "ipa": "/ˈtʃɪldrən/",
        "arpabet": ["CH", "IH", "L", "D", "R", "AH", "N"],
        "example": "The children are at school.",
        "frequency": 3,
        "difficulty": 3,
        "memory_tip": "child + ren（不规则复数后缀），类似 ox→oxen",
    },
    "playing": {
        "pos": "v.",
        "meaning": "正在玩耍（play的现在分词）",
        "ipa": "/ˈpleɪɪŋ/",
        "arpabet": ["P", "L", "EY", "IH", "NG"],
        "example": "They are playing soccer.",
        "frequency": 4,
        "difficulty": 2,
    },
    "in": {
        "pos": "prep.",
        "meaning": "在...里面",
        "ipa": "/ɪn/",
        "arpabet": ["IH", "N"],
        "example": "The cat is in the box.",
        "frequency": 5,
        "difficulty": 1,
    },
    "garden": {
        "pos": "n.",
        "meaning": "花园，菜园",
        "ipa": "/ˈɡɑːrdn/",
        "arpabet": ["G", "AA", "R", "D", "AH", "N"],
        "example": "She has a beautiful garden.",
        "frequency": 3,
        "difficulty": 2,
        "memory_tip": "guard(守卫) + en → 守护的地方 → 花园",
    },
    "enjoy": {
        "pos": "v.",
        "meaning": "享受，喜欢",
        "ipa": "/ɪnˈdʒɔɪ/",
        "arpabet": ["EH", "N", "JH", "OY"],
        "example": "I enjoy swimming.",
        "frequency": 4,
        "difficulty": 2,
        "memory_tip": "en(使) + joy(快乐) → 使快乐 → 享受",
        "grammar_note": "enjoy 后必须接动名词(doing)，不能接不定式(to do)",
    },
    "reading": {
        "pos": "v./n.",
        "meaning": "阅读（read的动名词形式）",
        "ipa": "/ˈriːdɪŋ/",
        "arpabet": ["R", "IY", "D", "IH", "NG"],
        "example": "Reading is fun.",
        "frequency": 4,
        "difficulty": 2,
    },
    "books": {
        "pos": "n.",
        "meaning": "书籍（book的复数）",
        "ipa": "/bʊks/",
        "arpabet": ["B", "UH", "K", "S"],
        "example": "I like reading books.",
        "frequency": 4,
        "difficulty": 1,
    },
    "evening": {
        "pos": "n.",
        "meaning": "晚上，傍晚",
        "ipa": "/ˈiːvnɪŋ/",
        "arpabet": ["IY", "V", "N", "IH", "NG"],
        "example": "Good evening!",
        "frequency": 4,
        "difficulty": 2,
    },
    "restaurant": {
        "pos": "n.",
        "meaning": "餐厅，饭店",
        "ipa": "/ˈrɛstərɒnt/",
        "arpabet": ["R", "EH", "S", "T", "R", "AA", "N", "T"],
        "example": "Let's go to a restaurant.",
        "frequency": 4,
        "difficulty": 3,
        "memory_tip": "rest(休息) + aurant → 休息吃饭的地方 → 餐厅",
    },
    "serves": {
        "pos": "v.",
        "meaning": "供应，服务（serve的第三人称单数）",
        "ipa": "/sɜːrvz/",
        "arpabet": ["S", "ER", "V", "Z"],
        "example": "This restaurant serves great pizza.",
        "frequency": 3,
        "difficulty": 3,
    },
    "delicious": {
        "pos": "adj.",
        "meaning": "美味的，可口的",
        "ipa": "/dɪˈlɪʃəs/",
        "arpabet": ["D", "IH", "L", "IH", "SH", "AH", "S"],
        "example": "The cake is delicious.",
        "frequency": 4,
        "difficulty": 3,
        "memory_tip": "de(加强) + lici(诱惑) + ous → 十分诱人的 → 美味的",
    },
    "food": {
        "pos": "n.",
        "meaning": "食物",
        "ipa": "/fuːd/",
        "arpabet": ["F", "UW", "D"],
        "example": "Chinese food is amazing.",
        "frequency": 4,
        "difficulty": 1,
    },
    "we": {
        "pos": "pron.",
        "meaning": "我们",
        "ipa": "/wiː/",
        "arpabet": ["W", "IY"],
        "example": "We are friends.",
        "frequency": 5,
        "difficulty": 1,
    },
    "went": {
        "pos": "v.",
        "meaning": "去了（go的过去式）",
        "ipa": "/wɛnt/",
        "arpabet": ["W", "EH", "N", "T"],
        "example": "We went to the beach.",
        "frequency": 4,
        "difficulty": 2,
        "memory_tip": "go → went（不规则过去式），需单独记忆",
    },
    "to": {
        "pos": "prep.",
        "meaning": "到，向",
        "ipa": "/tə/",
        "arpabet": ["T", "AH"],
        "example": "I go to school every day.",
        "frequency": 5,
        "difficulty": 1,
    },
    "park": {
        "pos": "n.",
        "meaning": "公园",
        "ipa": "/pɑːrk/",
        "arpabet": ["P", "AA", "R", "K"],
        "example": "Let's walk in the park.",
        "frequency": 4,
        "difficulty": 1,
    },
    "yesterday": {
        "pos": "n./adv.",
        "meaning": "昨天",
        "ipa": "/ˈjɛstərdeɪ/",
        "arpabet": ["Y", "EH", "S", "T", "ER", "D", "EY"],
        "example": "I saw him yesterday.",
        "frequency": 4,
        "difficulty": 2,
        "memory_tip": "yester(昨日) + day(天) → 昨天",
    },
    "learning": {
        "pos": "v./n.",
        "meaning": "学习（learn的动名词）",
        "ipa": "/ˈlɜːrnɪŋ/",
        "arpabet": ["L", "ER", "N", "IH", "NG"],
        "example": "Learning is a lifelong journey.",
        "frequency": 4,
        "difficulty": 2,
    },
    "english": {
        "pos": "n./adj.",
        "meaning": "英语/英国的",
        "ipa": "/ˈɪŋɡlɪʃ/",
        "arpabet": ["IH", "NG", "G", "L", "IH", "SH"],
        "example": "I study English every day.",
        "frequency": 5,
        "difficulty": 1,
    },
    "takes": {
        "pos": "v.",
        "meaning": "花费，需要（take的第三人称单数）",
        "ipa": "/teɪks/",
        "arpabet": ["T", "EY", "K", "S"],
        "example": "It takes two hours.",
        "frequency": 4,
        "difficulty": 2,
    },
    "time": {
        "pos": "n.",
        "meaning": "时间",
        "ipa": "/taɪm/",
        "arpabet": ["T", "AY", "M"],
        "example": "What time is it?",
        "frequency": 5,
        "difficulty": 1,
    },
    "and": {
        "pos": "conj.",
        "meaning": "和，与",
        "ipa": "/ænd/",
        "arpabet": ["AE", "N", "D"],
        "example": "You and I are friends.",
        "frequency": 5,
        "difficulty": 1,
    },
    "practice": {
        "pos": "n./v.",
        "meaning": "练习",
        "ipa": "/ˈpræktɪs/",
        "arpabet": ["P", "R", "AE", "K", "T", "IH", "S"],
        "example": "Practice makes perfect.",
        "frequency": 4,
        "difficulty": 2,
        "memory_tip": "pract(做) + ice → 反复做 → 练习",
    },
    "she": {
        "pos": "pron.",
        "meaning": "她",
        "ipa": "/ʃiː/",
        "arpabet": ["SH", "IY"],
        "example": "She is my sister.",
        "frequency": 5,
        "difficulty": 1,
    },
    "sells": {
        "pos": "v.",
        "meaning": "卖（sell的第三人称单数）",
        "ipa": "/sɛlz/",
        "arpabet": ["S", "EH", "L", "Z"],
        "example": "She sells flowers.",
        "frequency": 3,
        "difficulty": 2,
    },
    "seashells": {
        "pos": "n.",
        "meaning": "贝壳（seashell的复数）",
        "ipa": "/ˈsiːʃɛlz/",
        "arpabet": ["S", "IY", "SH", "EH", "L", "Z"],
        "example": "We collected seashells on the beach.",
        "frequency": 2,
        "difficulty": 3,
        "memory_tip": "sea(海) + shell(壳) → 海里的壳 → 贝壳",
    },
    "by": {
        "pos": "prep./adv.",
        "meaning": "在...旁边/通过",
        "ipa": "/baɪ/",
        "arpabet": ["B", "AY"],
        "example": "She sat by the window.",
        "frequency": 4,
        "difficulty": 1,
    },
    "seashore": {
        "pos": "n.",
        "meaning": "海岸，海边",
        "ipa": "/ˈsiːʃɔːr/",
        "arpabet": ["S", "IY", "SH", "AO", "R"],
        "example": "We walked along the seashore.",
        "frequency": 2,
        "difficulty": 3,
        "memory_tip": "sea(海) + shore(岸) → 海岸",
    },
}

# ============================================================
# ARPAbet → IPA 映射
# ============================================================
ARPABET_TO_IPA = {
    "AA": "ɑː", "AE": "æ", "AH": "ə", "AW": "aʊ", "AY": "aɪ",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "DX": "ɾ",
    "EH": "ɛ", "ER": "ɜːr", "EY": "eɪ", "F": "f", "G": "ɡ",
    "HH": "h", "IH": "ɪ", "IY": "iː", "JH": "dʒ", "K": "k",
    "L": "l", "M": "m", "N": "n", "NG": "ŋ", "OW": "oʊ",
    "OY": "ɔɪ", "P": "p", "R": "r", "S": "s", "SH": "ʃ",
    "T": "t", "TH": "θ", "UH": "ʊ", "UW": "uː", "V": "v",
    "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}

# ============================================================
# 音素词汇表
# ============================================================
VOCAB = {
    "<PAD>": 0, "<UNK>": 1, "<BOS>": 2, "<EOS>": 3, "|": 4,
    "AA": 5, "AE": 6, "AH": 7, "AW": 8, "AY": 9,
    "B": 10, "CH": 11, "D": 12, "DH": 13, "DX": 14,
    "EH": 15, "ER": 16, "EY": 17, "F": 18, "G": 19,
    "HH": 20, "IH": 21, "IY": 22, "JH": 23, "K": 24,
    "L": 25, "M": 26, "N": 27, "NG": 28, "OW": 29,
    "OY": 30, "P": 31, "R": 32, "S": 33, "SH": 34,
    "T": 35, "TH": 36, "UH": 37, "UW": 38, "V": 39,
    "W": 40, "Y": 41, "Z": 42, "ZH": 43,
    "<s>": 44, "</s>": 45,
}

ID2TOKEN = {v: k for k, v in VOCAB.items()}
BLANK_ID = 0

# ============================================================
# 音素分类
# ============================================================
PHONEME_CATEGORIES = {
    "vowels": {
        "short": ["AA", "AE", "AH", "EH", "IH", "UH"],
        "long": ["AY", "AW", "EY", "OW", "OY", "IY", "UW"],
        "r_colored": ["ER"],
    },
    "consonants": {
        "stops": ["B", "D", "G", "K", "P", "T"],
        "fricatives": ["F", "S", "SH", "TH", "V", "Z", "ZH", "DH"],
        "affricates": ["CH", "JH"],
        "nasals": ["M", "N", "NG"],
        "liquids": ["L", "R"],
        "glides": ["W", "Y"],
        "aspirate": ["HH"],
    },
}

PHONEME_GROUP = {}
for group_name, subgroups in PHONEME_CATEGORIES.items():
    for sub_name, phonemes in subgroups.items():
        for p in phonemes:
            PHONEME_GROUP[p] = (group_name, sub_name)

# ============================================================
# 最小对立对 (Minimal Pairs) - 中国学习者最易混淆
# ============================================================
MINIMAL_PAIRS = [
    {
        "pair": ("L", "R"),
        "examples": [("light", "right"), ("lead", "read"), ("fly", "fry"), ("collect", "correct")],
        "description": "中国学习者最难的区分之一：/L/ 是边音（舌尖抵上齿龈，气流从两侧出），/R/ 是卷舌音（舌尖上卷不触上颚）",
        "drill_sentence": "Red lorry, yellow lorry",
        "difficulty": "hard",
        "native_language_issue": "中文普通话的 r 和 l 与英文不同，中文 r 更接近英文 zh",
    },
    {
        "pair": ("TH", "S"),
        "examples": [("think", "sink"), ("thin", "sin"), ("thumb", "some"), ("mouth", "mouse")],
        "description": "中文没有 /TH/ (θ) 音，学习者常用 /S/ 替代。关键：舌尖必须伸出上下齿之间",
        "drill_sentence": "I think the sink is thin",
        "difficulty": "hard",
        "native_language_issue": "中文无齿间擦音，S替代是最常见错误",
    },
    {
        "pair": ("DH", "Z"),
        "examples": [("this", "zis"), ("that", "zat"), ("the", "ze"), ("them", "zem")],
        "description": "浊音版本，/DH/ (ð) 常被 /Z/ 替代。口型与 /TH/ 相同但声带振动",
        "drill_sentence": "This and that are the things",
        "difficulty": "hard",
        "native_language_issue": "与 /TH/ 同理，中文无此音",
    },
    {
        "pair": ("V", "W"),
        "examples": [("vet", "wet"), ("vine", "wine"), ("vest", "west"), ("vetting", "wedding")],
        "description": "/V/ 是唇齿音（上齿咬下唇），/W/ 是双唇音（双唇合拢）。中国南方学习者尤其易混淆",
        "drill_sentence": "Very well, wet vest",
        "difficulty": "medium",
        "native_language_issue": "部分方言区 w/v 不分",
    },
    {
        "pair": ("S", "SH"),
        "examples": [("see", "she"), ("seat", "sheet"), ("sell", "shell"), ("sip", "ship")],
        "description": "/S/ 是齿龈擦音（嘴角展开），/SH/ 是齿龈后擦音（嘴唇前突圆起）。口型完全不同",
        "drill_sentence": "She sells seashells",
        "difficulty": "medium",
        "native_language_issue": "中文 sh 和英文 SH 发音位置不同",
    },
    {
        "pair": ("IH", "IY"),
        "examples": [("sit", "seat"), ("bit", "beat"), ("ship", "sheep"), ("fill", "feel")],
        "description": "短元音 /IH/ 和长元音 /IY/。/IH/ 短促放松，/IY/ 长而紧，嘴角更展开",
        "drill_sentence": "Sit in the seat and feel it",
        "difficulty": "medium",
        "native_language_issue": "中文无长短元音对立，学习者常忽略时长差异",
    },
    {
        "pair": ("AE", "EH"),
        "examples": [("cat", "ket"), ("bad", "bed"), ("fan", "fen"), ("sat", "set")],
        "description": "/AE/ 嘴更大（嘴巴张开约两指宽），/EH/ 嘴更小（约一指宽）。区别在于开口度",
        "drill_sentence": "The bad cat sat on the bed",
        "difficulty": "medium",
        "native_language_issue": "中文无 /AE/ 音，学习者常发成 /EH/ 或 /AH/",
    },
    {
        "pair": ("F", "V"),
        "examples": [("fan", "van"), ("fine", "vine"), ("safe", "save"), ("leaf", "leave")],
        "description": "清浊对立：口型相同（上齿咬下唇），区别仅在于声带是否振动。/F/ 无振动，/V/ 有振动",
        "drill_sentence": "Five fine vans arrived",
        "difficulty": "easy",
        "native_language_issue": "中文无清浊辅音对立（只有送气/不送气对立）",
    },
    {
        "pair": ("Z", "S"),
        "examples": [("zoo", "Sue"), ("buzz", "bus"), ("zip", "sip"), ("haze", "face")],
        "description": "清浊对立：口型相同（齿龈擦音），区别仅在于声带振动",
        "drill_sentence": "Sue visits the zoo and sees the buses",
        "difficulty": "easy",
        "native_language_issue": "同 /F/-/V/，中文无浊擦音",
    },
    {
        "pair": ("N", "NG"),
        "examples": [("sin", "sing"), ("ran", "rang"), ("ton", "tongue"), ("ban", "bang")],
        "description": "/N/ 舌尖抵上齿龈，/NG/ 舌根抵软腭。位置完全不同，但中国学习者常混淆词尾的 n/ng",
        "drill_sentence": "Sing a song and run along",
        "difficulty": "medium",
        "native_language_issue": "部分方言（如南方方言）n/ng 不分",
    },
    {
        "pair": ("CH", "JH"),
        "examples": [("chin", "gin"), ("batch", "badge"), ("chunk", "junk"), ("rich", "ridge")],
        "description": "清浊对立：/CH/ 不振动+送气，/JH/ 振动+不送气",
        "drill_sentence": "Choose the juice with chunks",
        "difficulty": "easy",
        "native_language_issue": "中文的 j/q/x 与英文 CH/JH 发音位置不同",
    },
    {
        "pair": ("B", "P"),
        "examples": [("bat", "pat"), ("big", "pig"), ("cab", "cap"), ("robe", "rope")],
        "description": "清浊对立：/B/ 声带振动，/P/ 不振动且强送气",
        "drill_sentence": "A big pig with a bat and a pat",
        "difficulty": "easy",
        "native_language_issue": "中文 b/p 是不送气/送气对立，不是清浊对立",
    },
]

# ============================================================
# 44个音素完整发音指南
# ============================================================
PHONEME_TIPS = {
    # === 元音 ===
    "AA": {
        "description": "开口后元音，如 fAther 中的 a",
        "common_error": "容易发成 /AE/ 或 /AH/，嘴巴张得不够大，舌位偏前",
        "solution": "嘴巴张大，舌头放低靠后，像打哈欠时的口型。发 'ah' 音，保持嘴型稳定。用手轻触喉咙感受声带振动。",
        "mouth_shape": "口腔大开，舌后缩，下巴明显下降",
        "practice_words": ["father", "car", "park", "start", "heart"],
        "ipa": "ɑː",
    },
    "AE": {
        "description": "开前元音，如 cAt 中的 a",
        "common_error": "容易发成 /AA/ 或 /EH/，嘴型偏圆或偏窄，开口度不够",
        "solution": "嘴巴张开约两指宽，嘴角稍向两侧拉开，像微笑时的口型。发介于 'a' 和 'e' 之间的音。对着镜子确认开口度。",
        "mouth_shape": "口腔半开，舌前部稍抬，嘴角微展",
        "practice_words": ["cat", "bad", "hat", "man", "family"],
        "ipa": "æ",
    },
    "AH": {
        "description": "中央元音（Schwa），如 abOut 中的 u",
        "common_error": "容易发成 /AA/ 或 /UH/，口型过于极端或不放松",
        "solution": "嘴巴自然放松，舌头处于中间位置，发出最自然的 'uh' 音。这是英语中最常见的元音，所有非重读元音都可能变成它。全身放松，不要用力。",
        "mouth_shape": "口腔自然，舌位居中，嘴唇放松",
        "practice_words": ["about", "the", "again", "sofa", "banana"],
        "ipa": "ə",
    },
    "AW": {
        "description": "双元音，如 hOW 中的 ow",
        "common_error": "滑动不够，或起始音偏错，或发成 /AA/ + /W/",
        "solution": "从 /AA/ 滑向 /UW/，嘴巴从大开到渐圆。注意两个音的平滑过渡，不要停顿。像说 '啊呜' 但连起来。",
        "mouth_shape": "从大开到圆唇，下巴从低到高",
        "practice_words": ["how", "now", "house", "down", "brown"],
        "ipa": "aʊ",
    },
    "AY": {
        "description": "双元音，如 bIte 中的 i",
        "common_error": "滑动不够或发成单元音 /AA/，缺少 /IY/ 的滑动",
        "solution": "从 /AA/ 滑向 /IY/，下巴从低到高，嘴角从开到合。感受下巴明显上抬。像说 '啊伊' 但一气呵成。",
        "mouth_shape": "从大开到扁唇，下巴明显上抬",
        "practice_words": ["like", "time", "my", "day", "play"],
        "ipa": "aɪ",
    },
    "EH": {
        "description": "半开前元音，如 bEd 中的 e",
        "common_error": "容易发成 /AE/ 或 /IH/，嘴巴张得过大或过小",
        "solution": "嘴巴半开（约一指宽），嘴角微展，比 /AE/ 窄但比 /IH/ 宽。发短促的 'eh' 音。像说'哎'但嘴更扁。",
        "mouth_shape": "口腔半开，舌前部微抬，嘴角微展",
        "practice_words": ["bed", "red", "get", "says", "friend"],
        "ipa": "ɛ",
    },
    "ER": {
        "description": "卷舌元音，如 bIRd 中的 ir",
        "common_error": "不卷舌或过度卷舌，或发成 /AH/，或像中文'儿'化音",
        "solution": "舌尖微微上翘（不接触上颚），嘴唇微圆。这是美式英语的标志音。注意：舌尖只是微微翘起，不要过度卷曲。英式英语不卷舌。",
        "mouth_shape": "舌微卷（舌尖不上触），唇微圆微突",
        "practice_words": ["bird", "work", "learn", "her", "turn"],
        "ipa": "ɜːr",
    },
    "EY": {
        "description": "双元音，如 dAY 中的 ay",
        "common_error": "滑动不够或发成单元音 /EH/，缺少向 /IY/ 的滑动",
        "solution": "从 /EH/ 滑向 /IY/，嘴巴从半开到合拢。确保有明显的滑动感，不能停留在 /EH/ 上。",
        "mouth_shape": "从半开到扁唇，嘴角从微展到展开",
        "practice_words": ["day", "say", "play", "make", "great"],
        "ipa": "eɪ",
    },
    "IH": {
        "description": "闭前短元音，如 bIt 中的 i",
        "common_error": "容易发成 /IY/（过长过紧）或 /EH/，或用中文'一'替代",
        "solution": "嘴巴微开，嘴角微展，发短促放松的 'ih' 音。注意不要拖长，与 /IY/ 区分开。中文'一'更接近 /IY/ 而非 /IH/。",
        "mouth_shape": "口腔微开，舌前部较高但放松，嘴角微展",
        "practice_words": ["sit", "big", "in", "this", "with"],
        "ipa": "ɪ",
    },
    "IY": {
        "description": "闭前长元音，如 sEE 中的 ee",
        "common_error": "不够长或嘴型不够扁，或发成 /IH/，或用中文'衣'替代",
        "solution": "嘴角用力向两侧拉展，舌尖抵下齿，发长音 'ee'。保持口型稳定，音要持续足够长。比中文'衣'嘴更扁、音更长。",
        "mouth_shape": "扁唇（嘴角用力展），舌前部高抬",
        "practice_words": ["see", "me", "be", "she", "please"],
        "ipa": "iː",
    },
    "OW": {
        "description": "双元音，如 gO 中的 o",
        "common_error": "滑动不够或发成单元音，或用中文'欧'替代",
        "solution": "从 /AH/ 滑向 /UW/，嘴唇从自然到圆。注意滑动过程要明显，不是纯圆唇音。比中文'欧'更强调滑动。",
        "mouth_shape": "从自然放松到圆唇前突",
        "practice_words": ["go", "no", "know", "home", "over"],
        "ipa": "oʊ",
    },
    "OY": {
        "description": "双元音，如 bOY 中的 oy",
        "common_error": "起始音偏错或滑动不够，或发成 /OW/ + /IY/",
        "solution": "从 /OW/ 滑向 /IY/，嘴巴从圆到扁。两个音的过渡要自然流畅，不能断开。",
        "mouth_shape": "从圆唇到扁唇，下巴先降后升",
        "practice_words": ["boy", "enjoy", "toy", "choice", "voice"],
        "ipa": "ɔɪ",
    },
    "UH": {
        "description": "闭后短元音，如 bOOk 中的 oo",
        "common_error": "容易发成 /UW/（太紧太长）或 /AH/，或用中文'乌'替代",
        "solution": "嘴唇微圆但不过度紧张，发短促放松的 'uh' 音。比 /UW/ 更放松、更短。中文'乌'更接近 /UW/。",
        "mouth_shape": "唇微圆但放松，舌后部微抬",
        "practice_words": ["book", "look", "good", "would", "could"],
        "ipa": "ʊ",
    },
    "UW": {
        "description": "闭后长元音，如 fOOd 中的 oo",
        "common_error": "不够圆唇或不够长，或发成 /UH/，或用中文'乌'替代但不够紧",
        "solution": "嘴唇前伸成小圆形（像吹口哨），舌尖远离牙齿，发长音 'oo'。保持圆唇和音长。比中文'乌'嘴唇更突出。",
        "mouth_shape": "唇前突成小圆形，舌后部高抬",
        "practice_words": ["food", "too", "school", "blue", "you"],
        "ipa": "uː",
    },
    # === 塞音 ===
    "B": {
        "description": "浊双唇塞音，如 Ba",
        "common_error": "容易与 /P/ 混淆，声带不振动（受中文 b/p 送气/不送气习惯影响）",
        "solution": "双唇紧闭后突然打开，同时声带振动。把手放在喉咙上感受振动。中文的 b 是不送气清音，英语 /B/ 是浊音——两者完全不同！",
        "mouth_shape": "双唇紧闭后爆破，声带振动",
        "practice_words": ["big", "book", "boy", "about", "table"],
        "ipa": "b",
    },
    "P": {
        "description": "清双唇塞音，如 Pan",
        "common_error": "送气不够，或声带振动（浊化），受中文影响发成不送气音",
        "solution": "双唇紧闭后突然打开，声带不振动，要有明显送气。把手放在嘴前感受气流。词首的 /P/ 送气特别强。",
        "mouth_shape": "双唇紧闭后爆破送气，声带不振动",
        "practice_words": ["pen", "play", "park", "people", "open"],
        "ipa": "p",
    },
    "D": {
        "description": "浊齿龈塞音，如 Da",
        "common_error": "容易与 /T/ 混淆（浊化不够），或位置偏前/偏后",
        "solution": "舌尖抵住上齿龈后突然放开，声带振动。注意舌尖位置要准确在上齿龈（上牙背后的突起处）。",
        "mouth_shape": "舌尖抵上齿龈后爆破，声带振动",
        "practice_words": ["day", "do", "red", "had", "did"],
        "ipa": "d",
    },
    "T": {
        "description": "清齿龈塞音，如 Tan",
        "common_error": "容易浊化（与 /D/ 混淆），或在元音间浊化（美式口音特征）",
        "solution": "舌尖抵住上齿龈后突然放开，声带不振动，送气明显。词首要强送气。注意：美式英语元音间的 t 常变成闪音 /DX/。",
        "mouth_shape": "舌尖抵上齿龈后爆破送气，声带不振动",
        "practice_words": ["time", "take", "today", "water", "get"],
        "ipa": "t",
    },
    "G": {
        "description": "浊软腭塞音，如 Go",
        "common_error": "容易与 /K/ 混淆（浊化不够），或发成 /D/（舌位偏前）",
        "solution": "舌后部抵住软腭后突然放开，声带振动。感受舌根与软腭的接触。与 /K/ 唯一区别是声带振动。",
        "mouth_shape": "舌后部抵软腭后爆破，声带振动",
        "practice_words": ["go", "good", "big", "get", "garden"],
        "ipa": "ɡ",
    },
    "K": {
        "description": "清软腭塞音，如 Kit",
        "common_error": "容易浊化（与 /G/ 混淆），或发成 /T/（舌位偏前）",
        "solution": "舌后部抵住软腭后突然放开，声带不振动，送气要明显。尤其在词首时送气很强。",
        "mouth_shape": "舌后部抵软腭后爆破送气，声带不振动",
        "practice_words": ["can", "come", "take", "make", "book"],
        "ipa": "k",
    },
    # === 擦音 ===
    "F": {
        "description": "清唇齿擦音，如 Fan",
        "common_error": "容易与 /V/ 混淆（声带振动），或上齿没有接触下唇",
        "solution": "上齿轻咬下唇内侧，气流从缝隙中摩擦而出，声带不振动。确认上齿确实接触下唇。对着镜子检查口型。",
        "mouth_shape": "上齿咬下唇，气流摩擦而出",
        "practice_words": ["find", "food", "five", "friend", "life"],
        "ipa": "f",
    },
    "V": {
        "description": "浊唇齿擦音，如 Van",
        "common_error": "容易与 /F/ 混淆（没有声带振动），或发成 /W/（嘴唇不合）",
        "solution": "上齿轻咬下唇内侧，气流从缝隙中摩擦而出，声带振动。把手放在喉咙上感受振动。与 /F/ 口型完全相同，只是多了声带振动。",
        "mouth_shape": "上齿咬下唇，声带振动，气流摩擦",
        "practice_words": ["very", "have", "love", "live", "every"],
        "ipa": "v",
    },
    "S": {
        "description": "清齿龈擦音，如 See",
        "common_error": "容易与 /Z/ 混淆（浊化），或与 /SH/ 混淆（舌位偏后）",
        "solution": "嘴角展开（微笑口型），舌尖靠近上齿龈（不接触），气流从窄缝中嘶嘶而出。保持笑容口型，声音尖锐清脆。",
        "mouth_shape": "嘴角展开，舌尖近上齿龈，气流窄缝而出",
        "practice_words": ["see", "say", "this", "yes", "six"],
        "ipa": "s",
    },
    "Z": {
        "description": "浊齿龈擦音，如 Zoo",
        "common_error": "容易与 /S/ 混淆（没有声带振动），或发成 /DH/",
        "solution": "口型与 /S/ 相同，但声带振动发出 'zzz' 蜂鸣声。像蜜蜂嗡嗡叫。摸喉咙感受振动。",
        "mouth_shape": "嘴角展开，声带振动，舌尖近上齿龈",
        "practice_words": ["zoo", "is", "his", "was", "easy"],
        "ipa": "z",
    },
    "SH": {
        "description": "清齿龈后擦音，如 She",
        "common_error": "容易与 /S/ 混淆（嘴唇不圆），或与 /CH/ 混淆（加了爆破）",
        "solution": "嘴唇前突圆起，舌尖接近硬腭前部，发出 'sh' 嘘声。像让人安静时的声音。注意嘴唇要前突，不像 /S/ 的微笑口型。",
        "mouth_shape": "唇前突圆起，舌近硬腭，持续气流",
        "practice_words": ["she", "shop", "ship", "sure", "special"],
        "ipa": "ʃ",
    },
    "ZH": {
        "description": "浊齿龈后擦音，如 viSion",
        "common_error": "容易与 /SH/ 混淆（没有声带振动），或与 /Z/ 混淆（舌位偏前）",
        "solution": "口型与 /SH/ 相同，但声带振动。像法语中的 'j' 音。声带振动产生蜂鸣感。这个音在英语中出现频率较低。",
        "mouth_shape": "唇前突圆起，声带振动，舌近硬腭",
        "practice_words": ["vision", "measure", "usual", "pleasure", "decision"],
        "ipa": "ʒ",
    },
    "TH": {
        "description": "清齿擦音，如 Think",
        "common_error": "最常见的中国学习者错误！用 /S/、/T/ 或 /F/ 代替",
        "solution": "舌尖伸出上下齿之间（咬舌音），气流从舌齿间吹出。关键：舌尖一定要伸出牙齿外！对着镜子看舌头。感觉像轻轻咬住舌尖吹气。这是英语独有的音。",
        "mouth_shape": "舌尖伸出齿间，气流从舌齿间通过",
        "practice_words": ["think", "three", "thank", "both", "mouth"],
        "ipa": "θ",
    },
    "DH": {
        "description": "浊齿擦音，如 THis",
        "common_error": "最常见的中国学习者错误！用 /Z/、/D/ 或 /V/ 代替",
        "solution": "舌尖伸出上下齿之间，声带振动。与 /TH/ 口型相同但声带振动。'this' 不是 'zis' 或 'dis'。舌尖必须伸出齿外！",
        "mouth_shape": "舌尖伸出齿间，声带振动，气流通过",
        "practice_words": ["this", "that", "the", "them", "with"],
        "ipa": "ð",
    },
    # === 塞擦音 ===
    "CH": {
        "description": "清齿龈后塞擦音，如 CHin",
        "common_error": "容易与 /SH/ 混淆（缺少爆破阶段）或 /JH/ 混淆（浊化）",
        "solution": "先做成 /T/ 的口型（舌尖抵上齿龈），然后释放为 /SH/。先阻塞后摩擦，是一个组合音。注意送气感。",
        "mouth_shape": "舌尖抵上齿龈，然后释放为 /SH/，送气",
        "practice_words": ["child", "choose", "change", "teacher", "each"],
        "ipa": "tʃ",
    },
    "JH": {
        "description": "浊齿龈后塞擦音，如 Jump",
        "common_error": "容易与 /CH/ 混淆（没有声带振动）或 /ZH/ 混淆（缺少爆破）",
        "solution": "先做成 /D/ 的口型，然后释放为 /ZH/。与 /CH/ 口型相同但声带振动。摸喉咙感受振动。",
        "mouth_shape": "舌尖抵上齿龈，声带振动释放为 /ZH/",
        "practice_words": ["jump", "just", "job", "enjoy", "age"],
        "ipa": "dʒ",
    },
    # === 鼻音 ===
    "M": {
        "description": "双唇鼻音，如 Man",
        "common_error": "闭唇不够紧，或发音时间不够长，或发成 /N/",
        "solution": "双唇紧闭，气流从鼻腔出来，声带振动。闭嘴时哼 'mmm' 音。注意嘴唇要完全闭合。",
        "mouth_shape": "双唇紧闭，气流从鼻腔出来",
        "practice_words": ["man", "my", "me", "time", "morning"],
        "ipa": "m",
    },
    "N": {
        "description": "齿龈鼻音，如 No",
        "common_error": "容易与 /NG/ 混淆（尤其在词尾），舌位不准确",
        "solution": "舌尖抵住上齿龈，气流从鼻腔出来。注意 /N/ 舌尖在上齿龈，/NG/ 舌根在软腭。词尾 -n 不要发成 -ng。",
        "mouth_shape": "舌尖抵上齿龈，气流从鼻腔出来",
        "practice_words": ["no", "not", "in", "and", "can"],
        "ipa": "n",
    },
    "NG": {
        "description": "软腭鼻音，如 siNG",
        "common_error": "容易与 /N/ 混淆（尤其在词尾），或在词尾加上 /G/ 音",
        "solution": "舌后部抵住软腭，气流从鼻腔出来。注意词尾的 -ing 不要多发 /G/ 音。'sing' 不是 'sing-g'。南方方言区学习者特别注意 n/ng 不分问题。",
        "mouth_shape": "舌后部抵软腭，气流从鼻腔出来",
        "practice_words": ["sing", "morning", "going", "thing", "reading"],
        "ipa": "ŋ",
    },
    # === 流音和滑音 ===
    "L": {
        "description": "齿龈边音，如 Light",
        "common_error": "容易与 /R/ 混淆（中国学习者最大难点之一），或词尾 dark L 发不好",
        "solution": "舌尖抵住上齿龈，气流从舌头两侧流出。词首的 clear L 舌尖用力抵住；词尾的 dark L 舌尖也抵住但舌后部抬起。关键是舌尖必须接触上齿龈！",
        "mouth_shape": "舌尖抵上齿龈，气流从舌侧流出",
        "practice_words": ["like", "learn", "play", "will", "help"],
        "ipa": "l",
    },
    "R": {
        "description": "齿龈通音/卷舌音，如 Run",
        "common_error": "容易与 /L/ 混淆（中国学习者最大难点之一），或过度卷舌，或发成中文 r",
        "solution": "舌尖向后卷但不接触上颚，嘴唇微圆。注意英语 /R/ 舌尖不接触任何部位，不颤动。与中文 r 完全不同！中文 r 舌尖会接触上颚。",
        "mouth_shape": "舌尖上卷不触上颚，唇微圆前突",
        "practice_words": ["run", "read", "right", "red", "practice"],
        "ipa": "r",
    },
    "W": {
        "description": "双唇滑音，如 We",
        "common_error": "容易与 /V/ 混淆（用唇齿音代替双唇音），或圆唇不够",
        "solution": "嘴唇紧圆前突，然后迅速滑向后续元音。注意 /W/ 是双唇音（两片嘴唇合拢），/V/ 是唇齿音（上齿咬下唇）。二者口型完全不同！",
        "mouth_shape": "双唇紧圆后滑开，快速过渡",
        "practice_words": ["we", "what", "would", "way", "weather"],
        "ipa": "w",
    },
    "Y": {
        "description": "硬腭滑音，如 Yes",
        "common_error": "发音时间过长变成 /IY/，或舌面抬得不够",
        "solution": "舌面前部抬向硬腭，然后迅速滑向后续元音。是一个短暂的滑音，不要停留。像汉语'叶'的起始部分。",
        "mouth_shape": "舌面近硬腭后迅速滑开",
        "practice_words": ["yes", "you", "your", "yesterday", "beyond"],
        "ipa": "j",
    },
    "HH": {
        "description": "声门擦音，如 Hat",
        "common_error": "发音过重变成咳音，或与中文 h 混淆（中文 h 是软腭擦音）",
        "solution": "轻轻呼气，声带不振动。比中文的 h 更轻柔，只是轻微的气流声。英语 /HH/ 位置在声门，中文 h 位置在软腭。",
        "mouth_shape": "声门轻微打开，气流轻轻呼出",
        "practice_words": ["he", "how", "help", "here", "have"],
        "ipa": "h",
    },
    "DX": {
        "description": "齿龈弹音（美式英语 t 的闪音），如 waTer",
        "common_error": "没有弹舌效果，或发成 /D/，或发成标准 /T/",
        "solution": "舌尖快速弹击上齿龈一次，像西班牙语的弹音但只弹一下。美式英语中 t 在元音间常变成此音。'water' 听起来像 'wah-der'。",
        "mouth_shape": "舌尖快速弹击上齿龈一次",
        "practice_words": ["water", "better", "butter", "city", "party"],
        "ipa": "ɾ",
    },
}

# ============================================================
# 音素相似度函数
# ============================================================
def _build_similarity_matrix():
    """构建音素相似度矩阵"""
    vowel_short = {"AA", "AE", "AH", "EH", "IH", "UH"}
    vowel_long = {"AY", "AW", "EY", "OW", "OY", "IY", "UW"}
    vowel_r = {"ER"}
    stops_voiced = {"B", "D", "G"}
    stops_voiceless = {"P", "T", "K"}
    fricatives_voiced = {"V", "Z", "ZH", "DH"}
    fricatives_voiceless = {"F", "S", "SH", "TH"}
    affricates_voiced = {"JH"}
    affricates_voiceless = {"CH"}
    nasals = {"M", "N", "NG"}
    liquids = {"L", "R"}
    glides = {"W", "Y"}
    aspirate = {"HH"}

    groups = [
        vowel_short, vowel_long, vowel_r,
        stops_voiced, stops_voiceless,
        fricatives_voiced, fricatives_voiceless,
        affricates_voiced, affricates_voiceless,
        nasals, liquids, glides, aspirate,
    ]

    def get_similarity(p1, p2):
        if p1 == p2:
            return 1.0
        voiced_pairs = [
            ({"P", "B"}, 0.6), ({"T", "D"}, 0.6), ({"K", "G"}, 0.6),
            ({"F", "V"}, 0.6), ({"S", "Z"}, 0.6), ({"SH", "ZH"}, 0.6),
            ({"TH", "DH"}, 0.6), ({"CH", "JH"}, 0.6),
        ]
        for pair_set, score in voiced_pairs:
            if p1 in pair_set and p2 in pair_set:
                return score
        for group in groups:
            if p1 in group and p2 in group:
                return 0.4
        all_vowels = vowel_short | vowel_long | vowel_r
        all_stops = stops_voiced | stops_voiceless
        all_fricatives = fricatives_voiced | fricatives_voiceless
        all_affricates = affricates_voiced | affricates_voiceless
        big_groups = [all_vowels, all_stops, all_fricatives, all_affricates, nasals, liquids | glides]
        for bg in big_groups:
            if p1 in bg and p2 in bg:
                return 0.25
        return 0.0

    return get_similarity

SIMILARITY_FUNC = _build_similarity_matrix()

# ============================================================
# 自动构建音素→示例词映射
# ============================================================
for _p, _info in PHONEME_TIPS.items():
    _words = _info.get("practice_words", [])
    if _words:
        PHONEME_EXAMPLE_WORD[_p] = _words[0]

# ============================================================
# 间隔重复 SM-2 算法配置
# ============================================================
SM2_CONFIG = {
    "min_easiness": 1.3,   # 最低易度因子
    "initial_interval": 1, # 初始间隔（天）
    "second_interval": 6,  # 第二次间隔（天）
}
