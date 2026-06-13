"""
翻译服务 - 为没有翻译的句子提供自动翻译

优先级：
1. 本地缓存（已翻译过的）
2. Bing Translate API（免费，无需API key）
3. 本地离线翻译（argos-translate 或简易词典）
"""

import json
import os
import re
import hashlib
from pathlib import Path
from typing import Optional

_CACHE_FILE = Path(__file__).parent / "translation_cache.json"
_cache: dict = {}


def _load_cache():
    global _cache
    if _CACHE_FILE.exists():
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}


def _save_cache():
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _cache_key(text: str) -> str:
    return hashlib.md5(text.lower().strip().encode()).hexdigest()


# ============================================================
# Bing Translate (free, no API key needed)
# ============================================================
def translate_bing(text: str, from_lang: str = "en", to_lang: str = "zh-Hans") -> Optional[str]:
    """使用必应翻译API（免费，无需API key）"""
    try:
        import urllib.request
        import urllib.parse
        import json as _json

        # Bing翻译的免费接口
        req = urllib.request.Request(
            f"https://www.bing.com/ttranslatev3?fromLang={from_lang}&to={to_lang}&text={urllib.parse.quote(text)}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 0:
                return data[0].get("translations", [{}])[0].get("text", "")
            elif isinstance(data, dict):
                return data.get("translations", [{}])[0].get("text", "")
    except Exception:
        pass
    return None


# ============================================================
# Argos Translate (offline)
# ============================================================
def translate_argos(text: str, from_lang: str = "en", to_lang: str = "zh") -> Optional[str]:
    """使用 argos-translate 离线翻译"""
    try:
        from argostranslate import translate
        translated = translate.translate(text, from_lang, to_lang)
        if translated and translated != text:
            return translated
    except ImportError:
        pass
    except Exception:
        pass
    return None


# ============================================================
# Google Translate (free tier via googletrans)
# ============================================================
def translate_google(text: str, from_lang: str = "en", to_lang: str = "zh-CN") -> Optional[str]:
    """使用 googletrans 翻译（免费但可能不稳定）"""
    try:
        from googletrans import Translator
        translator = Translator()
        result = translator.translate(text, src=from_lang, dest=to_lang)
        if result and result.text:
            return result.text
    except ImportError:
        pass
    except Exception:
        pass
    return None


# ============================================================
# Simple built-in phrase dictionary (offline fallback)
# ============================================================
_SIMPLE_DICT = {
    "the": "这/那", "a": "一个", "an": "一个", "is": "是", "are": "是", "was": "是(过去)",
    "were": "是(过去)", "am": "是", "be": "是", "been": "曾是", "being": "正在是",
    "have": "有", "has": "有", "had": "有(过去)", "do": "做", "does": "做", "did": "做(过去)",
    "will": "将会", "would": "会", "shall": "将", "should": "应该", "can": "能", "could": "能",
    "may": "可能", "might": "可能", "must": "必须", "need": "需要",
    "i": "我", "you": "你", "he": "他", "she": "她", "it": "它", "we": "我们", "they": "他们",
    "my": "我的", "your": "你的", "his": "他的", "her": "她的", "its": "它的", "our": "我们的",
    "their": "他们的", "me": "我(宾格)", "him": "他(宾格)", "us": "我们(宾格)", "them": "他们(宾格)",
    "this": "这个", "that": "那个", "these": "这些", "those": "那些",
    "what": "什么", "which": "哪个", "who": "谁", "whom": "谁(宾格)", "whose": "谁的",
    "where": "哪里", "when": "什么时候", "why": "为什么", "how": "怎样",
    "and": "和", "but": "但是", "or": "或者", "not": "不", "no": "不", "yes": "是",
    "if": "如果", "then": "那么", "so": "所以", "because": "因为",
    "in": "在...里", "on": "在...上", "at": "在", "to": "到", "from": "从",
    "with": "和...一起", "by": "通过/在...旁", "for": "为了", "of": "...的",
    "about": "关于", "into": "进入", "through": "通过", "during": "在...期间",
    "before": "在...之前", "after": "在...之后", "between": "在...之间",
    "up": "上", "down": "下", "out": "外", "off": "离开", "over": "在...上方",
    "under": "在...下方", "again": "再次", "also": "也", "just": "只是",
    "very": "非常", "much": "很多", "more": "更多", "most": "最",
    "some": "一些", "any": "任何", "all": "所有", "each": "每个", "every": "每个",
    "many": "许多", "few": "少", "little": "小/少", "big": "大", "small": "小",
    "good": "好", "bad": "坏", "new": "新", "old": "旧", "long": "长", "short": "短",
    "great": "伟大的", "right": "对/右", "well": "好地", "still": "仍然",
    "here": "这里", "there": "那里", "now": "现在", "today": "今天",
    "always": "总是", "never": "从不", "often": "经常", "sometimes": "有时",
    "only": "只有", "really": "真的", "already": "已经", "yet": "还",
}

def translate_simple(text: str) -> Optional[str]:
    """简易词典翻译（最后的回退）"""
    words = re.sub(r'[^a-z\s]', '', text.lower()).split()
    translated = []
    for w in words:
        if w in _SIMPLE_DICT:
            translated.append(_SIMPLE_DICT[w])
        else:
            translated.append(f"({w})")
    if translated:
        result = "".join(translated)
        # 简单清理连续括号
        result = re.sub(r'\)\(', " ", result)
        return result
    return None


# ============================================================
# Main translation function
# ============================================================
_translate_initialized = False

def ensure_initialized():
    global _translate_initialized
    if not _translate_initialized:
        _load_cache()
        _translate_initialized = True


def translate_text(text: str, force: bool = False) -> str:
    """
    翻译英文文本到中文

    优先级：缓存 → Bing → Google → Argos → 简易词典
    """
    ensure_initialized()

    if not text or not text.strip():
        return ""

    # 检查缓存
    key = _cache_key(text)
    if not force and key in _cache:
        return _cache[key]

    # 1. 尝试 Bing
    result = translate_bing(text)
    if result and result.strip():
        _cache[key] = result
        _save_cache()
        return result

    # 2. 尝试 Google
    result = translate_google(text)
    if result and result.strip():
        _cache[key] = result
        _save_cache()
        return result

    # 3. 尝试 Argos (离线)
    result = translate_argos(text)
    if result and result.strip():
        _cache[key] = result
        _save_cache()
        return result

    # 4. 简易词典
    result = translate_simple(text)
    if result and result.strip():
        _cache[key] = result
        _save_cache()
        return result

    return ""
