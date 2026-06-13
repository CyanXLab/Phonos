"""
本地 TTS 服务 - 当浏览器 SpeechSynthesis API 失败时使用

优先级：edge-tts（免费高质量在线）→ pyttsx3（离线）→ 生成静音
"""

import os
import sys
import time
import tempfile
import hashlib
import threading
from pathlib import Path
from typing import Optional

_cache_dir = Path(__file__).parent / "tts_cache"
_cache_dir.mkdir(exist_ok=True)


def _get_cache_path(text: str, voice: str = "en-US") -> str:
    """生成缓存文件路径"""
    h = hashlib.md5(f"{voice}:{text}".encode()).hexdigest()
    return str(_cache_dir / f"{h}.mp3")


# edge-tts 可用语音列表（按优先级排序）
_EDGE_VOICES = [
    "en-US-AriaNeural",    # 首选
    "en-US-JennyNeural",   # 备选1
    "en-US-GuyNeural",     # 备选2
    "en-US-DavisNeural",   # 备选3
]

def tts_with_edge(text: str, voice: str = None) -> Optional[str]:
    """使用 edge-tts 生成语音（免费、高质量、需联网）
    
    如果指定 voice 则只尝试该 voice，否则依次尝试多个 voice。
    微软偶尔会封禁某个 voice 或 Token，多 voice 轮询可提高成功率。
    """
    try:
        import edge_tts
    except ImportError:
        print("[TTS] edge-tts 未安装")
        return None

    voices_to_try = [voice] if voice else _EDGE_VOICES
    last_error = None

    for v in voices_to_try:
        if not v:
            continue
        cache_path = _get_cache_path(text, v)
        try:
            # 检查缓存
            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
                return cache_path

            communicate = edge_tts.Communicate(text, v)
            communicate.save_sync(cache_path)

            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
                return cache_path
            else:
                print(f"[TTS] edge-tts({v}) 生成的文件无效")
                # 清理无效文件
                try:
                    os.remove(cache_path)
                except Exception:
                    pass
        except Exception as e:
            last_error = e
            print(f"[TTS] edge-tts({v}) 失败: {e}")
            # 清理可能残留的损坏缓存文件
            if os.path.exists(cache_path):
                try:
                    os.remove(cache_path)
                except Exception:
                    pass
            # 403/401 等鉴权错误，换一个 voice 试试
            error_str = str(e)
            if "403" in error_str or "401" in error_str or "Invalid response" in error_str:
                print(f"[TTS] edge-tts({v}) 鉴权被拒，尝试下一个 voice...")
                continue
            else:
                # 其他错误（网络超时等），不继续尝试
                break

    if last_error:
        print(f"[TTS] 所有 edge-tts voice 均失败，最后一次错误: {last_error}")
    return None


# Flag to track if pyttsx3 actually works (not just importable)
_pyttsx3_available = None
_pyttsx3_check_lock = threading.Lock()


def _check_pyttsx3_available() -> bool:
    """Test if pyttsx3 can actually initialize (not just import)
    
    - Windows/macOS 桌面环境：pyttsx3 通常可以工作，启用它
    - Linux headless/CI 环境：pyttsx3 可能因无音频设备而崩溃，禁用
    - 可通过环境变量 PHONOS_PYTTSX3=1 强制启用，或 PHONOS_PYTTSX3=0 强制禁用
    """
    global _pyttsx3_available
    with _pyttsx3_check_lock:
        if _pyttsx3_available is not None:
            return _pyttsx3_available

        # 环境变量优先
        env_val = os.environ.get("PHONOS_PYTTSX3", "").strip()
        if env_val == "1":
            _pyttsx3_available = True
            print("[TTS] pyttsx3 通过环境变量强制启用")
            return True
        elif env_val == "0":
            _pyttsx3_available = False
            print("[TTS] pyttsx3 通过环境变量强制禁用")
            return False

        # 检测环境：Windows/macOS 桌面 → 启用；Linux headless → 禁用
        is_desktop = (
            sys.platform == "win32" or
            sys.platform == "darwin" or
            os.environ.get("DISPLAY") is not None or
            os.environ.get("WAYLAND_DISPLAY") is not None
        )

        if not is_desktop:
            _pyttsx3_available = False
            print("[TTS] pyttsx3 在无头环境下自动禁用")
            return False

        # 桌面环境：尝试初始化 pyttsx3 验证可用性
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.stop()
            _pyttsx3_available = True
            print("[TTS] pyttsx3 初始化成功，已启用")
        except Exception as e:
            _pyttsx3_available = False
            print(f"[TTS] pyttsx3 初始化失败，已禁用: {e}")

        return _pyttsx3_available


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
        engine.stop()  # 确保释放资源

        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
            return cache_path
        else:
            print(f"[TTS] pyttsx3 生成的文件无效: {cache_path}")
    except Exception as e:
        print(f"[TTS] pyttsx3 失败: {e}")
        # 标记为不可用，避免反复尝试
        global _pyttsx3_available
        _pyttsx3_available = False
    return None


# edge-tts 连续失败计数与冷却（类似翻译服务的降级机制）
_edge_fail_count = 0
_edge_fail_lock = threading.Lock()
_EDGE_SKIP_THRESHOLD = 3      # 连续失败 N 次后跳过 edge-tts
_EDGE_COOLDOWN_SEC = 300      # 冷却时间（秒）
_edge_skip_until = 0.0


def _record_edge_success():
    """edge-tts 调用成功，重置失败计数"""
    global _edge_fail_count, _edge_skip_until
    with _edge_fail_lock:
        _edge_fail_count = 0
        _edge_skip_until = 0.0


def _record_edge_failure():
    """edge-tts 调用失败，增加计数；达到阈值后进入冷却期"""
    global _edge_fail_count, _edge_skip_until
    with _edge_fail_lock:
        _edge_fail_count += 1
        if _edge_fail_count >= _EDGE_SKIP_THRESHOLD:
            _edge_skip_until = time.time() + _EDGE_COOLDOWN_SEC
            print(f"[TTS] edge-tts 连续失败 {_edge_fail_count} 次，冷却 {_EDGE_COOLDOWN_SEC}s")


def _should_skip_edge() -> bool:
    """是否应该跳过 edge-tts（因为连续失败太多）"""
    global _edge_fail_count, _edge_skip_until
    with _edge_fail_lock:
        if _edge_fail_count < _EDGE_SKIP_THRESHOLD:
            return False
        if time.time() > _edge_skip_until:
            # 冷却期已过，重置计数，允许再次尝试
            _edge_fail_count = 0
            _edge_skip_until = 0.0
            return False
        return True


def generate_tts(text: str) -> dict:
    """
    生成 TTS 音频文件

    优先级：edge-tts（在线）→ pyttsx3（离线）→ 生成简短静音提示
    edge-tts 连续失败 ≥ 3 次后进入 5 分钟冷却期，期间跳过在线 TTS。

    返回: {"path": str, "format": str, "source": str} 或 {"error": str}
    """
    if not text or not text.strip():
        return {"error": "文本为空"}

    # 尝试 edge-tts（除非连续失败太多进入冷却期）
    if not _should_skip_edge():
        path = tts_with_edge(text)
        if path:
            _record_edge_success()
            return {"path": path, "format": "mp3", "source": "edge-tts"}
        else:
            _record_edge_failure()
    else:
        print(f"[TTS] edge-tts 冷却中，跳过在线 TTS")

    # 尝试 pyttsx3
    path = tts_with_pyttsx3(text)
    if path:
        return {"path": path, "format": "wav", "source": "pyttsx3"}

    # 最后的降级：生成一个极短的静音 WAV 文件，避免前端 500 错误
    # 前端检测到 source=none 后可以回退到浏览器 SpeechSynthesis
    try:
        import struct, wave
        silence_path = _get_cache_path(text, "silence").replace(".mp3", ".wav")
        if not os.path.exists(silence_path):
            with wave.open(silence_path, 'w') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(16000)
                # 写入 0.1 秒静音
                silence_data = struct.pack('<' + 'h' * 1600, *([0] * 1600))
                wf.writeframes(silence_data)
        return {"path": silence_path, "format": "wav", "source": "none",
                "fallback": "browser_speech"}
    except Exception:
        pass

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
