"""
Phonos 口语练习平台 - FastAPI 后端

优化点:
- 延迟加载词典（首次查询时才加载）
- 音素缓存后台更新（不阻塞启动）
- 句子按需enrich（不一次性处理所有句子）
- 免费网络API回退（ENDICT查不到的词）
- ONNX 翻译模型在线API失败时自动回退
"""

import os
import re
import sys
import traceback
import tempfile
import random
import asyncio
import time
import warnings
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from phoneme_data import (
    PRESET_SENTENCES, PHONEME_TIPS, MINIMAL_PAIRS,
    ARPABET_TO_IPA, VOCAB,
    update_phoneme_cache,
)
from g2p_service import get_g2p_service, G2PService
from onnx_service import get_recognizer
from scoring import evaluate_pronunciation, generate_error_tips, result_to_dict
from fsrs_db import get_fsrs_db
from tts_service import generate_tts, generate_phoneme_audio, check_tts_available
from dict_service import get_dict_service
from translate_service import translate_text, translate_text_detail, get_translate_status
from auth_service import get_auth_service
from learning_algorithm import get_learning_algorithm

app = FastAPI(title="Phonos 口语练习平台", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 模型路径
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

def _find_model() -> str:
    """自动查找 ONNX 模型文件"""
    env_path = os.environ.get("HUPER_MODEL_PATH", "")
    if env_path and os.path.isfile(env_path):
        return env_path

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
_model_loaded = False


@app.on_event("startup")
async def startup():
    print("[启动] 初始化 Phonos 口语练习平台...")

    # 1. 初始化 G2P 服务（轻量，不阻塞）
    g2p = get_g2p_service()
    print(f"[启动] G2P 服务就绪 (g2p_en: {'可用' if g2p.available else '不可用，使用词典'})")

    # 2. 初始化词典服务（延迟加载，不在此读取文件）
    get_dict_service()
    print("[启动] 词典服务就绪（延迟加载）")

    # 3. 后台更新音素缓存（不阻塞启动，用户可立即访问）
    asyncio.create_task(_background_update_cache())

    # 4. 加载 ONNX 模型（后台，不阻塞）
    if MODEL_PATH and os.path.exists(MODEL_PATH):
        asyncio.create_task(_background_load_model())
    else:
        print("[启动] ⚠️  未找到 ONNX 模型，请将模型文件放到以下位置之一:")
        print(f"         - {_PROJECT_ROOT / 'model' / 'model.onnx'}")
        print(f"         - {_PROJECT_ROOT / 'model' / 'model_quantized.onnx'}")
        print("         或设置环境变量 HUPER_MODEL_PATH 指定模型路径")

    # 5. 初始化 FSRS 数据库
    try:
        fsrs = get_fsrs_db()
        print(f"[启动] FSRS 数据库就绪")
    except Exception as e:
        print(f"[启动] ⚠️  FSRS 数据库初始化失败: {e}")

    # 5.5 初始化认证服务和智能学习服务
    try:
        auth = get_auth_service()
        print(f"[启动] 认证服务就绪")
    except Exception as e:
        print(f"[启动] ⚠️  认证服务初始化失败: {e}")

    try:
        learning = get_learning_algorithm()
        print(f"[启动] 智能学习服务就绪")
    except Exception as e:
        print(f"[启动] ⚠️  智能学习服务初始化失败: {e}")

    # 6. TTS 可用性检查
    tts_status = check_tts_available()
    available_engines = [k for k, v in tts_status.items() if v]
    if available_engines:
        print(f"[启动] TTS 服务可用: {', '.join(available_engines)}")
    else:
        print("[启动] ⚠️  TTS 服务不可用，请安装 edge-tts 或 pyttsx3")

    print(f"[启动] 句子数据: {len(PRESET_SENTENCES)} 个预设句子")
    print("[启动] 平台初始化完成（后台加载模型和音素缓存...）")


async def _background_load_model():
    """后台加载 ONNX 模型"""
    global _model_loaded
    try:
        get_recognizer(MODEL_PATH)
        _model_loaded = True
        print(f"[后台] ONNX 模型加载成功: {MODEL_PATH}")
    except Exception as e:
        print(f"[后台] ONNX 模型加载失败: {e}")


async def _background_update_cache():
    """后台增量更新音素缓存"""
    global _phoneme_cache
    try:
        g2p = get_g2p_service()
        # 在线程池中执行，避免阻塞事件循环
        loop = asyncio.get_event_loop()
        _phoneme_cache = await loop.run_in_executor(
            None, update_phoneme_cache, PRESET_SENTENCES, g2p
        )
        print(f"[后台] 音素缓存更新完成: {len(_phoneme_cache)} 条")

        # 同时为所有句子创建 FSRS 卡片（default 用户）
        try:
            fsrs = get_fsrs_db()
            for sentence in PRESET_SENTENCES:
                card_id = f"sentence_{sentence['id']}"
                fsrs.ensure_card(card_id, card_type="sentence", user_id="default")
            print(f"[后台] FSRS 卡片就绪: {len(PRESET_SENTENCES)} 个")
        except Exception as e:
            print(f"[后台] FSRS 卡片创建失败: {e}")

    except Exception as e:
        print(f"[后台] 音素缓存更新失败: {e}")


# ============================================================
# 认证辅助函数
# ============================================================

def get_current_user(request: Request) -> dict:
    """从请求头获取当前用户，无token时返回默认用户"""
    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    auth = get_auth_service()
    return auth.get_user_by_token(token)


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
        "phoneme_cache_ready": len(_phoneme_cache) > 0,
        "translate_status": get_translate_status(),
    }


# ============================================================
# 认证 API
# ============================================================

@app.post("/api/auth/register")
async def auth_register(data: dict):
    auth = get_auth_service()
    try:
        result = auth.register(
            username=data.get("username", ""),
            password=data.get("password", ""),
            display_name=data.get("display_name", ""),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/login")
async def auth_login(data: dict):
    auth = get_auth_service()
    try:
        result = auth.login(
            username=data.get("username", ""),
            password=data.get("password", ""),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
    if token:
        auth = get_auth_service()
        auth.logout(token)
    return {"ok": True}


@app.get("/api/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    return user


@app.put("/api/auth/profile")
async def auth_update_profile(data: dict, user: dict = Depends(get_current_user)):
    auth = get_auth_service()
    try:
        result = auth.update_profile(
            user_id=user["id"],
            display_name=data.get("display_name"),
            settings=data.get("settings"),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/auth/password")
async def auth_change_password(data: dict, user: dict = Depends(get_current_user)):
    auth = get_auth_service()
    try:
        auth.change_password(
            user_id=user["id"],
            old_password=data.get("old_password", ""),
            new_password=data.get("new_password", ""),
        )
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# 注意：不提供 /api/auth/users 接口，不暴露其他用户账号信息


# ============================================================
# 智能学习 API
# ============================================================

@app.get("/api/learning/weakness-profile")
async def learning_weakness_profile(user: dict = Depends(get_current_user)):
    learning = get_learning_algorithm()
    return learning.get_weakness_profile(user["id"])


@app.get("/api/learning/recommendations")
async def learning_recommendations(user: dict = Depends(get_current_user)):
    learning = get_learning_algorithm()
    return learning.get_recommendations(user["id"], PRESET_SENTENCES)


@app.get("/api/learning/adaptive-next")
async def learning_adaptive_next(user: dict = Depends(get_current_user)):
    learning = get_learning_algorithm()
    result = learning.get_adaptive_next(user["id"], PRESET_SENTENCES)
    if result:
        enriched = await _enrich_sentence_async(result)
        return enriched
    return None


@app.get("/api/learning/analytics")
async def learning_analytics(user: dict = Depends(get_current_user)):
    learning = get_learning_algorithm()
    return learning.get_analytics(user["id"])


@app.get("/api/stats")
async def get_user_stats(user: dict = Depends(get_current_user)):
    """获取当前用户的完整统计（从数据库，跨浏览器同步）"""
    user_id = user.get("id", "default")
    learning = get_learning_algorithm()
    fsrs = get_fsrs_db()

    # 1. 学习算法统计（评测记录、错误音素、单词进度）
    analytics = learning.get_analytics(user_id)

    # 2. FSRS 统计
    fsrs_stats = fsrs.get_stats(user_id)

    # 3. 错误音素详情（用于前端错误统计展示）
    weakness = learning.get_weakness_profile(user_id)

    # 4. 最近的得分记录
    conn = learning._get_conn() if hasattr(learning, '_get_conn') else None
    recent_scores = []
    total_practice = 0
    words_learned = {}
    error_phonemes = {}

    try:
        import sqlite3
        conn2 = sqlite3.connect(learning.db_path)
        # 最近50次得分
        rows = conn2.execute(
            "SELECT overall_score FROM user_evaluations WHERE user_id = ? ORDER BY evaluated_at DESC LIMIT 50",
            (user_id,)
        ).fetchall()
        recent_scores = [r[0] for r in rows]

        # 总练习次数
        total_practice = conn2.execute(
            "SELECT COUNT(*) FROM user_evaluations WHERE user_id = ?", (user_id,)
        ).fetchone()[0]

        # 单词掌握情况（发音评测数据）
        word_rows = conn2.execute(
            "SELECT word, attempts, best_score, avg_score, mastered FROM user_word_progress WHERE user_id = ? ORDER BY avg_score ASC",
            (user_id,)
        ).fetchall()
        for r in word_rows:
            words_learned[r[0]] = {
                "attempts": r[1], 
                "best": round(r[2], 1), 
                "avg": round(r[3], 1), 
                "mastered": bool(r[4]),
                "source": "pronunciation"
            }

        # 错误音素统计
        phoneme_rows = conn2.execute(
            "SELECT phoneme, total_attempts, error_count, error_rate FROM user_phoneme_stats WHERE user_id = ? ORDER BY error_count DESC",
            (user_id,)
        ).fetchall()
        error_phonemes = {r[0]: r[2] for r in phoneme_rows}

        # 听写错误单词数据（合并到 words_learned）
        error_word_rows = conn2.execute(
            "SELECT word, error_type, count FROM user_word_errors WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        for r in error_word_rows:
            word = r[0]
            if word not in words_learned:
                words_learned[word] = {
                    "attempts": 0, "best": 0, "avg": 0, "mastered": False, "source": "dictation"
                }
            if r[1] == 'dictation':
                words_learned[word]["dictation_errors"] = r[2]
            elif r[1] == 'pronunciation':
                words_learned[word]["pronunciation_errors"] = r[2]

        conn2.close()
    except Exception as e:
        print(f"[统计] 查询失败: {e}")

    # 补充 FSRS 单词卡片数据（掌握度从 FSRS 状态推断）
    try:
        now = time.time()
        import sqlite3 as _sql3
        conn3 = _sql3.connect(fsrs.db_path)
        word_card_rows = conn3.execute(
            "SELECT card_id, state, difficulty, stability, reps, scheduled_days, due, last_review "
            "FROM cards WHERE card_type='word' AND user_id=?",
            (user_id,)
        ).fetchall()
        for r in word_card_rows:
            word = r[0].replace("word_", "", 1)
            state = r[1]  # 0=new, 1=learning, 2=review, 3=relearning
            difficulty = r[2]
            stability = r[3]
            reps = r[4]
            scheduled_days = r[5]
            due = r[6]
            last_review = r[7]

            # 推断掌握度
            if state == 0:
                mastery = "new"
            elif state == 1:
                mastery = "learning"
            elif state == 2 and due > now:
                mastery = "mastered"  # 已复习且未到期 = 已掌握
            elif state == 2 and due <= now:
                mastery = "due"  # 到期需要复习
            elif state == 3:
                mastery = "relearning"
            else:
                mastery = "unknown"

            if word in words_learned:
                words_learned[word]["fsrs_mastery"] = mastery
                words_learned[word]["fsrs_reps"] = reps
                words_learned[word]["fsrs_difficulty"] = round(difficulty, 2)
                words_learned[word]["fsrs_scheduled_days"] = round(scheduled_days, 1)
            else:
                words_learned[word] = {
                    "attempts": 0, "best": 0, "avg": 0, "mastered": mastery == "mastered",
                    "source": "fsrs", "fsrs_mastery": mastery, "fsrs_reps": reps,
                    "fsrs_difficulty": round(difficulty, 2), "fsrs_scheduled_days": round(scheduled_days, 1),
                }
        conn3.close()
    except Exception as e:
        print(f"[统计] FSRS单词数据查询失败: {e}")

    # 单词复习统计（合并 FSRS 和学习数据库的单词数据）
    word_review_stats = fsrs.get_word_review_stats(user_id)

    # 补充：统计不在 FSRS 中但在 user_word_progress / user_word_errors 中的单词
    # 这些是用户练习过但没有 FSRS 卡片的单词
    fsrs_word_set = set()
    try:
        conn4 = sqlite3.connect(fsrs.db_path)
        fsrs_word_rows = conn4.execute(
            "SELECT card_id FROM cards WHERE card_type='word' AND user_id=?", (user_id,)
        ).fetchall()
        conn4.close()
        fsrs_word_set = {r[0].replace("word_", "", 1) for r in fsrs_word_rows}
    except Exception:
        pass

    # 统计只有发音数据没有 FSRS 卡片的单词
    extra_mastered = 0
    extra_learning = 0
    extra_new = 0
    for word, info in words_learned.items():
        if word not in fsrs_word_set:
            if info.get("mastered", False) or info.get("best", 0) >= 80:
                extra_mastered += 1
            elif info.get("attempts", 0) > 0:
                extra_learning += 1
            else:
                extra_new += 1

    # 合并统计
    word_review_stats["total"] = word_review_stats.get("total", 0) + len([w for w in words_learned if w not in fsrs_word_set])
    word_review_stats["mastered"] = word_review_stats.get("mastered", 0) + extra_mastered
    word_review_stats["learning"] = word_review_stats.get("learning", 0) + extra_learning
    # 重新计算 due = total - mastered - new（保持用户视角一致性）
    word_review_stats["due"] = word_review_stats["total"] - word_review_stats["mastered"] - word_review_stats.get("new", 0)
    if word_review_stats["due"] < 0:
        word_review_stats["due"] = 0

    # 错误单词统计（按类型分组，含词典信息）
    error_words_stats = {"dictation_errors": [], "pronunciation_errors": [], "summary": {}}
    try:
        dict_svc = get_dict_service()
        all_error_words = learning.get_error_words(user_id)
        for ew in all_error_words:
            word = ew["word"]
            word_detail = dict_svc.lookup(word, local_only=True)
            entry = {
                "word": word,
                "ipa": word_detail.get("ipa", ""),
                "meaning": word_detail.get("meaning", ""),
                "dictation_errors": ew.get("dictation_errors", 0),
                "pronunciation_errors": ew.get("pronunciation_errors", 0),
                "total_errors": ew.get("total_errors", 0),
            }
            if ew.get("dictation_errors", 0) > 0:
                error_words_stats["dictation_errors"].append(entry)
            if ew.get("pronunciation_errors", 0) > 0:
                error_words_stats["pronunciation_errors"].append(entry)
        error_words_stats["dictation_errors"].sort(key=lambda x: x["dictation_errors"], reverse=True)
        error_words_stats["pronunciation_errors"].sort(key=lambda x: x["pronunciation_errors"], reverse=True)
        error_words_stats["summary"] = {
            "total_dict_errors": len(error_words_stats["dictation_errors"]),
            "total_pron_errors": len(error_words_stats["pronunciation_errors"]),
            "total_error_words": len(all_error_words),
        }
    except Exception as e:
        print(f"[统计] 错误单词统计失败: {e}")

    return {
        "total_practice": total_practice,
        "recent_scores": recent_scores,
        "error_phonemes": error_phonemes,
        "words_learned": words_learned,
        "analytics": analytics,
        "fsrs_stats": fsrs_stats,
        "word_review_stats": word_review_stats,
        "weakness": weakness,
        "error_words_stats": error_words_stats,
    }


@app.post("/api/learning/record-evaluation")
async def learning_record_evaluation(data: dict, user: dict = Depends(get_current_user)):
    learning = get_learning_algorithm()
    try:
        learning.record_evaluation(
            user_id=user["id"],
            sentence_id=data.get("sentence_id", ""),
            overall_score=data.get("overall_score", 0),
            pronunciation_score=data.get("pronunciation_score", 0),
            completeness_score=data.get("completeness_score", 0),
            fluency_score=data.get("fluency_score", 0),
            errors=data.get("errors", []),
            word_scores=data.get("word_scores", []),
            duration=data.get("duration", 0),
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sentence")
async def get_random_sentence(force_new: bool = Query(False, description="强制获取新句子，跳过FSRS"), user: dict = Depends(get_current_user)):
    """获取练习句子（FSRS 优先，混合复习和新句子）"""
    user_id = user.get("id", "default")

    if force_new:
        sentence = random.choice(PRESET_SENTENCES)
        result = await _enrich_sentence_async(sentence)
        _auto_register_words(sentence["text"], user_id)
        return result

    try:
        fsrs = get_fsrs_db()
        queue = fsrs.get_review_queue(card_type="sentence", user_id=user_id, new_per_day=5)

        if queue:
            review_cards = [q for q in queue if q["type"] == "review"]
            new_cards = [q for q in queue if q["type"] == "new"]

            if review_cards:
                chosen = random.choice(review_cards)
                sentence = _find_sentence_by_card_id(chosen["card_id"])
                if sentence:
                    result = await _enrich_sentence_async(sentence)
                    result["fsrs"] = chosen
                    _auto_register_words(sentence["text"], user_id)
                    return result

            if new_cards:
                chosen = random.choice(new_cards)
                sentence = _find_sentence_by_card_id(chosen["card_id"])
                if sentence:
                    result = await _enrich_sentence_async(sentence)
                    result["fsrs"] = chosen
                    _auto_register_words(sentence["text"], user_id)
                    return result

        # 没有队列，选一个句子
        fsrs_card_ids = set()
        try:
            import sqlite3
            conn = sqlite3.connect(fsrs.db_path)
            rows = conn.execute("SELECT card_id FROM cards WHERE card_type='sentence' AND user_id=?", (user_id,)).fetchall()
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
            fsrs.ensure_card(f"sentence_{sentence['id']}", card_type="sentence", user_id=user_id)
            result = await _enrich_sentence_async(sentence)
            _auto_register_words(sentence["text"], user_id)
            return result

    except Exception as e:
        print(f"[FSRS] 获取复习队列失败，回退到随机模式: {e}")

    sentence = random.choice(PRESET_SENTENCES)
    result = await _enrich_sentence_async(sentence)
    _auto_register_words(sentence["text"], user_id)
    return result


@app.get("/api/sentences")
async def get_all_sentences():
    """获取所有练习句子（流式：只返回基本信息，不展开词典详情）"""
    return [
        {
            "id": s["id"],
            "text": s["text"],
            "translation": s.get("translation", ""),
            "difficulty": s.get("difficulty", "medium"),
            "category": s.get("category", "general"),
        }
        for s in PRESET_SENTENCES
    ]


@app.get("/api/sentence/{sentence_id}")
async def get_sentence_by_id(sentence_id: int):
    """按ID获取句子（完整详情）"""
    for s in PRESET_SENTENCES:
        if s["id"] == sentence_id:
            return await _enrich_sentence_async(s)
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
async def fsrs_review(data: dict, user: dict = Depends(get_current_user)):
    card_id = data.get("card_id")
    rating = data.get("rating")
    card_type = data.get("card_type", "sentence")
    user_id = user.get("id", "default")

    if not card_id:
        raise HTTPException(status_code=400, detail="缺少 card_id")
    if rating not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="rating 必须为 1-4")

    try:
        fsrs = get_fsrs_db()
        result = fsrs.review_card(card_id, rating, card_type, user_id=user_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"复习记录失败: {str(e)}")


@app.get("/api/fsrs/queue")
async def fsrs_queue(card_type: str = Query("sentence"), new_per_day: int = Query(5), user: dict = Depends(get_current_user)):
    user_id = user.get("id", "default")
    try:
        fsrs = get_fsrs_db()
        queue = fsrs.get_review_queue(card_type=card_type, user_id=user_id, new_per_day=new_per_day)
        return {"queue": queue, "total": len(queue)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取复习队列失败: {str(e)}")


@app.get("/api/fsrs/stats")
async def fsrs_stats(user: dict = Depends(get_current_user)):
    user_id = user.get("id", "default")
    try:
        fsrs = get_fsrs_db()
        fsrs_stats_data = fsrs.get_stats(user_id=user_id)
        # Also include learning analytics if available
        try:
            learning = get_learning_algorithm()
            analytics = learning.get_analytics(user_id)
            fsrs_stats_data["learning_analytics"] = analytics
        except Exception:
            pass
        return fsrs_stats_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")


@app.get("/api/fsrs/next")
async def fsrs_next(card_type: str = Query("sentence"), user: dict = Depends(get_current_user)):
    user_id = user.get("id", "default")
    try:
        fsrs = get_fsrs_db()
        queue = fsrs.get_review_queue(card_type=card_type, user_id=user_id, new_per_day=5)

        if queue:
            review_cards = [q for q in queue if q["type"] == "review"]
            new_cards = [q for q in queue if q["type"] == "new"]

            chosen = None
            sentence_type = "new"
            if review_cards:
                chosen = random.choice(review_cards)
                sentence_type = "review"
            elif new_cards:
                chosen = random.choice(new_cards)

            if chosen:
                sentence = _find_sentence_by_card_id(chosen["card_id"])
                if sentence:
                    result = await _enrich_sentence_async(sentence)
                    result["fsrs"] = chosen
                    return {"sentence": result, "type": sentence_type}

        sentence = random.choice(PRESET_SENTENCES)
        result = await _enrich_sentence_async(sentence)
        return {"sentence": result, "type": "new"}

    except Exception:
        sentence = random.choice(PRESET_SENTENCES)
        result = await _enrich_sentence_async(sentence)
        return {"sentence": result, "type": "new"}


@app.get("/api/fsrs/due-count")
async def fsrs_due_count(card_type: str = Query("sentence"), user: dict = Depends(get_current_user)):
    """获取到期复习数量
    
    返回多种计数：
    - count: 严格FSRS到期数（state!=NEW 且 due<=now）
    - pending_count: 待复习数（非NEW且非已掌握，不含新词）
    - total_reviewable: 可练习总数（新词+待复习，不含已掌握）
    - new_count: 新卡片数
    """
    user_id = user.get("id", "default")
    try:
        fsrs = get_fsrs_db()
        due_count = fsrs.get_due_count(card_type=card_type, user_id=user_id)
        new_count = fsrs.get_new_card_count(card_type=card_type, user_id=user_id)
        pending_count = fsrs.get_pending_review_count(card_type=card_type, user_id=user_id)
        total_reviewable = fsrs.get_total_reviewable_count(card_type=card_type, user_id=user_id)
        return {
            "count": due_count, 
            "new_count": new_count, 
            "total_due": due_count, 
            "pending_count": pending_count,
            "total_reviewable": total_reviewable,
        }
    except Exception:
        return {"count": 0, "new_count": 0, "total_due": 0, "pending_count": 0, "total_reviewable": 0}


@app.post("/api/fsrs/ensure")
async def fsrs_ensure(data: dict, user: dict = Depends(get_current_user)):
    card_ids = data.get("card_ids", [])
    card_type = data.get("card_type", "sentence")
    user_id = user.get("id", "default")

    if not card_ids:
        raise HTTPException(status_code=400, detail="缺少 card_ids")

    try:
        fsrs = get_fsrs_db()
        created = []
        for card_id in card_ids:
            fsrs.ensure_card(card_id, card_type, user_id=user_id)
            created.append(card_id)
        return {"created": created, "total": len(created)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建卡片失败: {str(e)}")


# ============================================================
# 学习模式 API
# ============================================================

@app.get("/api/mode/sequential/next")
async def mode_sequential_next(
    start_id: Optional[int] = Query(None, description="起始句子ID（1-indexed，句子的id字段）"),
    end_id: Optional[int] = Query(None, description="结束句子ID"),
    user: dict = Depends(get_current_user),
):
    """顺序模式：严格按JSON文件ID顺序获取下一个句子
    
    顺序模式不因 FSRS 到期复习打断，FSRS 只在后台记录进度。
    当用户主动评级时，FSRS 会在智能模式中发挥作用。
    支持通过 start_id/end_id 指定ID范围。
    """
    user_id = user.get("id", "default")
    learning = get_learning_algorithm()
    fsrs = get_fsrs_db()
    current_count = len(PRESET_SENTENCES)

    # 0. 数据变化检测
    pos_info = learning.get_sequential_position(user_id)
    stored_count = pos_info.get("sentences_count", 0)
    data_changed = False
    if stored_count > 0 and stored_count != current_count:
        data_changed = True

    # 1. 确定有效的 start_id / end_id
    effective_start = start_id if start_id is not None else pos_info.get("start_id")
    effective_end = end_id if end_id is not None else pos_info.get("end_id")

    # 2. 顺序获取下一个句子（严格按顺序，不被 FSRS 打断）
    if effective_start is not None or effective_end is not None:
        # 使用 ID 范围过滤
        filtered = [s for s in PRESET_SENTENCES]
        if effective_start is not None:
            filtered = [s for s in filtered if s.get("id", 0) >= effective_start]
        if effective_end is not None:
            filtered = [s for s in filtered if s.get("id", 0) <= effective_end]

        if not filtered:
            raise HTTPException(status_code=404, detail="指定ID范围内没有句子")

        # 用存储的位置在过滤后的列表中找句子
        pos = pos_info.get("position", 0)
        
        # 如果数据变化了，不自动前进，返回提示
        if data_changed:
            sentence = filtered[0]
            result = await _enrich_sentence_async(sentence)
            return {
                "sentence": result,
                "type": "new",
                "mode": "sequential",
                "data_changed": True,
                "position": 0,
                "total": len(filtered),
                "message": "句子数据已变更，请确认起始位置",
            }

        # 在过滤列表中找到当前应该的句子
        if pos < len(filtered):
            sentence = filtered[pos]
        else:
            pos = 0
            sentence = filtered[0]

        # 更新位置（在过滤列表中的位置+1）
        next_pos = pos + 1
        if next_pos >= len(filtered):
            next_pos = 0  # 循环
        learning.set_sequential_position(
            user_id, next_pos, sentences_count=current_count,
            start_id=effective_start, end_id=effective_end
        )

        # 确保 FSRS 卡片存在
        fsrs.ensure_card(f"sentence_{sentence['id']}", card_type="sentence", user_id=user_id)

        # 获取 FSRS 卡片信息（如果有）
        card_info = fsrs.get_card_info(f"sentence_{sentence['id']}", user_id)

        result = await _enrich_sentence_async(sentence)
        if card_info:
            result["fsrs"] = card_info
        _auto_register_words(sentence["text"], user_id)
        return {
            "sentence": result,
            "type": "new",
            "mode": "sequential",
            "position": pos,
            "total": len(filtered),
            "data_changed": False,
            "start_id": effective_start,
            "end_id": effective_end,
        }
    else:
        # 原有逻辑：使用列表位置
        pos = pos_info.get("position", 0)

        # 如果数据变化了，不自动前进
        if data_changed:
            if pos >= current_count:
                pos = 0
            sentence = PRESET_SENTENCES[pos]
            result = await _enrich_sentence_async(sentence)
            _auto_register_words(sentence["text"], user_id)
            return {
                "sentence": result,
                "type": "new",
                "mode": "sequential",
                "data_changed": True,
                "position": pos,
                "total": current_count,
                "message": "句子数据已变更，请确认起始位置",
            }

        if pos >= current_count:
            pos = 0  # 循环

        sentence = PRESET_SENTENCES[pos]
        next_pos = pos + 1
        learning.set_sequential_position(user_id, next_pos, sentences_count=current_count)

        # 确保 FSRS 卡片存在
        fsrs.ensure_card(f"sentence_{sentence['id']}", card_type="sentence", user_id=user_id)

        # 获取 FSRS 卡片信息
        card_info = fsrs.get_card_info(f"sentence_{sentence['id']}", user_id)

        result = await _enrich_sentence_async(sentence)
        if card_info:
            result["fsrs"] = card_info
        _auto_register_words(sentence["text"], user_id)
        return {
            "sentence": result,
            "type": "new",
            "mode": "sequential",
            "position": pos,
            "total": current_count,
            "data_changed": False,
        }


@app.post("/api/mode/sequential/set-range")
async def mode_sequential_set_range(data: dict, user: dict = Depends(get_current_user)):
    """设置顺序模式的ID范围（或从某个ID开始）

    请求体：
    - start_id: 起始句子ID（1-indexed，句子的id字段），必填
    - end_id: 结束句子ID，可选（默认到最后一个句子）
    """
    user_id = user.get("id", "default")
    start_id = data.get("start_id")
    end_id = data.get("end_id")

    if start_id is None:
        raise HTTPException(status_code=400, detail="缺少 start_id")

    learning = get_learning_algorithm()
    result = learning.set_sequential_range(user_id, start_id, end_id, PRESET_SENTENCES)

    # 确保 FSRS 卡片存在
    fsrs = get_fsrs_db()
    start_sentence = None
    for s in PRESET_SENTENCES:
        if s.get("id") == start_id:
            start_sentence = s
            break

    if start_sentence:
        fsrs.ensure_card(f"sentence_{start_sentence['id']}", card_type="sentence", user_id=user_id)

    return {
        "ok": True,
        "position": result["position"],
        "start_id": result["start_id"],
        "end_id": result["end_id"],
        "sentences_count": result["sentences_count"],
        "message": f"顺序模式已设置为从ID {start_id}开始" + (f" 到ID {end_id}" if end_id else ""),
    }


@app.get("/api/mode/smart/next")
async def mode_smart_next(user: dict = Depends(get_current_user)):
    """智能模式：基于薄弱分析和FSRS复习历史推荐句子（增强版）"""
    user_id = user.get("id", "default")
    learning = get_learning_algorithm()
    fsrs = get_fsrs_db()

    # 1. 优先复习到期卡片（使用评分函数排序）
    due_cards = fsrs.get_due_cards(card_type="sentence", user_id=user_id, limit=20)
    if due_cards:
        # Score each due card's sentence using the smart recommendation score
        scored_cards = []
        for card in due_cards:
            sentence = _find_sentence_by_card_id(card["card_id"])
            if sentence:
                score = learning.get_smart_recommendation_score(user_id, sentence, PRESET_SENTENCES)
                scored_cards.append((score, card, sentence))

        if scored_cards:
            # Sort by score descending - pick the highest-scored sentence
            scored_cards.sort(key=lambda x: -x[0])
            # Pick from top 3 with some randomness for variety
            top_n = min(3, len(scored_cards))
            chosen_idx = random.randint(0, top_n - 1)
            chosen_score, chosen_card, chosen_sentence = scored_cards[chosen_idx]
            result = await _enrich_sentence_async(chosen_sentence)
            result["fsrs"] = chosen_card
            result["smart_score"] = round(chosen_score, 2)
            _auto_register_words(chosen_sentence["text"], user_id)
            return {"sentence": result, "type": "review", "mode": "smart"}

    # 2. 自适应推荐新句子（使用评分函数排序候选句子）
    weakness = learning.get_weakness_profile(user_id)
    difficulty = weakness.get("difficulty_level", "medium")

    # Filter sentences by difficulty
    difficulty_map = {"easy": ["easy"], "medium": ["easy", "medium"], "hard": ["medium", "hard"]}
    target_diffs = difficulty_map.get(difficulty, ["medium"])
    matching = [s for s in PRESET_SENTENCES if s.get("difficulty", "medium") in target_diffs]
    if not matching:
        matching = PRESET_SENTENCES

    # Score all matching sentences and pick the best
    scored_sentences = []
    for s in matching:
        score = learning.get_smart_recommendation_score(user_id, s, PRESET_SENTENCES)
        scored_sentences.append((score, s))

    if scored_sentences:
        scored_sentences.sort(key=lambda x: -x[0])
        # Pick from top 5 with some randomness
        top_n = min(5, len(scored_sentences))
        chosen_idx = random.randint(0, top_n - 1)
        chosen_score, chosen_sentence = scored_sentences[chosen_idx]
        fsrs.ensure_card(f"sentence_{chosen_sentence['id']}", card_type="sentence", user_id=user_id)
        enriched = await _enrich_sentence_async(chosen_sentence)
        enriched["smart_score"] = round(chosen_score, 2)
        _auto_register_words(chosen_sentence["text"], user_id)
        return {"sentence": enriched, "type": "new", "mode": "smart"}

    # 3. Fallback
    sentence = random.choice(PRESET_SENTENCES)
    enriched = await _enrich_sentence_async(sentence)
    _auto_register_words(sentence["text"], user_id)
    return {"sentence": enriched, "type": "new", "mode": "smart"}


@app.get("/api/mode/status")
async def mode_status(user: dict = Depends(get_current_user)):
    """获取当前学习模式状态（增强版：包含数据变更检测和智能模式信息）"""
    user_id = user.get("id", "default")
    learning = get_learning_algorithm()
    fsrs = get_fsrs_db()
    current_count = len(PRESET_SENTENCES)

    pos_info = learning.get_sequential_position(user_id)
    pos = pos_info.get("position", 0)
    stored_count = pos_info.get("sentences_count", 0)
    start_id = pos_info.get("start_id")
    end_id = pos_info.get("end_id")
    data_changed = stored_count > 0 and stored_count != current_count

    due_count = len(fsrs.get_due_cards(card_type="sentence", user_id=user_id))
    error_words = learning.get_error_words(user_id)
    word_due = len(fsrs.get_due_cards(card_type="word", user_id=user_id))

    # Smart mode info
    weakness = learning.get_weakness_profile(user_id)
    smart_mode_info = {
        "difficulty_level": weakness.get("difficulty_level", "medium"),
        "phoneme_weakness_count": len(weakness.get("phoneme_weaknesses", [])),
        "word_weakness_count": len(weakness.get("word_weaknesses", [])),
        "error_word_count": len(error_words),
    }

    return {
        "sequential_position": pos,
        "sequential_total": current_count,
        "due_reviews": due_count,
        "error_word_count": len(error_words),
        "word_due_count": word_due,
        "sentences_count": current_count,
        "stored_sentences_count": stored_count,
        "data_changed": data_changed,
        "start_id": start_id,
        "end_id": end_id,
        "smart_mode_info": smart_mode_info,
    }


# ============================================================
# 单词复习 API（FSRS 逐个推荐）
# ============================================================

@app.get("/api/words/review-queue")
async def words_review_queue(limit: int = Query(20, description="每次复习单词数量"), user: dict = Depends(get_current_user)):
    """获取单词复习队列（FSRS 逐个推荐 + 错误单词补充）
    
    策略：
    1. FSRS 到期复习单词优先
    2. 新单词（错误单词）补充
    3. 每次最多 limit 个（默认20）
    4. 每个单词包含 FSRS 状态、掌握度、错误次数等信息
    """
    user_id = user.get("id", "default")
    learning = get_learning_algorithm()
    fsrs = get_fsrs_db()
    dict_svc = get_dict_service()

    now = time.time()
    seen = set()
    queue = []

    # 1. FSRS 到期的复习单词
    due_word_cards = fsrs.get_due_cards(card_type="word", user_id=user_id, limit=limit)
    for card in due_word_cards:
        word = card["card_id"].replace("word_", "", 1)
        if word not in seen:
            seen.add(word)
            word_detail = dict_svc.lookup(word, local_only=True)
            queue.append({
                "word": word,
                "type": "review",
                "card_id": card["card_id"],
                "fsrs_state": card["state_name"],
                "fsrs_difficulty": card.get("difficulty", 0),
                "fsrs_stability": card.get("stability", 0),
                "fsrs_reps": card.get("reps", 0),
                "fsrs_scheduled_days": card.get("scheduled_days", 0),
                **_build_word_detail(word, word_detail),
            })

    # 2. 错误单词（按错误次数排序，不重复）
    if len(queue) < limit:
        error_words = learning.get_error_words(user_id)
        for ew in error_words:
            if len(queue) >= limit:
                break
            word = ew["word"]
            if word not in seen:
                seen.add(word)
                card_id = f"word_{word}"
                fsrs.ensure_card(card_id, card_type="word", user_id=user_id)
                card_info = fsrs.get_card_info(card_id, user_id)
                word_detail = dict_svc.lookup(word, local_only=True)
                queue.append({
                    "word": word,
                    "type": "new",
                    "card_id": card_id,
                    "dictation_errors": ew.get("dictation_errors", 0),
                    "pronunciation_errors": ew.get("pronunciation_errors", 0),
                    "total_errors": ew.get("total_errors", 0),
                    "fsrs_state": card_info.get("state_name", "new") if card_info else "new",
                    "fsrs_difficulty": card_info.get("difficulty", 0) if card_info else 0,
                    "fsrs_reps": card_info.get("reps", 0) if card_info else 0,
                    **_build_word_detail(word, word_detail),
                })

    # 3. 如果还不够，从新卡片中补充
    if len(queue) < limit:
        new_card_ids = fsrs.get_new_cards(card_type="word", user_id=user_id, limit=limit - len(queue))
        for card_id in new_card_ids:
            word = card_id.replace("word_", "", 1)
            if word not in seen:
                seen.add(word)
                word_detail = dict_svc.lookup(word, local_only=True)
                queue.append({
                    "word": word,
                    "type": "new",
                    "card_id": card_id,
                    "fsrs_state": "new",
                    "fsrs_difficulty": 0,
                    "fsrs_reps": 0,
                    **_build_word_detail(word, word_detail),
                })

    # 获取复习统计
    review_stats = fsrs.get_word_review_stats(user_id)

    return {
        "queue": queue,
        "total": len(queue),
        "review_stats": review_stats,
    }


@app.get("/api/words/next-review")
async def words_next_review(skip: str = Query("", description="已复习的card_id列表，逗号分隔"), user: dict = Depends(get_current_user)):
    """获取下一个需要复习的单词（FSRS 推荐，一次一个）
    
    返回单个单词的完整信息，包含：
    - FSRS 状态、掌握度、可回忆率
    - 词典信息（音标、释义）
    - 错误记录（听写/发音错误次数）
    
    skip 参数：本次会话已复习的 card_id 列表（逗号分隔），避免重复推荐同一单词
    """
    user_id = user.get("id", "default")
    fsrs = get_fsrs_db()
    learning = get_learning_algorithm()
    dict_svc = get_dict_service()

    # 解析 skip_ids
    skip_ids = [s.strip() for s in skip.split(",") if s.strip()] if skip else None

    # FSRS 推荐下一个
    next_card = fsrs.get_next_word_for_review(user_id, skip_ids=skip_ids)
    if not next_card:
        return {"word": None, "message": "暂无需要复习的单词"}

    word = next_card["card_id"].replace("word_", "", 1)
    word_detail = dict_svc.lookup(word, local_only=True)

    # 获取错误记录
    error_words = learning.get_error_words(user_id)
    error_info = next((ew for ew in error_words if ew["word"] == word), None)

    # 获取 FSRS 详细信息
    card_info = fsrs.get_card_info(next_card["card_id"], user_id)

    # 获取复习统计
    review_stats = fsrs.get_word_review_stats(user_id)

    result = {
        "word": word,
        "type": next_card["type"],
        "card_id": next_card["card_id"],
        "fsrs_state": next_card.get("state_name", "new"),
        "fsrs_difficulty": next_card.get("difficulty", 0),
        "fsrs_stability": next_card.get("stability", 0),
        "fsrs_reps": next_card.get("reps", 0),
        "fsrs_scheduled_days": next_card.get("scheduled_days", 0),
        "dictation_errors": error_info.get("dictation_errors", 0) if error_info else 0,
        "pronunciation_errors": error_info.get("pronunciation_errors", 0) if error_info else 0,
        "total_errors": error_info.get("total_errors", 0) if error_info else 0,
        "review_stats": review_stats,
        **_build_word_detail(word, word_detail),
    }

    if card_info:
        result["fsrs_retrievability"] = card_info.get("retrievability", 0)
        result["fsrs_last_review"] = card_info.get("last_review", 0)

    return result


@app.post("/api/words/review")
async def words_review_rate(data: dict, user: dict = Depends(get_current_user)):
    """单词复习评级（4级：1=没印象, 2=难, 3=模糊, 4=掌握）"""
    word = data.get("word")
    rating = data.get("rating")  # 1-4
    user_id = user.get("id", "default")

    if not word:
        raise HTTPException(status_code=400, detail="缺少 word")
    if rating not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="rating 必须为 1-4")

    card_id = f"word_{word}"
    fsrs = get_fsrs_db()
    fsrs.ensure_card(card_id, card_type="word", user_id=user_id)
    result = fsrs.review_card(card_id, rating, card_type="word", user_id=user_id)

    # If rating is Easy(4) and FSRS considers this mastered, reduce error count
    # Only reduce for Easy ratings to avoid clearing errors too quickly
    if rating == 4:
        card_info = fsrs.get_card_info(card_id, user_id)
        if card_info and card_info.get("state") == 2 and card_info.get("scheduled_days", 0) >= 1:
            learning = get_learning_algorithm()
            import sqlite3 as _sql
            conn = _sql.connect(learning.db_path)
            conn.execute(
                "UPDATE user_word_errors SET count = MAX(0, count - 1) WHERE user_id = ? AND word = ?",
                (user_id, word)
            )
            conn.commit()
            conn.close()

    return result


@app.get("/api/words/errors")
async def words_errors(user: dict = Depends(get_current_user)):
    """获取所有错误单词"""
    user_id = user.get("id", "default")
    learning = get_learning_algorithm()
    error_words = learning.get_error_words(user_id)

    # Enrich with dictionary data
    dict_svc = get_dict_service()
    for ew in error_words:
        word = ew["word"]
        word_detail = dict_svc.lookup(word, local_only=True)
        ew["ipa"] = word_detail.get("ipa", "")
        ew["meaning"] = word_detail.get("meaning", "")
        ew["pos"] = word_detail.get("pos", "")

    return {"words": error_words, "total": len(error_words)}


@app.get("/api/words/error-stats")
async def words_error_stats(user: dict = Depends(get_current_user)):
    """获取单词错误统计（按类型分组，含FSRS状态）
    
    返回：
    - pronunciation_errors: 经常读错的单词列表
    - dictation_errors: 经常听写错的单词列表
    - summary: 总体统计
    """
    user_id = user.get("id", "default")
    learning = get_learning_algorithm()
    fsrs = get_fsrs_db()
    dict_svc = get_dict_service()

    all_errors = learning.get_error_words(user_id)
    pron_errors = []
    dict_errors = []

    for ew in all_errors:
        word = ew["word"]
        card_id = f"word_{word}"
        fsrs.ensure_card(card_id, card_type="word", user_id=user_id)
        card_info = fsrs.get_card_info(card_id, user_id)
        word_detail = dict_svc.lookup(word, local_only=True)

        entry = {
            "word": word,
            "ipa": word_detail.get("ipa", ""),
            "meaning": word_detail.get("meaning", ""),
            "pos": word_detail.get("pos", ""),
            "fsrs_state": card_info.get("state_name", "new") if card_info else "new",
            "fsrs_reps": card_info.get("reps", 0) if card_info else 0,
            "fsrs_scheduled_days": card_info.get("scheduled_days", 0) if card_info else 0,
        }

        if ew.get("pronunciation_errors", 0) > 0:
            entry["pronunciation_errors"] = ew["pronunciation_errors"]
            pron_errors.append(entry)

        if ew.get("dictation_errors", 0) > 0:
            entry["dictation_errors"] = ew["dictation_errors"]
            dict_errors.append(entry)

    # Sort by error count descending
    pron_errors.sort(key=lambda x: x.get("pronunciation_errors", 0), reverse=True)
    dict_errors.sort(key=lambda x: x.get("dictation_errors", 0), reverse=True)

    return {
        "pronunciation_errors": pron_errors,
        "dictation_errors": dict_errors,
        "summary": {
            "total_pron_errors": len(pron_errors),
            "total_dict_errors": len(dict_errors),
            "total_unique_errors": len(all_errors),
        }
    }


@app.get("/api/words/practice-next")
async def words_practice_next(mode: str = Query("all", description="练习模式: all/pronunciation/dictation"), skip: str = Query("", description="已练习的word列表，逗号分隔"), user: dict = Depends(get_current_user)):
    """获取下一个练习单词（FSRS自动推荐，支持按错误类型过滤）
    
    与 /api/words/next-review 的区别：
    - 新词也算可练习（不只是到期复习）
    - 加权随机：新词70% + 到期复习30%
    - 无手动评级，由后续评分自动FSRS评级
    - 包含TTS可用性、错误统计等完整信息
    
    mode 参数：
    - all: 所有未掌握单词（默认）
    - pronunciation: 仅读错过的单词
    - dictation: 仅听写错过的单词
    
    skip 参数：本次会话已练习的 word 列表（逗号分隔），避免重复推荐
    """
    user_id = user.get("id", "default")
    fsrs = get_fsrs_db()
    learning = get_learning_algorithm()
    dict_svc = get_dict_service()

    # 解析 skip 列表
    skip_words = set(s.strip().lower() for s in skip.split(",") if s.strip()) if skip else set()

    if mode == "pronunciation" or mode == "dictation":
        # 错误词优先模式：只从错误词中选择
        error_type = "pronunciation" if mode == "pronunciation" else "dictation"
        all_errors = learning.get_error_words(user_id)
        
        # 过滤对应类型的错误词
        if error_type == "pronunciation":
            error_words = [ew for ew in all_errors if ew.get("pronunciation_errors", 0) > 0]
        else:
            error_words = [ew for ew in all_errors if ew.get("dictation_errors", 0) > 0]
        
        # 排除本次已练习的词
        if skip_words:
            error_words = [ew for ew in error_words if ew["word"].lower() not in skip_words]
        
        if not error_words:
            return {"word": None, "message": f"暂无{'读错' if mode == 'pronunciation' else '听写错误'}的单词", "total_reviewable": 0, "review_stats": fsrs.get_word_review_stats(user_id)}
        
        # 按错误次数排序（多的优先），然后按 FSRS 状态（未掌握优先）
        # 为每个错误词确保有 FSRS 卡片并获取状态
        error_word_data = []
        for ew in error_words:
            word = ew["word"]
            card_id = f"word_{word}"
            fsrs.ensure_card(card_id, card_type="word", user_id=user_id)
            card_info = fsrs.get_card_info(card_id, user_id)
            
            # 错误词模式：不跳过已掌握的（用户明确要求练习错误词，即使FSRS认为已掌握）
            # 但将已掌握的排在后面
            
            error_word_data.append({
                "word": word,
                "card_info": card_info,
                "errors": ew.get(f"{error_type}_errors", 0),
                "is_mastered": bool(card_info and card_info["state"] == 2 and card_info["scheduled_days"] >= 1),
            })
        
        if not error_word_data:
            return {"word": None, "message": f"所有{'读错' if mode == 'pronunciation' else '听写错误'}的单词已掌握", "total_reviewable": 0, "review_stats": fsrs.get_word_review_stats(user_id)}
        
        # 排序：未掌握优先 > 错误次数多 > FSRS难度高 > 复习次数少
        error_word_data.sort(key=lambda x: (x["is_mastered"], -x["errors"], -(x["card_info"].get("difficulty", 0) if x["card_info"] else 0), x["card_info"].get("reps", 0) if x["card_info"] else 0))
        
        # 从前5个中随机选一个（避免太单调）
        top_n = min(5, len(error_word_data))
        chosen = random.choice(error_word_data[:top_n])
        
        word = chosen["word"]
        word_detail = dict_svc.lookup(word, local_only=True)
        card_info = chosen["card_info"]
        error_info = next((ew for ew in all_errors if ew["word"] == word), None)
        
        review_stats = fsrs.get_word_review_stats(user_id)
        total_reviewable = len([x for x in error_word_data if not x["is_mastered"]])
        if total_reviewable == 0:
            total_reviewable = len(error_word_data)
        
        result = {
            "word": word,
            "type": "error_review",
            "card_id": f"word_{word}",
            "fsrs_state": card_info.get("state_name", "new") if card_info else "new",
            "fsrs_difficulty": card_info.get("difficulty", 0) if card_info else 0,
            "fsrs_stability": card_info.get("stability", 0) if card_info else 0,
            "fsrs_reps": card_info.get("reps", 0) if card_info else 0,
            "fsrs_scheduled_days": card_info.get("scheduled_days", 0) if card_info else 0,
            "fsrs_retrievability": card_info.get("retrievability", 0) if card_info else 0,
            "dictation_errors": error_info.get("dictation_errors", 0) if error_info else 0,
            "pronunciation_errors": error_info.get("pronunciation_errors", 0) if error_info else 0,
            "total_errors": error_info.get("total_errors", 0) if error_info else 0,
            "review_stats": review_stats,
            "total_reviewable": total_reviewable,
            **_build_word_detail(word, word_detail),
        }
        return result

    # 默认模式：所有未掌握单词
    next_card = fsrs.get_next_word_for_practice(user_id)
    if not next_card:
        return {"word": None, "message": "暂无可练习的单词", "total_reviewable": 0, "review_stats": fsrs.get_word_review_stats(user_id)}

    word = next_card["card_id"].replace("word_", "", 1)
    word_detail = dict_svc.lookup(word, local_only=True)
    card_info = fsrs.get_card_info(next_card["card_id"], user_id)

    # 获取错误记录
    error_words = learning.get_error_words(user_id)
    error_info = next((ew for ew in error_words if ew["word"] == word), None)

    # 练习统计
    review_stats = fsrs.get_word_review_stats(user_id)
    total_reviewable = fsrs.get_total_reviewable_count("word", user_id)

    result = {
        "word": word,
        "type": next_card["type"],
        "card_id": next_card["card_id"],
        "fsrs_state": next_card.get("state_name", "new"),
        "fsrs_difficulty": next_card.get("difficulty", 0),
        "fsrs_stability": next_card.get("stability", 0),
        "fsrs_reps": next_card.get("reps", 0),
        "fsrs_scheduled_days": next_card.get("scheduled_days", 0),
        "fsrs_retrievability": card_info.get("retrievability", 0) if card_info else 0,
        "dictation_errors": error_info.get("dictation_errors", 0) if error_info else 0,
        "pronunciation_errors": error_info.get("pronunciation_errors", 0) if error_info else 0,
        "total_errors": error_info.get("total_errors", 0) if error_info else 0,
        "review_stats": review_stats,
        "total_reviewable": total_reviewable,
        **_build_word_detail(word, word_detail),
    }

    return result


@app.post("/api/words/practice-evaluate")
async def words_practice_evaluate(
    audio: UploadFile = File(...),
    word: str = Form(...),
    user: dict = Depends(get_current_user),
):
    """单词跟读练习：评估发音→自动FSRS评级→返回结果+下一个推荐词
    
    自动评级规则：
    - 发音准确率 >= 90%: Easy(4)
    - 发音准确率 >= 70%: Good(3)
    - 发音准确率 >= 50%: Hard(2)
    - 发音准确率 < 50%: Again(1)
    """
    user_id = user.get("id", "default")

    try:
        g2p = get_g2p_service()
        expected_phonemes = g2p.text_to_phonemes(word)

        if not expected_phonemes:
            raise HTTPException(status_code=400, detail="无法生成音素序列")

        # Save audio to temp file
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

            word_phonemes = g2p.text_to_phonemes_with_words(word)

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
            response["word"] = word

            # 计算发音分数（0-100）
            pronunciation_score = response.get("scores", {}).get("pronunciation", 0)
            overall_score = response.get("scores", {}).get("overall", 0)
            effective_score = max(pronunciation_score, overall_score)

            # 自动FSRS评级
            if effective_score >= 90:
                auto_rating = 4  # Easy
            elif effective_score >= 70:
                auto_rating = 3  # Good
            elif effective_score >= 50:
                auto_rating = 2  # Hard
            else:
                auto_rating = 1  # Again

            # 执行FSRS评级
            card_id = f"word_{word}"
            fsrs = get_fsrs_db()
            fsrs.ensure_card(card_id, card_type="word", user_id=user_id)
            fsrs_result = fsrs.review_card(card_id, auto_rating, card_type="word", user_id=user_id)

            # 记录发音错误（分数<60的词）
            if effective_score < 60:
                learning = get_learning_algorithm()
                try:
                    learning.record_pronunciation_errors(user_id, [{"word": word}])
                except Exception:
                    pass

            response["auto_rating"] = auto_rating
            response["auto_rating_name"] = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}[auto_rating]
            response["fsrs_result"] = fsrs_result
            response["effective_score"] = effective_score

            return response
        finally:
            os.unlink(tmp_path)

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"评测失败: {str(e)}")


@app.post("/api/words/dictation-practice")
async def words_dictation_practice(data: dict, user: dict = Depends(get_current_user)):
    """单词听写练习：检查拼写→自动FSRS评级→返回结果
    
    自动评级规则：
    - 完全正确: Easy(4)
    - near_correct (相似度>=0.8): Good(3)
    - partial (相似度>=0.6): Hard(2)
    - substitution/deletion: Again(1)
    
    大小写和标点不影响评分，可写可不写
    """
    word = _normalize_word(data.get("word", ""))
    user_input = _normalize_word(data.get("user_input", ""))
    user_id = user.get("id", "default")

    if not word:
        raise HTTPException(status_code=400, detail="缺少 word")

    # 使用编辑距离检查
    sim = _char_similarity(word, user_input)
    dist = _char_levenshtein(word, user_input)
    is_short_near = len(word) <= 4 and dist <= 1

    # 判定结果类型
    if word == user_input:
        result_type = "match"
        correct = True
        auto_rating = 4  # Easy
    elif sim >= 0.8 or is_short_near:
        result_type = "near_correct"
        correct = True
        auto_rating = 3  # Good
    elif sim >= 0.6:
        result_type = "partial"
        correct = False
        auto_rating = 2  # Hard
    else:
        result_type = "substitution"
        correct = False
        auto_rating = 1  # Again

    # FSRS评级
    card_id = f"word_{word}"
    fsrs = get_fsrs_db()
    fsrs.ensure_card(card_id, card_type="word", user_id=user_id)
    fsrs_result = fsrs.review_card(card_id, auto_rating, card_type="word", user_id=user_id)

    # 记录听写错误（非完全正确）
    if not correct or result_type == "near_correct":
        learning = get_learning_algorithm()
        try:
            learning.record_dictation_errors(user_id, [word])
        except Exception:
            pass

    return {
        "word": word,
        "user_input": user_input,
        "correct": correct,
        "type": result_type,
        "similarity": round(sim, 2),
        "edit_distance": dist,
        "auto_rating": auto_rating,
        "auto_rating_name": {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}[auto_rating],
        "fsrs_result": fsrs_result,
    }


@app.post("/api/dictation/record-errors")
async def dictation_record_errors(data: dict, user: dict = Depends(get_current_user)):
    """记录听写错误的单词（支持编辑距离容错等级）
    
    error_words 可以是：
    - 字符串数组: ["word1", "word2"]
    - 对象数组: [{word, user_input, type, similarity, edit_distance}]
    
    type 包括: substitution(完全错), partial(部分正确), near_correct(小错), deletion(漏词)
    """
    error_words_raw = data.get("error_words", [])
    sentence_id = data.get("sentence_id", "")
    user_id = user.get("id", "default")

    learning = get_learning_algorithm()
    fsrs = get_fsrs_db()
    
    recorded = 0
    for item in error_words_raw:
        if isinstance(item, dict):
            word = item.get("word", "").lower().strip()
            user_input = item.get("user_input", "").lower().strip()
            error_type = item.get("type", "substitution")
            similarity = item.get("similarity", 0)
            edit_distance = item.get("edit_distance", 0)
        else:
            word = str(item).lower().strip()
            user_input = ""
            error_type = "substitution"
            similarity = 0
            edit_distance = 0
        
        if not word:
            continue
        
        # 所有错误类型都记录到 learning_db（near_correct 也记录，因为拼写有误）
        # 但根据错误等级调整记录策略
        if error_type == "near_correct":
            # 小拼写错误：记录为拼写错误（separate error_type）
            learning.record_dictation_errors(user_id, [word], sentence_id)
        elif error_type == "partial":
            # 部分正确：记录为听写错误（相似度越低越需要关注）
            learning.record_dictation_errors(user_id, [word], sentence_id)
        elif error_type in ("substitution", "deletion"):
            # 完全错误：正常记录
            learning.record_dictation_errors(user_id, [word], sentence_id)
        
        # 为所有有错误的单词创建 FSRS 卡片
        card_id = f"word_{word}"
        fsrs.ensure_card(card_id, card_type="word", user_id=user_id)
        recorded += 1

    return {"ok": True, "recorded": recorded}


# ============================================================
# 异步词典查询 API
# ============================================================

@app.get("/api/dict/{word}")
async def lookup_word(word: str):
    """异步查询单词（本地 + 网络API回退）"""
    dict_svc = get_dict_service()
    result = await dict_svc.lookup_async(word)
    return result


# ============================================================
# 翻译 API
# ============================================================

@app.get("/api/translate")
async def translate_endpoint(
    text: str = Query(..., description="要翻译的英文文本"),
    force: bool = Query(False, description="强制重新翻译（忽略缓存）"),
    detail: bool = Query(False, description="返回详细翻译信息（含来源）"),
):
    """
    翻译英文文本到中文

    优先级：缓存 → Edge Translator → MyMemory → Google → ONNX本地模型 → 简易词典

    - force=true: 忽略缓存，重新翻译
    - detail=true: 返回翻译来源、在线API状态等详细信息
    """
    if not text or not text.strip():
        if detail:
            return {"original": text or "", "translation": "", "source": "none", "online_api_skipped": False}
        return {"translation": ""}

    # translate_text_detail 包含 CPU 密集的 ONNX 推理，放入线程池避免阻塞事件循环
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, translate_text_detail, text, force)

    if detail:
        return result
    else:
        return {"translation": result["translation"]}


@app.get("/api/translate/status")
async def translate_status_endpoint():
    """获取翻译服务状态（各引擎可用性、冷却状态）"""
    return get_translate_status()


# ============================================================
# IPA 标准发音音频 API
# ============================================================

_IPA_AUDIO_DIR = _SCRIPT_DIR / "ipa_audio"
_ARPABET_TO_AUDIO = {
    # Vowels
    'AA': _IPA_AUDIO_DIR / "vowels" / "Open_back_unrounded_vowel_ɑ.ogg.mp3",
    'AE': _IPA_AUDIO_DIR / "vowels" / "Near-open_front_unrounded_vowel_æ.ogg.mp3",
    'AH': _IPA_AUDIO_DIR / "vowels" / "Mid-central_vowel_ə.ogg.mp3",
    'AO': _IPA_AUDIO_DIR / "vowels" / "Open-mid_back_rounded_vowel_ɔ.ogg.mp3",
    'AW': None,
    'AY': None,
    'EH': _IPA_AUDIO_DIR / "vowels" / "Open-mid_front_unrounded_vowel_ɛ.ogg.mp3",
    'ER': _IPA_AUDIO_DIR / "vowels" / "Open-mid_central_unrounded_vowel_ɜ.ogg.mp3",
    'EY': None,
    'IH': _IPA_AUDIO_DIR / "vowels" / "Near-close_near-front_unrounded_vowel_ɪ.ogg.mp3",
    'IY': _IPA_AUDIO_DIR / "vowels" / "Close_front_unrounded_vowel_i.ogg.mp3",
    'OW': None,
    'OY': None,
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
    'CH': None,
    'JH': None,
    'M': _IPA_AUDIO_DIR / "consonants" / "Bilabial_nasal_m.ogg.mp3",
    'N': _IPA_AUDIO_DIR / "consonants" / "Alveolar_nasal_n.ogg.mp3",
    'NG': _IPA_AUDIO_DIR / "consonants" / "Velar_nasal_ŋ.ogg.mp3",
    'L': _IPA_AUDIO_DIR / "consonants" / "Voiced_alveolar_lateral_approximant_l.ogg.mp3",
    'R': _IPA_AUDIO_DIR / "consonants" / "archive" / "Alveolar_approximant_ɹ.ogg.mp3",
    'W': _IPA_AUDIO_DIR / "consonants" / "archive" / "Voiced_labio-velar_approximant.ogg.mp3",
    'Y': _IPA_AUDIO_DIR / "consonants" / "Voiced_palatal_approximant_j.ogg.mp3",
    'HH': _IPA_AUDIO_DIR / "consonants" / "Voiced_glottal_fricative_h.ogg.mp3",
}

_DIPHTHONG_COMPONENTS = {
    'AW': ('AA', 'UW'),
    'AY': ('AA', 'IY'),
    'EY': ('EH', 'IY'),
    'OW': ('AO', 'UW'),
    'OY': ('AO', 'IY'),
    'CH': ('T', 'SH'),
    'JH': ('D', 'ZH'),
}


@app.get("/api/ipa-audio/{arpabet}")
async def ipa_audio_endpoint(arpabet: str):
    arpabet = arpabet.upper().strip()

    # 1. 直接查找
    audio_path = _ARPABET_TO_AUDIO.get(arpabet)
    if audio_path and audio_path.is_file():
        return FileResponse(str(audio_path), media_type="audio/mpeg")

    # 2. 双元音/塞擦音
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
                "message": f"/{ARPABET_TO_IPA.get(arpabet, arpabet)}/ is a diphthong/affricate"
            }

    # 3. TTS 回退
    tts_path = generate_phoneme_audio(arpabet)
    if tts_path and os.path.exists(tts_path):
        media_type = "audio/mpeg" if tts_path.endswith(".mp3") else "audio/wav"
        return FileResponse(tts_path, media_type=media_type)

    raise HTTPException(status_code=404, detail=f"无音频: {arpabet}")


@app.get("/api/ipa-audio-info")
async def ipa_audio_info():
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
    # edge-tts 的 save_sync 是阻塞调用，放到线程池执行避免卡住事件循环
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, generate_tts, text)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    media_type = "audio/mpeg" if result["format"] == "mp3" else "audio/wav"
    headers = {}
    # 如果是静音降级，通知前端回退到浏览器 SpeechSynthesis
    if result.get("source") == "none":
        headers["X-TTS-Fallback"] = "browser_speech"
    return FileResponse(result["path"], media_type=media_type, headers=headers)


@app.get("/api/tts/phoneme")
async def tts_phoneme_endpoint(phoneme: str = Query(..., description="音素符号")):
    audio_path = generate_phoneme_audio(phoneme)
    if not audio_path:
        raise HTTPException(status_code=404, detail=f"无法为音素 '{phoneme}' 生成音频")
    media_type = "audio/mpeg" if audio_path.endswith(".mp3") else "audio/wav"
    return FileResponse(audio_path, media_type=media_type)


@app.get("/api/tts/check")
async def tts_check_endpoint():
    return check_tts_available()


# ============================================================
# 听写检查 API
# ============================================================

def _char_levenshtein(s1: str, s2: str) -> int:
    """计算两个字符串的字符级编辑距离"""
    m, n = len(s1), len(s2)
    if m == 0: return n
    if n == 0: return m
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1): dp[i][0] = i
    for j in range(n + 1): dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if s1[i-1] == s2[j-1] else 1
            dp[i][j] = min(dp[i-1][j] + 1, dp[i][j-1] + 1, dp[i-1][j-1] + cost)
    return dp[m][n]


def _char_similarity(s1: str, s2: str) -> float:
    """计算两个字符串的相似度（0~1，1=完全一致）"""
    max_len = max(len(s1), len(s2))
    if max_len == 0: return 1.0
    dist = _char_levenshtein(s1, s2)
    return 1.0 - dist / max_len

def _levenshtein_align(expected_words: list, user_words: list) -> list:
    """Levenshtein 距离对齐，返回 5 元组 (expected, actual, type, expected_idx, user_idx)

    expected_idx/user_idx 是原始数组中的位置索引，-1 表示无对应（deletion/insertion）。
    """
    m, n = len(expected_words), len(user_words)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    trace = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        dp[i][0] = dp[i - 1][0] + 1
        trace[i][0] = 1
    for j in range(1, n + 1):
        dp[0][j] = dp[0][j - 1] + 1
        trace[0][j] = 2

    for i in range(1, m + 1):
        for j in range(1, n + 1):
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

    alignment = []
    i, j = m, n
    while i > 0 or j > 0:
        if i > 0 and j > 0 and trace[i][j] == 0:
            align_type = "match" if expected_words[i - 1] == user_words[j - 1] else "substitution"
            alignment.append((expected_words[i - 1], user_words[j - 1], align_type, i - 1, j - 1))
            i -= 1
            j -= 1
        elif i > 0 and trace[i][j] == 1:
            alignment.append((expected_words[i - 1], "", "deletion", i - 1, -1))
            i -= 1
        else:
            alignment.append(("", user_words[j - 1], "insertion", -1, j - 1))
            j -= 1

    alignment.reverse()
    return alignment


def _normalize_word(w: str) -> str:
    """Normalize word for comparison: lowercase + strip punctuation (keep apostrophes/hyphens)"""
    return re.sub(r"[^a-zA-Z'\-]", "", w).lower()

@app.post("/api/dictation/check")
async def dictation_check(data: dict):
    expected = data.get("text", data.get("sentence_text", "")).strip()
    user_input_raw = data.get("user_input", "")

    # 保留空字符串用于位置映射（关键：空输入框不能被吞掉）
    if isinstance(user_input_raw, list):
        all_user_items = [str(w).strip() for w in user_input_raw]
    else:
        all_user_items = str(user_input_raw).strip().split()

    # 构建非空词及其在 all_user_items 中的索引
    non_empty_words_raw = []  # (index_in_all, word)
    for idx, w in enumerate(all_user_items):
        if w:
            non_empty_words_raw.append((idx, w))

    # Normalize: lowercase + strip punctuation for comparison (case/punctuation don't affect scoring)
    expected_words = [_normalize_word(w) for w in expected.split()]
    # 非空用户词 normalize
    non_empty_indices = [idx for idx, _ in non_empty_words_raw]  # 原始输入框索引列表
    user_words = [_normalize_word(w) for _, w in non_empty_words_raw]
    # Remove empty words after normalization
    expected_words = [w for w in expected_words if w]
    user_words = [w for w in user_words if w]

    # Keep original words for display (with original case/punctuation)
    original_expected_words = expected.split()
    original_user_words = [w for _, w in non_empty_words_raw]  # 只取非空原始词

    alignment = _levenshtein_align(expected_words, user_words)

    # 检查单词顺序：matched 词的 user_index 是否严格递增
    # 如果用户把词写在错误的位置（相对顺序不对），应该扣分
    order_error_count = 0

    # Map alignment back to original words for display
    orig_ew_idx = 0  # index into original_expected_words
    orig_uw_idx = 0  # index into original_user_words (non-empty only)
    last_user_idx = -1  # 上一个 matched/substitution 的 user_index，用于检测顺序

    results = []
    # 阈值：相似度 >= 0.6 算"部分正确"，>= 0.8 算"基本正确"
    # 短词（<=4字母）特殊处理：编辑距离<=1就算near_correct
    PARTIAL_THRESHOLD = 0.6
    NEAR_CORRECT_THRESHOLD = 0.8
    
    # Error type counters for summary
    spelling_count = 0
    omission_count = 0
    addition_count = 0
    
    for ew, uw, align_type, ei, ui in alignment:
        # Get original words for display
        orig_ew = original_expected_words[orig_ew_idx] if orig_ew_idx < len(original_expected_words) else ew
        orig_uw = original_user_words[orig_uw_idx] if orig_uw_idx < len(original_user_words) else uw
        
        if align_type == "match":
            # 检查顺序：用户输入的相对位置必须递增
            is_order_wrong = ui <= last_user_idx
            last_user_idx = ui

            if is_order_wrong:
                # 拼写正确但顺序错误，扣分
                results.append({"expected": ew, "expected_original": orig_ew, "actual": uw, "actual_original": orig_uw, "correct": False, "type": "order_error"})
                order_error_count += 1
            else:
                results.append({"expected": ew, "expected_original": orig_ew, "actual": uw, "actual_original": orig_uw, "correct": True, "type": "match"})
            orig_ew_idx += 1
            orig_uw_idx += 1
        elif align_type == "substitution":
            last_user_idx = ui
            sim = _char_similarity(ew, uw)
            dist = _char_levenshtein(ew, uw)
            # 短词特殊处理：3-4字母的词编辑距离1就算near_correct
            is_short_near = len(ew) <= 4 and dist <= 1
            if sim >= NEAR_CORRECT_THRESHOLD or is_short_near:
                results.append({
                    "expected": ew, "expected_original": orig_ew, "actual": uw, "actual_original": orig_uw, "correct": True, 
                    "type": "near_correct", "similarity": round(sim, 2),
                    "edit_distance": dist,
                })
            elif sim >= PARTIAL_THRESHOLD:
                results.append({
                    "expected": ew, "expected_original": orig_ew, "actual": uw, "actual_original": orig_uw, "correct": False, 
                    "type": "partial", "similarity": round(sim, 2),
                    "edit_distance": dist,
                })
                spelling_count += 1
            else:
                results.append({"expected": ew, "expected_original": orig_ew, "actual": uw, "actual_original": orig_uw, "correct": False, "type": "substitution"})
                spelling_count += 1
            orig_ew_idx += 1
            orig_uw_idx += 1
        elif align_type == "deletion":
            results.append({"expected": ew, "expected_original": orig_ew, "actual": "", "actual_original": "", "correct": False, "type": "deletion"})
            omission_count += 1
            orig_ew_idx += 1
        elif align_type == "insertion":
            last_user_idx = ui
            results.append({"expected": "", "expected_original": "", "actual": uw, "actual_original": orig_uw, "correct": False, "type": "insertion"})
            addition_count += 1
            orig_uw_idx += 1

    # 评分：漏写/多写也扣分，分母用 total_expected
    correct_count = sum(1 for r in results if r["correct"])
    partial_count = sum(1 for r in results if r.get("type") == "partial")
    total_expected = len(expected_words)
    # 近似正确算满分，部分正确算半分，漏写/多写/顺序错/拼写错 0 分
    accuracy = (correct_count + partial_count * 0.5) / max(total_expected, 1) * 100

    # 错误单词：完全错误和部分错误的都记录
    # 但部分正确的标记为不同级别
    # 漏写和漏写不记录为error_words（不影响其他词的分数）
    error_words = []
    for r in results:
        if not r["correct"] and r["expected"]:
            error_words.append({
                "word": r["expected"],
                "user_input": r.get("actual", ""),
                "type": r.get("type", "substitution"),
                "similarity": r.get("similarity", 0),
                "edit_distance": r.get("edit_distance", 0),
            })
        elif r.get("type") == "near_correct" and r["expected"]:
            # near_correct 虽然算正确，但也记录为"需关注"的单词
            error_words.append({
                "word": r["expected"],
                "user_input": r.get("actual", ""),
                "type": "near_correct",
                "similarity": r.get("similarity", 0),
                "edit_distance": r.get("edit_distance", 0),
            })
        elif r.get("type") == "deletion":
            # 漏写也记录为需关注的单词
            error_words.append({
                "word": r["expected"],
                "user_input": "",
                "type": "deletion",
                "similarity": 0,
                "edit_distance": len(r["expected"]),
            })

    return {
        "results": results,
        "accuracy": round(accuracy, 1),
        "expected": expected,
        "user_input": " ".join(all_user_items),
        "error_words": error_words,
        "error_summary": {
            "spelling": spelling_count,
            "omission": omission_count,
            "addition": addition_count,
            "order_error": order_error_count,
        },
        "non_empty_indices": non_empty_indices,
        "empty_input_indices": [idx for idx, w in enumerate(all_user_items) if not w],
    }


# ============================================================
# 音频评测 API
# ============================================================

def _load_audio_file(file_path: str):
    import soundfile as sf
    import librosa

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

    try:
        audio_data, sr = librosa.load(file_path, sr=16000, mono=True)
        return audio_data.astype(np.float32), 16000
    except Exception:
        pass

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

    raise RuntimeError("无法读取音频文件，请安装 ffmpeg")


@app.post("/api/evaluate")
async def evaluate_audio(
    audio: UploadFile = File(...),
    sentence_text: str = Form(...),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id", "default")
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

            # 异步查询单词详情（本地 + 网络API，并发查询）
            words = sentence_text.lower().split()
            dict_svc = get_dict_service()
            word_lookup_tasks = [dict_svc.lookup_async(w) for w in words]
            word_lookup_results = await asyncio.gather(*word_lookup_tasks, return_exceptions=True)
            word_details = []
            for w, detail in zip(words, word_lookup_results):
                if isinstance(detail, Exception):
                    detail = dict_svc.lookup(w, local_only=True)
                word_details.append(_build_word_detail(w, detail))

            response["word_details"] = word_details

            # 记录评测结果到学习系统
            try:
                learning = get_learning_algorithm()
                # Build error list for learning system
                errors_for_learning = []
                for err in (eval_result.errors or []):
                    err_dict = {
                        "expected": err.expected if hasattr(err, 'expected') else str(err),
                        "actual": err.actual if hasattr(err, 'actual') else '',
                        "type": err.type if hasattr(err, 'type') else 'substitution',
                    }
                    errors_for_learning.append(err_dict)

                # Build word scores for learning system
                word_scores_for_learning = []
                for w in (response.get("words") or []):
                    word_scores_for_learning.append({
                        "word": w.get("word", ""),
                        "accuracy": w.get("accuracy", 0),
                    })

                learning.record_evaluation(
                    user_id=user_id,
                    sentence_id=sentence_text[:50],
                    overall_score=response.get("scores", {}).get("overall", 0),
                    pronunciation_score=response.get("scores", {}).get("pronunciation", 0),
                    completeness_score=response.get("scores", {}).get("completeness", 0),
                    fluency_score=response.get("scores", {}).get("fluency", 0),
                    errors=errors_for_learning,
                    word_scores=word_scores_for_learning,
                    duration=total_duration,
                )

                # Record pronunciation errors for words with low accuracy
                pron_error_words = []
                for w in (response.get("words") or []):
                    if w.get("accuracy", 100) < 60:
                        pron_error_words.append(w.get("word", ""))
                if pron_error_words:
                    try:
                        learning.record_pronunciation_errors(user_id, pron_error_words)
                    except Exception as e:
                        print(f"[Learning] 记录发音错误失败: {e}")

                # 为句子中所有单词创建 FSRS 卡片（确保单词复习系统覆盖所有练习过的单词）
                try:
                    fsrs = get_fsrs_db()
                    all_words_in_sentence = sentence_text.lower().split()
                    for w in all_words_in_sentence:
                        if w and len(w) > 1:  # 跳过单字母
                            card_id = f"word_{w}"
                            fsrs.ensure_card(card_id, card_type="word", user_id=user_id)
                except Exception as e:
                    print(f"[FSRS] 创建单词卡片失败: {e}")
            except Exception as e:
                print(f"[Learning] 记录评测失败: {e}")

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

def _auto_register_words(sentence_text: str, user_id: str):
    """自动注册句子中的所有单词为 FSRS 卡片（确保单词复习系统覆盖所有遇到过的单词）
    
    每个新出现的单词都要记录，但不重复。这是"待复习"功能正常工作的前提。
    """
    try:
        fsrs = get_fsrs_db()
        words = sentence_text.lower().split()
        for w in words:
            # 清理标点
            w_clean = w.strip(".,!?;:'\"()-")
            if w_clean and len(w_clean) > 1:  # 跳过单字母和空
                card_id = f"word_{w_clean}"
                fsrs.ensure_card(card_id, card_type="word", user_id=user_id)
    except Exception as e:
        print(f"[FSRS] 自动注册单词失败: {e}")


def _find_sentence_by_card_id(card_id: str):
    if card_id.startswith("sentence_"):
        try:
            sid = int(card_id.split("_", 1)[1])
            for s in PRESET_SENTENCES:
                if s["id"] == sid:
                    return s
        except (ValueError, IndexError):
            pass

    for s in PRESET_SENTENCES:
        if s["text"] == card_id:
            return s

    return None


async def _enrich_sentence_async(sentence: dict) -> dict:
    """为句子数据添加音素和单词详情（异步版本，带网络API回退）

    关键优化：翻译和词典查询均为异步执行，不阻塞事件循环。
    ctranslate2(Argos) 是 CPU 密集型操作，必须放在线程池中运行，
    否则会阻塞整个 FastAPI 事件循环，导致并发请求卡住。
    """
    text = sentence["text"]
    cached = _phoneme_cache.get(text, {})

    words = text.lower().split()

    # 异步查询单词详情（并发查询，避免逐词串行等待）
    word_details = []
    dict_svc = get_dict_service()
    word_lookup_tasks = [dict_svc.lookup_async(w) for w in words]
    word_lookup_results = await asyncio.gather(*word_lookup_tasks, return_exceptions=True)
    for w, detail in zip(words, word_lookup_results):
        if isinstance(detail, Exception):
            detail = dict_svc.lookup(w, local_only=True)
        word_details.append(_build_word_detail(w, detail))

    # 自动翻译：优先使用翻译服务（Bing/Google/Argos），最后才用词典拼接
    translation = sentence.get("translation", "")
    if not translation:
        # 1. 优先：完整句子翻译（缓存 → 在线API → Argos本地模型）
        #    关键：translate_text() 内部的 Argos/ctranslate2 是 CPU 密集操作，
        #    必须放到线程池中，否则会阻塞事件循环导致并发卡死
        try:
            loop = asyncio.get_event_loop()
            translation = await loop.run_in_executor(None, translate_text, text)
        except Exception as e:
            print(f"[翻译] 句子翻译失败: {e}")
        # 2. 兜底：从词典逐词拼接（仅当翻译服务全部失败时）
        if not translation:
            try:
                word_meanings = []
                for w, detail in zip(words, word_lookup_results):
                    if isinstance(detail, Exception):
                        info = dict_svc.lookup(w, local_only=True)
                    else:
                        info = detail
                    meaning = info.get("meaning", "")
                    if meaning:
                        short = meaning.split(";")[0].split("，")[0].strip()
                        if short:
                            word_meanings.append(f"{short}")
                if word_meanings:
                    # 使用分号分隔，避免混淆
                    translation = "；".join(word_meanings) + "（逐词释义）"
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


def _build_word_detail(word: str, info: dict) -> dict:
    """构建单词详情"""
    g2p = get_g2p_service()
    arpabet = info.get("arpabet", [])
    if not arpabet:
        arpabet = g2p.text_to_phonemes(word)
    ipa_from_g2p = G2PService.arpabet_to_ipa(arpabet) if arpabet else ""

    ipa_us = info.get("ipa_us", "")
    ipa_uk = info.get("ipa_uk", "")

    if ipa_us.startswith("/") and ipa_us.endswith("/"):
        ipa_us = ipa_us[1:-1]
    if ipa_uk.startswith("/") and ipa_uk.endswith("/"):
        ipa_uk = ipa_uk[1:-1]

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
