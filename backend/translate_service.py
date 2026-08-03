"""
翻译服务 - 为没有翻译的句子提供自动翻译

优先级：
1. 本地缓存（已翻译过的）
2. 在线翻译 API（Edge Translator → MyMemory → Google，多次失败后跳过）
3. ONNX 翻译模型（本地 Seq2Seq 模型，在线 API 失败时使用）
4. 简易词典（最后的回退）

在线 API 失败计数器：连续失败 N 次后，暂时跳过在线 API，
直接使用 ONNX 翻译模型，避免浪费时间等待超时。
"""

import json
import os
import re
import hashlib
import threading
import time
from pathlib import Path
from typing import Optional

_CACHE_FILE = Path(__file__).parent / "translation_cache.json"
_cache: dict = {}

# 在线 API 失败计数与冷却
_api_fail_count = 0          # 连续失败次数
_api_fail_lock = threading.Lock()
_API_SKIP_THRESHOLD = 3      # 连续失败 N 次后跳过在线 API
_API_COOLDOWN_SEC = 300      # 冷却时间（秒），之后重新尝试在线 API
_api_skip_until = 0.0        # 跳过在线 API 直到这个时间戳


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
# 在线 API 失败计数管理
# ============================================================
def _record_api_success():
    """在线 API 调用成功，重置失败计数"""
    global _api_fail_count, _api_skip_until
    with _api_fail_lock:
        _api_fail_count = 0
        _api_skip_until = 0.0


def _record_api_failure():
    """在线 API 调用失败，增加计数；达到阈值后进入冷却期"""
    global _api_fail_count, _api_skip_until
    with _api_fail_lock:
        _api_fail_count += 1
        if _api_fail_count >= _API_SKIP_THRESHOLD:
            _api_skip_until = time.time() + _API_COOLDOWN_SEC


def _should_skip_online_apis() -> bool:
    """是否应该跳过在线 API（因为连续失败太多）"""
    global _api_fail_count, _api_skip_until
    with _api_fail_lock:
        if _api_fail_count < _API_SKIP_THRESHOLD:
            return False
        if time.time() > _api_skip_until:
            # 冷却期已过，重置计数，允许再次尝试
            _api_fail_count = 0
            _api_skip_until = 0.0
            return False
        return True


# ============================================================
# Microsoft Edge Translator (MET) — 免费 JWT 认证 + 官方 API
# 2025+ Bing 简单 GET 已失效（403），改用 Edge 浏览器认证通道
# ============================================================
_EDGE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
)

_edge_token = None          # JWT token
_edge_token_expires = 0.0   # token 过期时间（epoch秒）
_edge_token_lock = threading.Lock()


def _fetch_edge_token() -> bool:
    """从 Edge 浏览器认证端点获取免费 JWT token（有效期约10分钟）"""
    global _edge_token, _edge_token_expires
    try:
        import urllib.request
        import base64

        req = urllib.request.Request(
            "https://edge.microsoft.com/translate/auth",
            headers={"User-Agent": _EDGE_USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            token = resp.read().decode("utf-8").strip()
            if not token or len(token) < 20:
                print("[翻译] Edge Token 获取返回空或过短")
                return False

            # 解析 JWT 过期时间
            try:
                payload_b64 = token.split(".")[1]
                payload_b64 += "=" * (4 - len(payload_b64) % 4)
                payload = json.loads(base64.b64decode(payload_b64))
                exp = payload.get("exp", 0)
                _edge_token_expires = exp
            except Exception:
                # 解析失败，保守估计5分钟有效
                _edge_token_expires = time.time() + 300

            _edge_token = token
            print(f"[翻译] Edge Token 获取成功，有效期至 {_edge_token_expires}")
            return True
    except Exception as e:
        print(f"[翻译] Edge Token 获取失败: {e}")
        return False


def _is_edge_token_expired() -> bool:
    """Edge token 是否已过期（提前60秒刷新）"""
    if not _edge_token:
        return True
    return (time.time() + 60) >= _edge_token_expires


def translate_edge(text: str, from_lang: str = "en", to_lang: str = "zh-Hans") -> Optional[str]:
    """使用 Microsoft Edge Translator 免费翻译（官方 API + JWT 认证）"""
    global _edge_token
    try:
        import urllib.request

        with _edge_token_lock:
            if _is_edge_token_expired():
                if not _fetch_edge_token():
                    return None

        # 构造请求：官方 Microsoft Translator API
        to_code = "zh-Hans" if to_lang in ("zh", "zh-CN", "zh-Hans") else to_lang
        url = f"https://api.cognitive.microsofttranslator.com/translate?api-version=3.0&from={from_lang}&to={to_code}"
        body = json.dumps([{"Text": text}]).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers={
            "User-Agent": _EDGE_USER_AGENT,
            "Authorization": f"Bearer {_edge_token}",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 0:
                translations = data[0].get("translations", [])
                if translations:
                    return translations[0].get("text", "")
    except Exception as e:
        print(f"[翻译] Edge Translator 失败: {e}")
        # Token 可能失效，标记为过期以便下次重新获取
        with _edge_token_lock:
            _edge_token = None
    return None


# ============================================================
# MyMemory Translation API（免费，无需 API key，每天5K字符）
# ============================================================
def translate_mymemory(text: str, from_lang: str = "en", to_lang: str = "zh-CN") -> Optional[str]:
    """使用 MyMemory API 翻译（免费，每天5K字符匿名额度）"""
    try:
        import urllib.request
        import urllib.parse

        encoded = urllib.parse.quote(text)
        url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair={from_lang}|{to_lang}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            translated = data.get("responseData", {}).get("translatedText", "")
            # MyMemory 有时会返回大写提示（如 "MYMEMORY WARNING ..."），过滤掉
            if translated and not translated.startswith("MYMEMORY"):
                return translated
    except Exception as e:
        print(f"[翻译] MyMemory 失败: {e}")
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
# ONNX 翻译模型（本地 Seq2Seq 模型，替代 Argos Translate）
# 使用 optimum.onnxruntime ORTModelForSeq2SeqLM 加载
# ============================================================
def translate_onnx(text: str, from_lang: str = "en", to_lang: str = "zh") -> Optional[str]:
    """使用 ONNX 翻译模型本地离线翻译（Seq2Seq + ONNX Runtime）
    
    模型路径与 HuPER 音素模型在同一 models/ 目录下（models/onnx_quant）。
    使用 optimum.onnxruntime ORTModelForSeq2SeqLM + transformers pipeline。
    """
    try:
        from onnx_translate_service import translate_onnx as _onnx_translate
        result = _onnx_translate(text)
        if result and result.strip() and result.strip() != text.strip():
            print(f"[翻译] ONNX 模型翻译成功: {text[:50]} -> {result[:50]}")
            return result.strip()
    except ImportError:
        print("[翻译] onnx_translate_service 模块未找到")
    except Exception as e:
        print(f"[翻译] ONNX 模型翻译失败: {e}")
    return None


def is_onnx_translate_available() -> bool:
    """检查 ONNX 翻译模型是否可用"""
    try:
        from onnx_translate_service import is_onnx_translate_available as _check
        return _check()
    except Exception:
        return False


# ============================================================
# Simple built-in phrase dictionary (last offline fallback)
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
    """简易词典翻译（最后的回退）
    
    改进：只翻译功能词（冠词、介词、代词等），
    实词保持英文原样，避免产出"这/那(spontaneous applause)"这样的乱码。
    """
    words = text.split()
    translated_parts = []
    untranslated = []
    
    for w in words:
        key = re.sub(r'[^a-z]', '', w.lower())
        if key in _SIMPLE_DICT:
            # 功能词有翻译
            if untranslated:
                translated_parts.append(' '.join(untranslated))
                untranslated = []
            translated_parts.append(_SIMPLE_DICT[key])
        else:
            # 实词保持英文
            untranslated.append(w)
    
    if untranslated:
        translated_parts.append(' '.join(untranslated))
    
    if translated_parts:
        # 用自然的方式拼接：翻译的词直接连，未翻译的英文词保持
        result = ''
        for part in translated_parts:
            if result:
                result += ' '
            result += part
        return result if result.strip() else None
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

    优先级：缓存 → [在线API（Edge → MyMemory → Google）] → ONNX翻译模型 → 简易词典

    在线 API 连续失败 ≥ 3 次后，进入 5 分钟冷却期，
    期间直接使用 ONNX 翻译模型，避免等待超时。
    """
    detail = translate_text_detail(text, force)
    return detail["translation"]


def translate_text_detail(text: str, force: bool = False) -> dict:
    """
    翻译英文文本到中文（详细版，返回来源信息）

    返回:
        {
            "original": str,       # 原文
            "translation": str,    # 翻译结果
            "source": str,         # 翻译来源: cache / edge / mymemory / google / onnx / dictionary / none
            "online_api_skipped": bool  # 在线 API 是否被跳过（冷却中）
        }
    """
    ensure_initialized()

    empty_result = {
        "original": text or "",
        "translation": "",
        "source": "none",
        "online_api_skipped": False,
    }

    if not text or not text.strip():
        return empty_result

    # 检查缓存
    key = _cache_key(text)
    if not force and key in _cache:
        return {
            "original": text,
            "translation": _cache[key],
            "source": "cache",
            "online_api_skipped": False,
        }

    # ---- 在线 API 阶段 ----
    online_skipped = _should_skip_online_apis()
    if not online_skipped:
        # 1. 尝试 Microsoft Edge Translator（免费JWT认证+官方API，最稳定）
        result = translate_edge(text)
        if result and result.strip():
            _record_api_success()
            _cache[key] = result
            _save_cache()
            print(f"[翻译] Edge Translator 成功: {text[:40]} -> {result[:40]}")
            return {
                "original": text,
                "translation": result,
                "source": "edge",
                "online_api_skipped": False,
            }

        # 2. 尝试 MyMemory（免费，每天5K字符）
        result = translate_mymemory(text)
        if result and result.strip():
            _record_api_success()
            _cache[key] = result
            _save_cache()
            print(f"[翻译] MyMemory 成功: {text[:40]} -> {result[:40]}")
            return {
                "original": text,
                "translation": result,
                "source": "mymemory",
                "online_api_skipped": False,
            }

        # 3. 尝试 Google（需安装 googletrans）
        result = translate_google(text)
        if result and result.strip():
            _record_api_success()
            _cache[key] = result
            _save_cache()
            print(f"[翻译] Google 成功: {text[:40]} -> {result[:40]}")
            return {
                "original": text,
                "translation": result,
                "source": "google",
                "online_api_skipped": False,
            }

        # 在线 API 全部失败
        _record_api_failure()
        print(f"[翻译] 在线 API 均失败（连续第 {_api_fail_count} 次）")
    else:
        print(f"[翻译] 在线 API 冷却中，跳过")

    # ---- 本地离线翻译阶段 ----
    # 4. 尝试 ONNX 翻译模型（本地 Seq2Seq + ONNX Runtime）
    result = translate_onnx(text)
    if result and result.strip():
        _cache[key] = result
        _save_cache()
        return {
            "original": text,
            "translation": result,
            "source": "onnx",
            "online_api_skipped": online_skipped,
        }

    # 5. 简易词典（最后的回退）
    print(f"[翻译] 所有翻译服务失败，使用简易词典回退: {text[:60]}")
    result = translate_simple(text)
    if result and result.strip():
        _cache[key] = result
        _save_cache()
        return {
            "original": text,
            "translation": result,
            "source": "dictionary",
            "online_api_skipped": online_skipped,
        }

    return empty_result


def get_translate_status() -> dict:
    """获取翻译服务状态信息"""
    onnx_available = is_onnx_translate_available()
    online_skipped = _should_skip_online_apis()

    return {
        "online_api_available": not online_skipped,
        "online_api_skip_reason": "cooldown" if online_skipped else None,
        "onnx_available": onnx_available,
        "simple_dictionary_available": True,
        "fail_count": _api_fail_count,
        "skip_threshold": _API_SKIP_THRESHOLD,
        "cooldown_seconds": _API_COOLDOWN_SEC,
    }
