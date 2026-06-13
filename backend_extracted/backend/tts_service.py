"""
本地 TTS 服务 - 当浏览器 SpeechSynthesis API 失败时使用

优先级：edge-tts（免费高质量在线）→ pyttsx3（离线）→ 生成静音
"""

import os
import tempfile
import hashlib
from pathlib import Path
from typing import Optional

_cache_dir = Path(__file__).parent / "tts_cache"
_cache_dir.mkdir(exist_ok=True)


def _get_cache_path(text: str, voice: str = "en-US") -> str:
    """生成缓存文件路径"""
    h = hashlib.md5(f"{voice}:{text}".encode()).hexdigest()
    return str(_cache_dir / f"{h}.mp3")


def tts_with_edge(text: str, voice: str = "en-US-AriaNeural") -> Optional[str]:
    """使用 edge-tts 生成语音（免费、高质量、需联网）"""
    try:
        import edge_tts
        cache_path = _get_cache_path(text, voice)
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
            return cache_path

        communicate = edge_tts.Communicate(text, voice)
        communicate.save_sync(cache_path)

        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
            return cache_path
    except Exception:
        pass
    return None


# Flag to track if pyttsx3 actually works (not just importable)
_pyttsx3_available = None

def _check_pyttsx3_available() -> bool:
    """Test if pyttsx3 can actually initialize (not just import)
    
    Note: In headless/server environments, pyttsx3.init() can cause crashes
    because it tries to access audio devices. We disable it by default in
    server environments and rely on browser TTS instead.
    """
    global _pyttsx3_available
    if _pyttsx3_available is not None:
        return _pyttsx3_available
    # Disable pyttsx3 in server environments - it causes crashes
    # Browser TTS is the primary method anyway
    _pyttsx3_available = False
    return False


def tts_with_pyttsx3(text: str) -> Optional[str]:
    """使用 pyttsx3 生成语音（离线、质量一般）"""
    if not _check_pyttsx3_available():
        return None
    try:
        import pyttsx3
        cache_path = _get_cache_path(text, "pyttsx3").replace(".mp3", ".wav")

        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
            return cache_path

        engine = pyttsx3.init()
        # 设置美式英语
        voices = engine.getProperty('voices')
        for v in voices:
            if 'english' in v.name.lower() or 'en' in v.id.lower():
                engine.setProperty('voice', v.id)
                break
        engine.setProperty('rate', 140)
        engine.save_to_file(text, cache_path)
        engine.runAndWait()

        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
            return cache_path
    except Exception:
        pass
    return None


def generate_tts(text: str) -> dict:
    """
    生成 TTS 音频文件

    返回: {"path": str, "format": str, "source": str} 或 {"error": str}
    """
    if not text or not text.strip():
        return {"error": "文本为空"}

    # 尝试 edge-tts
    path = tts_with_edge(text)
    if path:
        return {"path": path, "format": "mp3", "source": "edge-tts"}

    # 尝试 pyttsx3
    path = tts_with_pyttsx3(text)
    if path:
        return {"path": path, "format": "wav", "source": "pyttsx3"}

    return {"error": "所有 TTS 引擎均不可用，请安装 edge-tts 或 pyttsx3"}


# 音素→发音文本映射（生成孤立的音素发音，而非整词）
# 使用更具描述性的发音提示词，帮助 TTS 引擎生成更接近孤立音素的发音
_PHONEME_PRONUNCIATION = {
    # 元音 - 使用自然英语发音词
    "AA": "ah, as in father", "AE": "aa, as in cat", "AH": "uh, as in about",
    "AW": "ow, as in how", "AY": "eye, as in my",
    "EH": "eh, as in bed", "ER": "ur, as in bird", "EY": "ay, as in day",
    "IH": "ih, as in sit", "IY": "ee, as in see",
    "OW": "oh, as in go", "OY": "oy, as in boy", "UH": "oo, as in book",
    "UW": "oo, as in food",
    # 塞音 - 加轻微元音使 TTS 能发声
    "B": "buh", "D": "duh", "G": "guh", "K": "kuh", "P": "puh", "T": "tuh",
    # 擦音 - 持续音
    "F": "fff", "V": "vvv", "S": "sss", "Z": "zzz",
    "SH": "shh", "ZH": "zh", "TH": "thh", "DH": "dh",
    "HH": "hah",
    # 塞擦音
    "CH": "ch", "JH": "jh",
    # 鼻音
    "M": "mmm", "N": "nnn", "NG": "ng",
    # 流音和滑音
    "L": "lll", "R": "rrr", "W": "woo", "Y": "yee",
    # 闪音
    "DX": "dd",
}

# 更简洁的发音文本（用于 edge-tts，效果更好）
_PHONEME_SHORT = {
    "AA": "ah", "AE": "aah", "AH": "uh", "AW": "ow", "AY": "eye",
    "EH": "eh", "ER": "ur", "EY": "ay", "IH": "ih", "IY": "ee",
    "OW": "oh", "OY": "oy", "UH": "oo", "UW": "oo",
    "B": "buh", "D": "duh", "G": "guh", "K": "kuh", "P": "puh", "T": "tuh",
    "F": "fff", "V": "vvv", "S": "sss", "Z": "zzz",
    "SH": "shh", "ZH": "zh", "TH": "thh", "DH": "dh",
    "HH": "hah", "CH": "ch", "JH": "jh",
    "M": "mmm", "N": "nnn", "NG": "ng",
    "L": "lll", "R": "rrr", "W": "woo", "Y": "yee",
    "DX": "dd",
}

# 音素对应的示例词（用于 TTS 回退时生成更自然的发音）
_PHONEME_WORD = {
    "AA": "father", "AE": "cat", "AH": "about", "AW": "how", "AY": "my",
    "EH": "bed", "ER": "bird", "EY": "day", "IH": "sit", "IY": "see",
    "OW": "go", "OY": "boy", "UH": "book", "UW": "food",
    "B": "big", "D": "day", "G": "go", "K": "can", "P": "pen", "T": "time",
    "F": "five", "V": "very", "S": "see", "Z": "zoo",
    "SH": "she", "ZH": "vision", "TH": "think", "DH": "this",
    "HH": "hello", "CH": "chair", "JH": "jump",
    "M": "man", "N": "no", "NG": "sing",
    "L": "light", "R": "red", "W": "we", "Y": "yes",
    "DX": "water",
}


def generate_phoneme_audio(phoneme: str) -> Optional[str]:
    """
    为单个音素生成发音音频

    策略：
    1. 使用音素专属发音文本（如 "ah", "sss", "buh"）生成孤立音素
    2. 回退：使用音素对应的示例词生成发音
    """
    # 策略1：使用音素专属发音文本
    pron_text = _PHONEME_SHORT.get(phoneme)

    if pron_text:
        # 使用特殊的缓存路径前缀区分音素发音和普通TTS
        cache_path = _get_cache_path(f"__phoneme__{phoneme}", "phoneme")
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
            return cache_path

        result = generate_tts(pron_text)
        if "path" in result:
            # 复制到音素专用缓存路径
            import shutil
            try:
                shutil.copy2(result["path"], cache_path)
                return cache_path
            except Exception:
                return result["path"]

    # 策略2：使用示例词生成发音（回退方案）
    word = _PHONEME_WORD.get(phoneme)
    if word:
        cache_path = _get_cache_path(f"__phoneme_word__{phoneme}", "phoneme-word")
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
            return cache_path

        result = generate_tts(word)
        if "path" in result:
            import shutil
            try:
                shutil.copy2(result["path"], cache_path)
                return cache_path
            except Exception:
                return result["path"]

    # 策略3：从 PHONEME_TIPS 获取练习词
    from phoneme_data import PHONEME_TIPS
    info = PHONEME_TIPS.get(phoneme)
    if info:
        practice_words = info.get("practice_words", [])
        if practice_words:
            word = practice_words[0]
            result = generate_tts(word)
            if "path" in result:
                return result["path"]

    return None


# 检查可用 TTS 引擎
def check_tts_available() -> dict:
    """检查 TTS 引擎可用性"""
    engines = {"edge_tts": False, "pyttsx3": False}

    try:
        import edge_tts
        engines["edge_tts"] = True
    except ImportError:
        pass

    try:
        engines["pyttsx3"] = _check_pyttsx3_available()
    except Exception:
        pass

    return engines
