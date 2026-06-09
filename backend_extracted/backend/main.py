"""
Phonos 口语练习平台 - FastAPI 后端
"""

import os
import sys
import traceback
import tempfile
import random
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from phoneme_data import (
    PRESET_SENTENCES, WORD_DICT, PHONEME_TIPS, MINIMAL_PAIRS,
    ARPABET_TO_IPA, VOCAB, PHONEME_EXAMPLE_WORD,
    update_phoneme_cache,
)
from g2p_service import get_g2p_service, G2PService
from onnx_service import get_recognizer
from scoring import evaluate_pronunciation, generate_error_tips, result_to_dict
from fsrs_db import get_fsrs_db
from tts_service import generate_tts, generate_phoneme_audio, check_tts_available
from dict_service import get_dict_service
from translate_service import translate_text

app = FastAPI(title="Phonos 口语练习平台", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 模型路径：优先读环境变量，否则在项目根目录的 model/ 子目录中查找
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

def _find_model() -> str:
    """自动查找 ONNX 模型文件"""
    env_path = os.environ.get("HUPER_MODEL_PATH", "")
    if env_path and os.path.isfile(env_path):
        return env_path

    # 按优先级搜索
    search_paths = [
        _PROJECT_ROOT / "models" / "model.onnx",
        _PROJECT_ROOT / "models" / "model_quantized.onnx",
        _SCRIPT_DIR / "models" / "model.onnx",
        _SCRIPT_DIR / "models" / "model_quantized.onnx",
        _PROJECT_ROOT / "huper_onnx" / "model.onnx",
        _PROJECT_ROOT / "huper_onnx_int8_dynamic" / "model_quantized.onnx",
    ]
    for p in search_paths:
        if p.is_file():
            return str(p)

    return ""

MODEL_PATH = _find_model()
_phoneme_cache: dict = {}


@app.on_event("startup")
async def startup():
    print("[启动] 初始化 Phonos 口语练习平台...")

    # 1. 加载句子（从 JSON 文件，触发 PRESET_SENTENCES 延迟加载）
    print(f"[启动] 句子数据加载完成，共 {len(PRESET_SENTENCES)} 个预设句子")

    # 2. 初始化 G2P 服务（需要在音素缓存更新之前）
    g2p = get_g2p_service()
    print(f"[启动] G2P 服务就绪 (g2p_en: {'可用' if g2p.available else '不可用，使用词典'})")

    # 3. 增量更新音素缓存（传入句子和 G2P 服务）
    global _phoneme_cache
    _phoneme_cache = update_phoneme_cache(PRESET_SENTENCES, g2p)
    print("[启动] 音素缓存更新完成")

    # 4. 加载 ONNX 模型
    if MODEL_PATH and os.path.exists(MODEL_PATH):
        try:
            get_recognizer(MODEL_PATH)
            print(f"[启动] ONNX 模型加载成功: {MODEL_PATH}")
        except Exception as e:
            print(f"[启动] ONNX 模型加载失败: {e}")
    else:
        print("[启动] ⚠️  未找到 ONNX 模型，请将模型文件放到以下位置之一:")
        print(f"         - {_PROJECT_ROOT / 'model' / 'model.onnx'}")
        print(f"         - {_PROJECT_ROOT / 'model' / 'model_quantized.onnx'}")
        print("         或设置环境变量 HUPER_MODEL_PATH 指定模型路径")

    # 5. 初始化 FSRS 数据库，为所有句子创建卡片
    try:
        fsrs = get_fsrs_db()
        for sentence in PRESET_SENTENCES:
            card_id = f"sentence_{sentence['id']}"
            fsrs.ensure_card(card_id, card_type="sentence")
        print(f"[启动] FSRS 数据库初始化完成，已为 {len(PRESET_SENTENCES)} 个句子创建卡片")
    except Exception as e:
        print(f"[启动] ⚠️  FSRS 数据库初始化失败: {e}")

    # 6. 检查 TTS 可用性
    tts_status = check_tts_available()
    available_engines = [k for k, v in tts_status.items() if v]
    if available_engines:
        print(f"[启动] TTS 服务可用: {', '.join(available_engines)}")
    else:
        print("[启动] ⚠️  TTS 服务不可用，请安装 edge-tts 或 pyttsx3")

    print("[启动] 平台初始化完成")


# ============================================================
# API 路由
# ============================================================

@app.get("/api/health")
async def health_check():
    model_ok = MODEL_PATH != "" and os.path.exists(MODEL_PATH)
    try:
        get_recognizer()
        model_loaded = True
    except:
        model_loaded = False

    tts_status = check_tts_available()

    return {
        "status": "ok",
        "model_loaded": model_loaded or model_ok,
        "g2p_available": get_g2p_service().available,
        "tts_available": tts_status,
        "fsrs_available": True,
    }


@app.get("/api/sentence")
async def get_random_sentence(force_new: bool = Query(False, description="强制获取新句子，跳过FSRS")):
    """获取练习句子（FSRS 优先，混合复习和新句子）"""
    # force_new 模式：跳过 FSRS，直接随机
    if force_new:
        sentence = random.choice(PRESET_SENTENCES)
        return _enrich_sentence(sentence)

    # 尝试从 FSRS 获取复习队列
    try:
        fsrs = get_fsrs_db()
        queue = fsrs.get_review_queue(card_type="sentence", new_per_day=5)

        if queue:
            # 优先选择到期的复习卡片
            review_cards = [q for q in queue if q["type"] == "review"]
            new_cards = [q for q in queue if q["type"] == "new"]

            # 如果有到期复习卡片，随机选一个
            if review_cards:
                chosen = random.choice(review_cards)
                card_id = chosen["card_id"]
                # card_id 格式为 "sentence_{id}" 或句子文本
                sentence = _find_sentence_by_card_id(card_id)
                if sentence:
                    result = _enrich_sentence(sentence)
                    result["fsrs"] = chosen
                    return result

            # 如果没有到期复习卡片，从新卡片中选
            if new_cards:
                chosen = random.choice(new_cards)
                card_id = chosen["card_id"]
                sentence = _find_sentence_by_card_id(card_id)
                if sentence:
                    result = _enrich_sentence(sentence)
                    result["fsrs"] = chosen
                    return result

        # 如果队列为空，选择尚未加入 FSRS 的句子
        fsrs_card_ids = set()
        try:
            # 获取所有已存在的卡片 ID
            import sqlite3
            conn = sqlite3.connect(fsrs.db_path)
            rows = conn.execute("SELECT card_id FROM cards WHERE card_type='sentence'").fetchall()
            fsrs_card_ids = {r[0] for r in rows}
            conn.close()
        except Exception:
            pass

        unregistered = [
            s for s in PRESET_SENTENCES
            if f"sentence_{s['id']}" not in fsrs_card_ids
        ]
        if unregistered:
            sentence = random.choice(unregistered)
            # 自动注册到 FSRS
            fsrs.ensure_card(f"sentence_{sentence['id']}", card_type="sentence")
            return _enrich_sentence(sentence)

    except Exception as e:
        print(f"[FSRS] 获取复习队列失败，回退到随机模式: {e}")

    # 回退：随机选择
    sentence = random.choice(PRESET_SENTENCES)
    return _enrich_sentence(sentence)


@app.get("/api/sentences")
async def get_all_sentences():
    """获取所有练习句子"""
    return [_enrich_sentence(s) for s in PRESET_SENTENCES]


@app.get("/api/sentence/{sentence_id}")
async def get_sentence_by_id(sentence_id: int):
    """按ID获取句子"""
    for s in PRESET_SENTENCES:
        if s["id"] == sentence_id:
            return _enrich_sentence(s)
    raise HTTPException(status_code=404, detail="句子不存在")


@app.get("/api/minimal-pairs")
async def get_minimal_pairs():
    """获取最小对立对数据"""
    return MINIMAL_PAIRS


@app.get("/api/phoneme-tips")
async def get_phoneme_tips():
    """获取全部44个音素的发音指南"""
    result = {}
    for phoneme, info in PHONEME_TIPS.items():
        result[phoneme] = {
            "description": info["description"],
            "ipa": info.get("ipa", ARPABET_TO_IPA.get(phoneme, "")),
            "common_error": info["common_error"],
            "solution": info["solution"],
            "mouth_shape": info["mouth_shape"],
            "practice_words": info.get("practice_words", []),
        }
    return result


# ============================================================
# FSRS 间隔重复 API
# ============================================================

@app.post("/api/fsrs/review")
async def fsrs_review(data: dict):
    """提交 FSRS 复习评分

    Body: {"card_id": str, "rating": int(1-4), "card_type": "sentence"}
    Rating: 1=Again, 2=Hard, 3=Good, 4=Easy
    """
    card_id = data.get("card_id")
    rating = data.get("rating")
    card_type = data.get("card_type", "sentence")

    if not card_id:
        raise HTTPException(status_code=400, detail="缺少 card_id")
    if rating not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="rating 必须为 1-4（Again/Hard/Good/Easy）")

    try:
        fsrs = get_fsrs_db()
        result = fsrs.review_card(card_id, rating, card_type)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"复习记录失败: {str(e)}")


@app.get("/api/fsrs/queue")
async def fsrs_queue(
    card_type: str = Query("sentence", description="卡片类型"),
    new_per_day: int = Query(5, description="每日新卡片数量"),
):
    """获取 FSRS 复习队列"""
    try:
        fsrs = get_fsrs_db()
        queue = fsrs.get_review_queue(card_type=card_type, new_per_day=new_per_day)
        return {"queue": queue, "total": len(queue)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取复习队列失败: {str(e)}")


@app.get("/api/fsrs/stats")
async def fsrs_stats():
    """获取 FSRS 学习统计"""
    try:
        fsrs = get_fsrs_db()
        return fsrs.get_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")


@app.get("/api/fsrs/next")
async def fsrs_next(card_type: str = Query("sentence", description="卡片类型")):
    """获取下一个 FSRS 句子（复习队列优先，然后新句子）"""
    try:
        fsrs = get_fsrs_db()
        queue = fsrs.get_review_queue(card_type=card_type, new_per_day=5)

        if queue:
            # 优先选择到期的复习卡片
            review_cards = [q for q in queue if q["type"] == "review"]
            new_cards = [q for q in queue if q["type"] == "new"]

            chosen = None
            if review_cards:
                chosen = random.choice(review_cards)
                sentence_type = "review"
            elif new_cards:
                chosen = random.choice(new_cards)
                sentence_type = "new"

            if chosen:
                card_id = chosen["card_id"]
                sentence = _find_sentence_by_card_id(card_id)
                if sentence:
                    result = _enrich_sentence(sentence)
                    result["fsrs"] = chosen
                    return {"sentence": result, "type": sentence_type}

        # 如果队列为空，随机选择
        sentence = random.choice(PRESET_SENTENCES)
        result = _enrich_sentence(sentence)
        return {"sentence": result, "type": "new"}

    except Exception as e:
        # 回退到随机
        sentence = random.choice(PRESET_SENTENCES)
        result = _enrich_sentence(sentence)
        return {"sentence": result, "type": "new"}


@app.get("/api/fsrs/due-count")
async def fsrs_due_count(card_type: str = Query("sentence", description="卡片类型")):
    """获取到期复习卡片数量"""
    try:
        fsrs = get_fsrs_db()
        due_cards = fsrs.get_due_cards(card_type=card_type)
        return {"count": len(due_cards)}
    except Exception:
        return {"count": 0}


@app.post("/api/fsrs/ensure")
async def fsrs_ensure(data: dict):
    """确保卡片存在于 FSRS 数据库

    Body: {"card_ids": [str], "card_type": "sentence"}
    """
    card_ids = data.get("card_ids", [])
    card_type = data.get("card_type", "sentence")

    if not card_ids:
        raise HTTPException(status_code=400, detail="缺少 card_ids")

    try:
        fsrs = get_fsrs_db()
        created = []
        for card_id in card_ids:
            fsrs.ensure_card(card_id, card_type)
            created.append(card_id)
        return {"created": created, "total": len(created)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建卡片失败: {str(e)}")


# ============================================================
# IPA 标准发音音频 API（使用上传的 IPA 音频文件）
# ============================================================

# ARPAbet → IPA 音频文件映射
_IPA_AUDIO_DIR = _SCRIPT_DIR / "ipa_audio"
_ARPABET_TO_AUDIO = {
    # Vowels
    'AA': _IPA_AUDIO_DIR / "vowels" / "Open_back_unrounded_vowel_ɑ.ogg.mp3",
    'AE': _IPA_AUDIO_DIR / "vowels" / "Near-open_front_unrounded_vowel_æ.ogg.mp3",
    'AH': _IPA_AUDIO_DIR / "vowels" / "Mid-central_vowel_ə.ogg.mp3",
    'AO': _IPA_AUDIO_DIR / "vowels" / "Open-mid_back_rounded_vowel_ɔ.ogg.mp3",
    'AW': None,  # diphthong aʊ - no single file, will combine
    'AY': None,  # diphthong aɪ - no single file
    'EH': _IPA_AUDIO_DIR / "vowels" / "Open-mid_front_unrounded_vowel_ɛ.ogg.mp3",
    'ER': _IPA_AUDIO_DIR / "vowels" / "Open-mid_central_unrounded_vowel_ɜ.ogg.mp3",
    'EY': None,  # diphthong eɪ - no single file
    'IH': _IPA_AUDIO_DIR / "vowels" / "Near-close_near-front_unrounded_vowel_ɪ.ogg.mp3",
    'IY': _IPA_AUDIO_DIR / "vowels" / "Close_front_unrounded_vowel_i.ogg.mp3",
    'OW': None,  # diphthong oʊ - no single file
    'OY': None,  # diphthong ɔɪ - no single file
    'UH': _IPA_AUDIO_DIR / "vowels" / "Near-close_near-back_rounded_vowel_ʊ.ogg.mp3",
    'UW': _IPA_AUDIO_DIR / "vowels" / "Close_back_rounded_vowel_u.ogg.mp3",
    # Consonants
    'P': _IPA_AUDIO_DIR / "consonants" / "archive" / "Voiceless_bilabial_plosive.ogg.mp3",
    'B': _IPA_AUDIO_DIR / "consonants" / "archive" / "Voiced_bilabial_plosive.ogg.mp3",
    'T': _IPA_AUDIO_DIR / "consonants" / "Voiceless_alveolar_plosive_t.ogg.mp3",
    'D': _IPA_AUDIO_DIR / "consonants" / "Voiced_alveolar_plosive_d.ogg.mp3",
    'K': _IPA_AUDIO_DIR / "consonants" / "Voiceless_velar_plosive_k.ogg.mp3",
    'G': _IPA_AUDIO_DIR / "consonants" / "Voiced_velar_plosive_g.ogg.mp3",
    'F': _IPA_AUDIO_DIR / "consonants" / "Voiceless_labio-dental_fricative_f.ogg.mp3",
    'V': _IPA_AUDIO_DIR / "consonants" / "Voiced_labio-dental_fricative_v.ogg.mp3",
    'S': _IPA_AUDIO_DIR / "consonants" / "Voiceless_alveolar_sibilant_s.ogg.mp3",
    'Z': _IPA_AUDIO_DIR / "consonants" / "Voiced_alveolar_sibilant_z.ogg.mp3",
    'SH': _IPA_AUDIO_DIR / "consonants" / "Voiceless_palato-alveolar_sibilant_ʃ.ogg.mp3",
    'ZH': _IPA_AUDIO_DIR / "consonants" / "Voiced_palato-alveolar_sibilant_ʒ.ogg.mp3",
    'TH': _IPA_AUDIO_DIR / "consonants" / "Voiceless_dental_fricative_θ.ogg.mp3",
    'DH': _IPA_AUDIO_DIR / "consonants" / "Voiced_dental_fricative_ð.ogg.mp3",
    'CH': None,  # affricate tʃ - no single file
    'JH': None,  # affricate dʒ - no single file
    'M': _IPA_AUDIO_DIR / "consonants" / "Bilabial_nasal_m.ogg.mp3",
    'N': _IPA_AUDIO_DIR / "consonants" / "Alveolar_nasal_n.ogg.mp3",
    'NG': _IPA_AUDIO_DIR / "consonants" / "Velar_nasal_ŋ.ogg.mp3",
    'L': _IPA_AUDIO_DIR / "consonants" / "Voiced_alveolar_lateral_approximant_l.ogg.mp3",
    'R': _IPA_AUDIO_DIR / "consonants" / "archive" / "Alveolar_approximant_ɹ.ogg.mp3",
    'W': _IPA_AUDIO_DIR / "consonants" / "archive" / "Voiced_labio-velar_approximant.ogg.mp3",
    'Y': _IPA_AUDIO_DIR / "consonants" / "Voiced_palatal_approximant_j.ogg.mp3",
    'HH': _IPA_AUDIO_DIR / "consonants" / "Voiced_glottal_fricative_h.ogg.mp3",
}

# Diphthong and affricate components (play two sounds sequentially)
_DIPHTHONG_COMPONENTS = {
    'AW': ('AA', 'UW'),   # aʊ
    'AY': ('AA', 'IY'),   # aɪ
    'EY': ('EH', 'IY'),   # eɪ
    'OW': ('AO', 'UW'),   # oʊ
    'OY': ('AO', 'IY'),   # ɔɪ
    'CH': ('T', 'SH'),    # tʃ
    'JH': ('D', 'ZH'),    # dʒ
}


@app.get("/api/ipa-audio/{arpabet}")
async def ipa_audio_endpoint(arpabet: str):
    """获取 ARPAbet 音素对应的标准 IPA 发音音频

    优先使用上传的 IPA 音频文件（真实人声录音），
    如果没有对应文件则回退到 TTS 合成。
    """
    arpabet = arpabet.upper().strip()

    # 1. 直接查找对应音频文件
    audio_path = _ARPABET_TO_AUDIO.get(arpabet)
    if audio_path and audio_path.is_file():
        return FileResponse(str(audio_path), media_type="audio/mpeg")

    # 2. 双元音/塞擦音：返回第一个成分的音频（前端会顺序播放两个）
    components = _DIPHTHONG_COMPONENTS.get(arpabet)
    if components:
        comp_paths = []
        for comp in components:
            p = _ARPABET_TO_AUDIO.get(comp)
            if p and p.is_file():
                comp_paths.append(f"/api/ipa-audio/{comp}")
        if comp_paths:
            return {
                "type": "composite",
                "components": comp_paths,
                "message": f"/{ARPABET_TO_IPA.get(arpabet, arpabet)}/ is a diphthong/affricate, playing component sounds"
            }

    # 3. 回退到 TTS 合成
    tts_path = generate_phoneme_audio(arpabet)
    if tts_path and os.path.exists(tts_path):
        media_type = "audio/mpeg" if tts_path.endswith(".mp3") else "audio/wav"
        return FileResponse(tts_path, media_type=media_type)

    raise HTTPException(status_code=404, detail=f"无音频: {arpabet}")


@app.get("/api/ipa-audio-info")
async def ipa_audio_info():
    """返回所有可用的音素音频信息"""
    available = {}
    for arpabet, path in _ARPABET_TO_AUDIO.items():
        if path and path.is_file():
            available[arpabet] = {"file": path.name, "ipa": ARPABET_TO_IPA.get(arpabet, "")}
        elif arpabet in _DIPHTHONG_COMPONENTS:
            available[arpabet] = {
                "file": "composite",
                "components": list(_DIPHTHONG_COMPONENTS[arpabet]),
                "ipa": ARPABET_TO_IPA.get(arpabet, "")
            }
    return {"total": len(available), "phonemes": available}


# ============================================================
# TTS 语音合成 API
# ============================================================

@app.get("/api/tts")
async def tts_endpoint(text: str = Query(..., description="要合成语音的文本")):
    """生成 TTS 音频并返回音频文件"""
    result = generate_tts(text)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    media_type = "audio/mpeg" if result["format"] == "mp3" else "audio/wav"
    return FileResponse(result["path"], media_type=media_type)


@app.get("/api/tts/phoneme")
async def tts_phoneme_endpoint(phoneme: str = Query(..., description="音素符号")):
    """为单个音素生成发音音频（TTS 合成，音质不如 IPA 标准音频）

    前端应优先使用 /api/ipa-audio/{arpabet} 获取真实人声发音
    """
    audio_path = generate_phoneme_audio(phoneme)
    if not audio_path:
        raise HTTPException(status_code=404, detail=f"无法为音素 '{phoneme}' 生成音频")
    # 判断文件格式
    if audio_path.endswith(".mp3"):
        media_type = "audio/mpeg"
    else:
        media_type = "audio/wav"
    return FileResponse(audio_path, media_type=media_type)


@app.get("/api/tts/check")
async def tts_check_endpoint():
    """检查 TTS 引擎可用性"""
    return check_tts_available()


# ============================================================
# 听写检查 API
# ============================================================

def _levenshtein_align(expected_words: list, user_words: list) -> list:
    """使用 Levenshtein 距离算法对齐期望词和用户输入词

    通过 DP 找到最优对齐，避免一一匹配导致的级联错误。
    返回对齐结果列表，每个元素包含 expected, actual, correct, alignment_type
    """
    m, n = len(expected_words), len(user_words)

    # DP 表：dp[i][j] = 将 expected[:i] 与 user[:j] 对齐的最小编辑距离
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    trace = [[0] * (n + 1) for _ in range(m + 1)]  # 0=match/sub, 1=del, 2=ins

    for i in range(1, m + 1):
        dp[i][0] = dp[i - 1][0] + 1  # 删除代价
        trace[i][0] = 1
    for j in range(1, n + 1):
        dp[0][j] = dp[0][j - 1] + 1  # 插入代价
        trace[0][j] = 2

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            # 匹配或替换
            cost = 0 if expected_words[i - 1] == user_words[j - 1] else 1
            sub = dp[i - 1][j - 1] + cost
            delete = dp[i - 1][j] + 1
            insert = dp[i][j - 1] + 1

            if sub <= delete and sub <= insert:
                dp[i][j] = sub
                trace[i][j] = 0
            elif delete <= insert:
                dp[i][j] = delete
                trace[i][j] = 1
            else:
                dp[i][j] = insert
                trace[i][j] = 2

    # 回溯对齐
    alignment = []
    i, j = m, n
    while i > 0 or j > 0:
        if i > 0 and j > 0 and trace[i][j] == 0:
            alignment.append((expected_words[i - 1], user_words[j - 1], "match" if expected_words[i - 1] == user_words[j - 1] else "substitution"))
            i -= 1
            j -= 1
        elif i > 0 and trace[i][j] == 1:
            alignment.append((expected_words[i - 1], "", "deletion"))
            i -= 1
        else:
            alignment.append(("", user_words[j - 1], "insertion"))
            j -= 1

    alignment.reverse()
    return alignment


@app.post("/api/dictation/check")
async def dictation_check(data: dict):
    """听写对比检查（基于 Levenshtein 距离算法）

    Body: {"text": "expected sentence", "sentence_text": "expected sentence", "user_input": "user typed" or ["word1", "word2"]}
    返回逐词对比结果和准确率
    """
    expected = data.get("text", data.get("sentence_text", "")).lower().strip()
    user_input_raw = data.get("user_input", "")
    if isinstance(user_input_raw, list):
        user_input = " ".join(str(w) for w in user_input_raw).lower().strip()
    else:
        user_input = str(user_input_raw).lower().strip()

    expected_words = expected.split()
    user_words = user_input.split()

    # 使用 Levenshtein 距离对齐，避免级联错误
    alignment = _levenshtein_align(expected_words, user_words)

    results = []
    for ew, uw, align_type in alignment:
        if align_type == "match":
            results.append({
                "expected": ew,
                "actual": uw,
                "correct": True,
                "type": "match",
            })
        elif align_type == "substitution":
            results.append({
                "expected": ew,
                "actual": uw,
                "correct": False,
                "type": "substitution",
            })
        elif align_type == "deletion":
            results.append({
                "expected": ew,
                "actual": "",
                "correct": False,
                "type": "deletion",
            })
        elif align_type == "insertion":
            results.append({
                "expected": "",
                "actual": uw,
                "correct": False,
                "type": "insertion",
            })

    accuracy = sum(1 for r in results if r["correct"]) / max(len(expected_words), 1) * 100

    return {
        "results": results,
        "accuracy": round(accuracy, 1),
        "expected": expected,
        "user_input": user_input,
    }


# ============================================================
# 音频评测 API
# ============================================================

def _load_audio_file(file_path: str):
    """
    多格式音频加载，支持 WAV/FLAC/OGG/WebM/MP4 等

    尝试顺序：
    1. soundfile（支持 WAV/FLAC/OGG 等）
    2. librosa.load()（支持更多格式，需 ffmpeg）
    3. pydub 转码后 soundfile 读取（WebM/MP4 等需 ffmpeg）
    4. subprocess ffmpeg 直接转码
    """
    import soundfile as sf
    import librosa

    # 尝试1：soundfile 直接读取
    try:
        audio_data, sr = sf.read(file_path)
        if audio_data.ndim > 1:
            audio_data = audio_data.mean(axis=-1)
        if sr != 16000:
            audio_data = librosa.resample(audio_data, orig_sr=sr, target_sr=16000)
            sr = 16000
        return audio_data.astype(np.float32), sr
    except Exception:
        pass

    # 尝试2：librosa.load（内部使用 audioread，可能支持更多格式）
    try:
        audio_data, sr = librosa.load(file_path, sr=16000, mono=True)
        return audio_data.astype(np.float32), 16000
    except Exception:
        pass

    # 尝试3：pydub 转码
    try:
        from pydub import AudioSegment
        from pydub.utils import which
        if which("ffmpeg"):
            audio_seg = AudioSegment.from_file(file_path)
            audio_seg = audio_seg.set_frame_rate(16000).set_channels(1)
            wav_path = file_path.rsplit('.', 1)[0] + "_converted.wav"
            audio_seg.export(wav_path, format="wav")
            try:
                audio_data, sr = sf.read(wav_path)
                if audio_data.ndim > 1:
                    audio_data = audio_data.mean(axis=-1)
                return audio_data.astype(np.float32), sr
            finally:
                if os.path.exists(wav_path):
                    os.unlink(wav_path)
    except Exception:
        pass

    # 尝试4：subprocess ffmpeg 直接转码
    try:
        import subprocess as sp
        wav_path = file_path.rsplit('.', 1)[0] + "_converted.wav"
        result = sp.run(
            ["ffmpeg", "-y", "-i", file_path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
            capture_output=True, timeout=30
        )
        if result.returncode == 0 and os.path.exists(wav_path):
            try:
                audio_data, sr = sf.read(wav_path)
                if audio_data.ndim > 1:
                    audio_data = audio_data.mean(axis=-1)
                return audio_data.astype(np.float32), sr
            finally:
                if os.path.exists(wav_path):
                    os.unlink(wav_path)
    except Exception:
        pass

    raise RuntimeError(
        "无法读取音频文件。请安装 ffmpeg 以支持 WebM/MP4 等格式。\n"
        "Windows: 下载 https://ffmpeg.org/download.html 并添加到 PATH\n"
        "或安装 pydub: pip install pydub"
    )


@app.post("/api/evaluate")
async def evaluate_audio(
    audio: UploadFile = File(...),
    sentence_text: str = Form(...),
):
    """评测音频发音"""
    try:
        g2p = get_g2p_service()
        expected_phonemes = g2p.text_to_phonemes(sentence_text)
        word_phonemes = g2p.text_to_phonemes_with_words(sentence_text)

        if not expected_phonemes:
            raise HTTPException(status_code=400, detail="无法生成期望音素序列")

        suffix = Path(audio.filename or "audio.wav").suffix or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            content = await audio.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            audio_float, sr = _load_audio_file(tmp_path)

            recognizer = get_recognizer(MODEL_PATH)
            result_dict = recognizer.recognize_with_timestamps(audio_float, sr)
            actual_phonemes = result_dict["phonemes"]
            timeline = result_dict["timeline"]
            blank_segments = result_dict["blank_segments"]
            total_duration = result_dict["total_duration"]

            eval_result = evaluate_pronunciation(
                expected_phonemes=expected_phonemes,
                actual_phonemes=actual_phonemes,
                word_boundaries=word_phonemes,
                timeline=timeline,
                blank_segments=blank_segments,
                total_duration=total_duration,
            )

            tips = generate_error_tips(eval_result.errors)
            response = result_to_dict(eval_result, tips)
            response["sentence"] = sentence_text

            # 添加单词详情
            words = sentence_text.lower().split()
            response["word_details"] = [_get_word_detail(w) for w in words]

            return response
        finally:
            os.unlink(tmp_path)

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"评测失败: {str(e)}")


# ============================================================
# 辅助函数
# ============================================================

def _find_sentence_by_card_id(card_id: str):
    """根据 FSRS 卡片 ID 查找对应的句子

    支持格式: "sentence_{id}" 或直接使用句子文本
    """
    # 格式1: "sentence_{id}"
    if card_id.startswith("sentence_"):
        try:
            sid = int(card_id.split("_", 1)[1])
            for s in PRESET_SENTENCES:
                if s["id"] == sid:
                    return s
        except (ValueError, IndexError):
            pass

    # 格式2: 直接使用句子文本作为 card_id
    for s in PRESET_SENTENCES:
        if s["text"] == card_id:
            return s

    return None


def _enrich_sentence(sentence: dict) -> dict:
    """为句子数据添加音素和单词详情，自动翻译缺失的翻译"""
    text = sentence["text"]
    cached = _phoneme_cache.get(text, {})

    words = text.lower().split()
    word_details = [_get_word_detail(w) for w in words]

    # 自动翻译：如果没有翻译，尝试本地词典拼接
    # 不再调用在线翻译服务（太慢，会阻塞页面加载）
    translation = sentence.get("translation", "")
    if not translation:
        # 尝试从词典拼接简易翻译
        try:
            word_meanings = []
            for w in words:
                info = get_dict_service().lookup(w, local_only=True)
                meaning = info.get("meaning", "")
                if meaning:
                    # 只取第一个释义的分号前部分
                    short = meaning.split(";")[0].split("，")[0].strip()
                    if short:
                        word_meanings.append(short)
            if word_meanings:
                translation = "；".join(word_meanings)
        except Exception:
            pass

    return {
        "id": sentence["id"],
        "text": text,
        "translation": translation,
        "difficulty": sentence.get("difficulty", "medium"),
        "category": sentence.get("category", "general"),
        "tags": sentence.get("tags", []),
        "key_phrases": sentence.get("key_phrases", []),
        "cultural_note": sentence.get("cultural_note", ""),
        "phonemes": cached.get("phonemes", []),
        "ipa": cached.get("ipa", ""),
        "word_phonemes": cached.get("word_phonemes", []),
        "word_details": word_details,
    }


def _get_word_detail(word: str) -> dict:
    """获取单词详情（动态词典查询，仅本地数据避免阻塞）"""
    dict_svc = get_dict_service()
    info = dict_svc.lookup(word, local_only=True)

    g2p = get_g2p_service()
    arpabet = info.get("arpabet", [])
    if not arpabet:
        arpabet = g2p.text_to_phonemes(word)
    ipa_from_g2p = G2PService.arpabet_to_ipa(arpabet) if arpabet else ""

    # 从 endict 获取的音标（优先使用）
    ipa_us = info.get("ipa_us", "")
    ipa_uk = info.get("ipa_uk", "")

    # 清理音标：去除可能存在的 // 包裹
    if ipa_us.startswith("/") and ipa_us.endswith("/"):
        ipa_us = ipa_us[1:-1]
    if ipa_uk.startswith("/") and ipa_uk.endswith("/"):
        ipa_uk = ipa_uk[1:-1]

    # 优先使用 endict 的美式音标，否则使用 G2P 生成的
    final_ipa = ipa_us or ipa_from_g2p

    return {
        "word": word,
        "pos": info.get("pos", ""),
        "meaning": info.get("meaning", ""),
        "ipa": final_ipa,
        "ipa_uk": ipa_uk,
        "arpabet": arpabet,
        "example": info.get("example", ""),
        "examples": info.get("examples", []),
        "frequency": info.get("frequency", 0),
        "difficulty": info.get("difficulty", 0),
        "memory_tip": info.get("memory_tip", ""),
        "grammar_note": info.get("grammar_note", ""),
        "source": info.get("source", "g2p"),
    }


# 挂载前端
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
