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
import sys
import traceback
import tempfile
import random
import asyncio
import time
import warnings
from pathlib import Path
from datetime import datetime, timezone
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
from metacognition import get_metacognition
from semantic_network import get_semantic_network

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


@app.get("/api/learning/explore-exploit")
async def get_explore_exploit_stats(user: dict = Depends(get_current_user)):
    """获取探索/利用统计数据"""
    user_id = user.get("id", "default")
    try:
        fsrs = get_fsrs_db()
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(fsrs.db_path)
        # Count new cards reviewed (exploration)
        new_reviews = conn.execute(
            "SELECT COUNT(*) FROM review_log WHERE user_id=? AND state=0",
            (user_id,)
        ).fetchone()[0]
        # Count review cards reviewed (exploitation)
        review_reviews = conn.execute(
            "SELECT COUNT(*) FROM review_log WHERE user_id=? AND state!=0",
            (user_id,)
        ).fetchone()[0]
        conn.close()

        total = new_reviews + review_reviews
        explore_ratio = new_reviews / total if total > 0 else 0.3

        return {
            "explore_ratio": round(explore_ratio, 3),
            "exploit_ratio": round(1 - explore_ratio, 3),
            "total_reviews": total,
            "new_cards_reviewed": new_reviews,
            "review_cards_reviewed": review_reviews,
        }
    except Exception:
        return {"explore_ratio": 0.3, "exploit_ratio": 0.7, "total_reviews": 0, "new_cards_reviewed": 0, "review_cards_reviewed": 0}


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

        # 错误音素统计（包含错误率百分比）
        phoneme_rows = conn2.execute(
            "SELECT phoneme, total_attempts, error_count, error_rate FROM user_phoneme_stats WHERE user_id = ? ORDER BY error_count DESC",
            (user_id,)
        ).fetchall()
        error_phonemes = {}
        for r in phoneme_rows:
            error_phonemes[r[0]] = {
                "count": r[2],
                "total": r[1],
                "rate": round(r[3] * 100, 1) if r[3] else 0
            }

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

    return {
        "total_practice": total_practice,
        "recent_scores": recent_scores,
        "error_phonemes": error_phonemes,
        "words_learned": words_learned,
        "analytics": analytics,
        "fsrs_stats": fsrs_stats,
        "word_review_stats": word_review_stats,
        "weakness": weakness,
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
async def fsrs_next(
    card_type: str = Query("sentence"),
    exclude: Optional[str] = Query(None, description="排除的卡片ID(逗号分隔)"),
    user: dict = Depends(get_current_user)
):
    user_id = user.get("id", "default")
    exclude_ids = []
    if exclude:
        exclude_ids = [x.strip() for x in exclude.split(',') if x.strip()]
    try:
        fsrs = get_fsrs_db()
        queue = fsrs.get_review_queue(card_type=card_type, user_id=user_id, new_per_day=5, exclude_card_ids=exclude_ids)

        if queue:
            review_cards = [q for q in queue if q["type"] == "review"]
            new_cards = [q for q in queue if q["type"] == "new"]

            # 混合策略：新词70% + 复习30%
            candidates = []
            weights = []
            for card in review_cards:
                candidates.append(("review", card))
                weights.append(3.0)
            for card in new_cards:
                candidates.append(("new", card))
                weights.append(7.0)
            
            if candidates:
                total_weight = sum(weights)
                rand = random.random() * total_weight
                cumulative = 0
                chosen = candidates[0]
                sentence_type = "new"
                for c, w in zip(candidates, weights):
                    cumulative += w
                    if rand <= cumulative:
                        chosen = c
                        break
                
                sentence_type, chosen_card = chosen
                sentence = _find_sentence_by_card_id(chosen_card["card_id"])
                if sentence:
                    result = await _enrich_sentence_async(sentence)
                    result["fsrs"] = chosen_card
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
        # 确定类型：如果FSRS卡片已经学习过，标记为review
        sentence_type = "new"
        if card_info and card_info.get("state", 0) > 0:
            sentence_type = "review"
        return {
            "sentence": result,
            "type": sentence_type,
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
        # 确定类型：如果FSRS卡片已经学习过，标记为review
        sentence_type = "new"
        if card_info and card_info.get("state", 0) > 0:
            sentence_type = "review"
        return {
            "sentence": result,
            "type": sentence_type,
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
async def mode_smart_next(
    exclude: Optional[str] = Query(None, description="排除的卡片ID(逗号分隔)"),
    user: dict = Depends(get_current_user)
):
    """智能模式：基于薄弱分析和FSRS复习历史推荐句子（增强版）"""
    user_id = user.get("id", "default")
    learning = get_learning_algorithm()
    fsrs = get_fsrs_db()
    
    # Parse exclude list to avoid repeating the same card
    exclude_ids = []
    if exclude:
        exclude_ids = [x.strip() for x in exclude.split(',') if x.strip()]

    # 1. 混合策略：新句子约70%，到期复习约30%，避免频繁重复复习
    # 先收集到期复习卡片和新句子卡片
    due_cards = fsrs.get_due_cards(card_type="sentence", user_id=user_id, limit=10, exclude_card_ids=exclude_ids)
    new_card_ids = fsrs.get_new_cards(card_type="sentence", user_id=user_id, limit=10)
    
    # 加权随机选择：新词70%，复习30%
    candidates = []
    weights = []
    
    for card in (due_cards or []):
        sentence = _find_sentence_by_card_id(card["card_id"])
        if sentence:
            score = learning.get_smart_recommendation_score(user_id, sentence, PRESET_SENTENCES)
            candidates.append(("review", card, sentence, score))
            weights.append(3.0)  # 复习权重30%
    
    for card_id in (new_card_ids or []):
        sentence = _find_sentence_by_card_id(card_id)
        if sentence:
            score = learning.get_smart_recommendation_score(user_id, sentence, PRESET_SENTENCES)
            candidates.append(("new", None, sentence, score))
            weights.append(7.0)  # 新词权重70%
    
    if candidates:
        # 按smart score加权随机选择
        total_weight = sum(weights)
        rand = random.random() * total_weight
        cumulative = 0
        chosen_idx = 0
        for i, w in enumerate(weights):
            cumulative += w
            if rand <= cumulative:
                chosen_idx = i
                break
        
        card_type_chosen, chosen_card, chosen_sentence, chosen_score = candidates[chosen_idx]
        result = await _enrich_sentence_async(chosen_sentence)
        if chosen_card:
            result["fsrs"] = chosen_card
        
        # 确定句子类型：即使后端标记为"new"，也要检查FSRS状态
        # 如果卡片已经学习过（state != NEW / reps > 0），应标记为"review"
        actual_type = card_type_chosen  # 默认使用后端类型
        if card_type_chosen == "new" and chosen_card:
            # 后端标记为new但有FSRS卡片信息 → 检查是否其实已学过
            card_state = chosen_card.get("state", 0)
            if card_state and card_state > 0:
                actual_type = "review"
        elif card_type_chosen == "new":
            # 没有chosen_card信息，但句子可能已被评测过
            # 通过FSRS卡片检查
            card_id = f"sentence_{chosen_sentence['id']}"
            card_info = fsrs.get_card_info(card_id, user_id)
            if card_info and card_info.get("state", 0) > 0:
                actual_type = "review"
        
        result["smart_score"] = round(chosen_score, 2)
        _auto_register_words(chosen_sentence["text"], user_id)
        return {"sentence": result, "type": actual_type, "mode": "smart"}

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
        card_info = fsrs.get_card_info(f"sentence_{chosen_sentence['id']}", user_id)
        enriched = await _enrich_sentence_async(chosen_sentence)
        enriched["smart_score"] = round(chosen_score, 2)
        if card_info:
            enriched["fsrs"] = card_info
        _auto_register_words(chosen_sentence["text"], user_id)
        # 检查是否已学过
        sentence_type = "new"
        if card_info and card_info.get("state", 0) > 0:
            sentence_type = "review"
        return {"sentence": enriched, "type": sentence_type, "mode": "smart"}

    # 3. Fallback
    sentence = random.choice(PRESET_SENTENCES)
    enriched = await _enrich_sentence_async(sentence)
    _auto_register_words(sentence["text"], user_id)
    # 检查是否已学过
    card_info = fsrs.get_card_info(f"sentence_{sentence['id']}", user_id)
    sentence_type = "new"
    if card_info and card_info.get("state", 0) > 0:
        sentence_type = "review"
    return {"sentence": enriched, "type": sentence_type, "mode": "smart"}


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
async def words_next_review(user: dict = Depends(get_current_user)):
    """获取下一个需要复习的单词（FSRS 推荐，一次一个）
    
    返回单个单词的完整信息，包含：
    - FSRS 状态、掌握度、可回忆率
    - 词典信息（音标、释义）
    - 错误记录（听写/发音错误次数）
    """
    user_id = user.get("id", "default")
    fsrs = get_fsrs_db()
    learning = get_learning_algorithm()
    dict_svc = get_dict_service()

    # FSRS 推荐下一个
    next_card = fsrs.get_next_word_for_review(user_id)
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

    # If mastered (rating 4), optionally reduce error count
    if rating >= 3:
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

        # Get pronunciation-specific and dictation-specific attempt counts
        # from user_word_errors table (which tracks per-type error counts)
        # Also get total attempts from user_word_progress
        word_progress = learning.get_word_progress(word, user_id)
        total_attempts = word_progress.get("attempts", 0) if word_progress else 0

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
            pron_err_count = ew["pronunciation_errors"]
            # Use actual pronunciation total attempts from _attempt tracking
            pron_total = ew.get("pronunciation_total", 0)
            if pron_total <= 0:
                pron_total = max(total_attempts, pron_err_count)
            entry["pronunciation_errors"] = pron_err_count
            entry["pronunciation_total"] = pron_total
            # Rate = errors / total attempts * 100
            entry["pronunciation_rate"] = round(pron_err_count / pron_total * 100, 1) if pron_total > 0 else 0.0
            pron_errors.append(entry.copy())

        if ew.get("dictation_errors", 0) > 0:
            dict_err_count = ew["dictation_errors"]
            dict_total = ew.get("dictation_total", 0)
            if dict_total <= 0:
                dict_total = max(total_attempts, dict_err_count)
            entry["dictation_errors"] = dict_err_count
            entry["dictation_total"] = dict_total
            entry["dictation_rate"] = round(dict_err_count / dict_total * 100, 1) if dict_total > 0 else 0.0
            dict_errors.append(entry.copy())

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
async def words_practice_next(mode: str = Query("all", description="练习模式: all/pronunciation/dictation"),
                              exclude: str = Query("", description="排除的卡片ID（逗号分隔）"),
                              user: dict = Depends(get_current_user)):
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
    
    exclude 参数：排除刚复习过的卡片ID（避免LEARNING/RELEARNING短间隔后立即重复）
    """
    user_id = user.get("id", "default")
    fsrs = get_fsrs_db()
    learning = get_learning_algorithm()
    dict_svc = get_dict_service()
    
    # Parse exclude list
    exclude_ids = [x.strip() for x in exclude.split(',') if x.strip()] if exclude else []

    if mode == "pronunciation" or mode == "dictation":
        # 错误词优先模式：只从错误词中选择
        error_type = "pronunciation" if mode == "pronunciation" else "dictation"
        all_errors = learning.get_error_words(user_id)
        
        # 过滤对应类型的错误词
        if error_type == "pronunciation":
            error_words = [ew for ew in all_errors if ew.get("pronunciation_errors", 0) > 0]
        else:
            error_words = [ew for ew in all_errors if ew.get("dictation_errors", 0) > 0]
        
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
            
            # 跳过已掌握的
            if card_info and card_info["state"] == 2 and card_info["scheduled_days"] >= 3:
                continue
            
            error_word_data.append({
                "word": word,
                "card_info": card_info,
                "errors": ew.get(f"{error_type}_errors", 0),
            })
        
        if not error_word_data:
            return {"word": None, "message": f"所有{'读错' if mode == 'pronunciation' else '听写错误'}的单词已掌握", "total_reviewable": 0, "review_stats": fsrs.get_word_review_stats(user_id)}
        
        # 排序：错误次数多 > FSRS难度高 > 复习次数少
        error_word_data.sort(key=lambda x: (-x["errors"], -(x["card_info"].get("difficulty", 0) if x["card_info"] else 0), x["card_info"].get("reps", 0) if x["card_info"] else 0))
        
        # 从前5个中随机选一个（避免太单调）
        top_n = min(5, len(error_word_data))
        chosen = random.choice(error_word_data[:top_n])
        
        word = chosen["word"]
        word_detail = dict_svc.lookup(word, local_only=True)
        card_info = chosen["card_info"]
        error_info = next((ew for ew in all_errors if ew["word"] == word), None)
        
        review_stats = fsrs.get_word_review_stats(user_id)
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
    next_card = fsrs.get_next_word_for_practice(user_id, exclude_card_ids=exclude_ids)
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

            # 记录发音尝试（不论对错，用于计算错误率）
            # 使用 _clean_word 清理单词，确保与错误记录使用相同的 key
            try:
                from learning_algorithm import _clean_word
                cleaned_word = _clean_word(word)
                if cleaned_word:  # 跳过功能词/缩写
                    learning = get_learning_algorithm()
                    import sqlite3 as _sql3
                    now_ts = time.time()
                    conn_pr = _sql3.connect(learning.db_path)
                    attempt_row = conn_pr.execute(
                        "SELECT count FROM user_word_errors WHERE user_id = ? AND word = ? AND error_type = ?",
                        (user_id, cleaned_word, 'pronunciation_attempt')
                    ).fetchone()
                    if attempt_row:
                        conn_pr.execute(
                            "UPDATE user_word_errors SET count = count + 1, last_seen = ? WHERE user_id = ? AND word = ? AND error_type = ?",
                            (now_ts, user_id, cleaned_word, 'pronunciation_attempt')
                        )
                    else:
                        conn_pr.execute(
                            "INSERT INTO user_word_errors (user_id, word, error_type, count, first_seen, last_seen) VALUES (?, ?, ?, 1, ?, ?)",
                            (user_id, cleaned_word, 'pronunciation_attempt', now_ts, now_ts)
                        )
                    conn_pr.commit()
                    conn_pr.close()
            except Exception:
                pass

            # 记录音素级别的total_attempts（正确+错误）
            try:
                learning = get_learning_algorithm()
                import sqlite3 as _sql3
                now_ts = time.time()
                conn_ph = _sql3.connect(learning.db_path)
                error_phonemes_set = set()
                for err in (response.get("errors") or []):
                    ep = err.get("expected", "")
                    if ep:
                        error_phonemes_set.add(ep)
                for ep in expected_phonemes:
                    is_err = ep in error_phonemes_set
                    row = conn_ph.execute(
                        "SELECT total_attempts, error_count FROM user_phoneme_stats WHERE user_id = ? AND phoneme = ?",
                        (user_id, ep)
                    ).fetchone()
                    if row:
                        total, err_count = row
                        new_total = total + 1
                        new_err = err_count + (1 if is_err else 0)
                        new_rate = new_err / new_total if new_total > 0 else 0
                        conn_ph.execute(
                            "UPDATE user_phoneme_stats SET total_attempts=?, error_count=?, error_rate=?, last_attempted=? WHERE user_id=? AND phoneme=?",
                            (new_total, new_err, new_rate, now_ts, user_id, ep)
                        )
                    else:
                        conn_ph.execute(
                            "INSERT INTO user_phoneme_stats (user_id, phoneme, total_attempts, error_count, error_rate, last_attempted) VALUES (?, ?, ?, ?, ?, ?)",
                            (user_id, ep, 1, 1 if is_err else 0, 1.0 if is_err else 0.0, now_ts)
                        )
                conn_ph.commit()
                conn_ph.close()
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
    """
    word = data.get("word", "").lower().strip()
    user_input = data.get("user_input", "").lower().strip()
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

    # 记录听写错误（仅真正错误时记录，near_correct不算错误）
    if not correct:
        learning = get_learning_algorithm()
        try:
            learning.record_dictation_errors(user_id, [word])
        except Exception:
            pass

    # Record dictation attempt (both correct and incorrect) for accurate rate
    # 使用 _clean_word 清理单词，确保与错误记录使用相同的 key
    try:
        from learning_algorithm import _clean_word
        cleaned_w = _clean_word(word)
        if cleaned_w:  # 跳过功能词/缩写
            import sqlite3 as _sql3_conn
            learning = get_learning_algorithm()
            now = time.time()
            conn2 = _sql3_conn.connect(learning.db_path)
            attempt_row = conn2.execute(
                "SELECT count FROM user_word_errors WHERE user_id = ? AND word = ? AND error_type = ?",
                (user_id, cleaned_w, 'dictation_attempt')
            ).fetchone()
            if attempt_row:
                conn2.execute(
                    "UPDATE user_word_errors SET count = count + 1, last_seen = ? WHERE user_id = ? AND word = ? AND error_type = ?",
                    (now, user_id, cleaned_w, 'dictation_attempt')
                )
            else:
                conn2.execute(
                    "INSERT INTO user_word_errors (user_id, word, error_type, count, first_seen, last_seen) VALUES (?, ?, ?, 1, ?, ?)",
                    (user_id, cleaned_w, 'dictation_attempt', now, now)
                )
            conn2.commit()
            conn2.close()
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

def _normalize_word(w: str) -> str:
    """Normalize word for comparison: lowercase, strip punctuation."""
    import re
    return re.sub(r"[^a-zA-Z'-]", "", w).lower()


def _levenshtein_align(expected_words: list, user_words: list) -> list:
    """Word-level Levenshtein alignment. Returns list of (expected, actual, type) tuples.

    type is one of: match, substitution, deletion, insertion
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
            # Compare normalized forms (case-insensitive, punctuation ignored)
            cost = 0 if _normalize_word(expected_words[i - 1]) == _normalize_word(user_words[j - 1]) else 1
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
            norm_exp = _normalize_word(expected_words[i - 1])
            norm_usr = _normalize_word(user_words[j - 1])
            if norm_exp == norm_usr:
                alignment.append((expected_words[i - 1], user_words[j - 1], "match"))
            else:
                alignment.append((expected_words[i - 1], user_words[j - 1], "substitution"))
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


def _check_order_errors(alignment: list) -> list:
    """After Levenshtein alignment, check matched words for relative order errors.

    A matched word whose user_index is not strictly increasing (relative to
    previous matched words) is an order_error. This prevents users from
    randomly arranging words and still getting credit.

    Returns a list of indices in alignment that should be changed to order_error.
    Deletions/insertions are skipped - only substitutions and matches are checked.
    The first occurrence of a word is kept as match, subsequent out-of-order
    occurrences are flagged.

    Strategy: Track user_index of matched words. If a matched word's user_index
    is not > last_matched_user_index, it's an order_error (spelling correct but
    position wrong relative to other matched words).
    """
    order_error_indices = []
    last_user_idx = -1

    for idx, (ew, uw, atype) in enumerate(alignment):
        if atype == "match" and uw:
            # This word was matched - check if its position is in order
            # We need the actual user word index. Since alignment merges
            # deletions/insertions, we track a running user position counter.
            pass  # Will do in a second pass with user position tracking

    # Second pass: track user position
    user_pos = 0
    last_matched_user_pos = -1
    for idx, (ew, uw, atype) in enumerate(alignment):
        if atype == "deletion":
            # No user word consumed
            continue
        elif atype == "insertion":
            user_pos += 1
            continue
        elif atype == "match":
            # Check order: user position must be strictly after last matched
            if last_matched_user_pos >= 0 and user_pos <= last_matched_user_pos:
                order_error_indices.append(idx)
            last_matched_user_pos = user_pos
            user_pos += 1
        elif atype == "substitution":
            user_pos += 1

    return order_error_indices


@app.post("/api/dictation/check")
async def dictation_check(data: dict):
    """Enhanced dictation check with:
    - Case-insensitive, punctuation-ignored comparison
    - Order error detection (correct spelling but wrong relative position)
    - Middle-empty input fix (empty inputs preserved for positional alignment)
    - Detailed error summary: spelling X | missed Y | extra Z | order W

    Error types:
    - match: spelling correct + order correct (+1 point)
    - order_error: spelling correct but wrong relative order (0 points, purple underline)
    - substitution: wrong spelling (0 points)
    - deletion: missed word (0 points)
    - insertion: extra word (0 points)
    - near_correct: minor spelling error, counted as correct
    - partial: partially correct spelling, half credit
    """
    expected_raw = data.get("text", data.get("sentence_text", ""))
    user_input_raw = data.get("user_input", "")

    # Preserve empty positions from the input list
    # If user_input is a list, keep empty strings for position tracking
    if isinstance(user_input_raw, list):
        # Each element corresponds to a position; empty string = not written
        user_words_raw = [str(w).strip() for w in user_input_raw]
    else:
        user_input_str = str(user_input_raw).strip()
        user_words_raw = user_input_str.split() if user_input_str else []

    # Normalize for comparison (lowercase, strip punctuation)
    expected_words = [_normalize_word(w) for w in expected_raw.split()]
    # For user input: preserve raw form for display, normalize for comparison
    # If list input, normalize each; empty stays empty
    user_words_norm = [_normalize_word(w) if w else "" for w in user_words_raw]

    # Filter out empty user words for Levenshtein alignment
    # But we need to map back to positions for the middle-empty bug fix
    # Strategy: align only non-empty user words, then map results back to input positions

    non_empty_user = [(i, w) for i, w in enumerate(user_words_norm) if w]
    non_empty_indices = [i for i, w in non_empty_user]
    non_empty_words = [w for i, w in non_empty_user]

    alignment = _levenshtein_align(expected_words, non_empty_words)

    # Check for order errors in the alignment
    order_error_indices = _check_order_errors(alignment)

    results = []
    PARTIAL_THRESHOLD = 0.6
    NEAR_CORRECT_THRESHOLD = 0.8

    # Build a mapping from alignment results to user input positions
    # Track which user positions have been consumed
    user_pos_consumed = 0  # Position in non_empty_words

    for align_idx, (ew, uw, align_type) in enumerate(alignment):
        if align_type == "match":
            user_input_idx = non_empty_indices[user_pos_consumed] if user_pos_consumed < len(non_empty_indices) else None
            if align_idx in order_error_indices:
                # Spelling correct but wrong relative order
                results.append({
                    "expected": ew, "actual": uw, "correct": False,
                    "type": "order_error", "user_index": user_input_idx,
                })
            else:
                results.append({
                    "expected": ew, "actual": uw, "correct": True,
                    "type": "match", "user_index": user_input_idx,
                })
            user_pos_consumed += 1

        elif align_type == "substitution":
            user_input_idx = non_empty_indices[user_pos_consumed] if user_pos_consumed < len(non_empty_indices) else None
            # Normalize both for similarity comparison
            sim = _char_similarity(_normalize_word(ew), _normalize_word(uw))
            dist = _char_levenshtein(_normalize_word(ew), _normalize_word(uw))
            is_short_near = len(_normalize_word(ew)) <= 4 and dist <= 1

            if sim >= NEAR_CORRECT_THRESHOLD or is_short_near:
                # Check order for near_correct too
                if align_idx in order_error_indices:
                    results.append({
                        "expected": ew, "actual": uw, "correct": False,
                        "type": "order_error", "similarity": round(sim, 2),
                        "edit_distance": dist, "user_index": user_input_idx,
                    })
                else:
                    results.append({
                        "expected": ew, "actual": uw, "correct": True,
                        "type": "near_correct", "similarity": round(sim, 2),
                        "edit_distance": dist, "user_index": user_input_idx,
                    })
            elif sim >= PARTIAL_THRESHOLD:
                results.append({
                    "expected": ew, "actual": uw, "correct": False,
                    "type": "partial", "similarity": round(sim, 2),
                    "edit_distance": dist, "user_index": user_input_idx,
                })
            else:
                results.append({
                    "expected": ew, "actual": uw, "correct": False,
                    "type": "substitution", "user_index": user_input_idx,
                })
            user_pos_consumed += 1

        elif align_type == "deletion":
            results.append({
                "expected": ew, "actual": "", "correct": False,
                "type": "deletion", "user_index": None,
            })

        elif align_type == "insertion":
            user_input_idx = non_empty_indices[user_pos_consumed] if user_pos_consumed < len(non_empty_indices) else None
            results.append({
                "expected": "", "actual": uw, "correct": False,
                "type": "insertion", "user_index": user_input_idx,
            })
            user_pos_consumed += 1

    # Now handle middle-empty positions:
    # Empty user inputs that weren't consumed by alignment are deletions
    consumed_user_indices = set()
    for r in results:
        if r.get("user_index") is not None:
            consumed_user_indices.add(r["user_index"])

    # Any user input position that is empty AND wasn't consumed = skipped position
    # These empty positions should be mapped to expected words via positional alignment
    # For simplicity: if user left a gap, the corresponding expected word at that
    # position is a deletion (not counted as correct)
    # We handle this by checking if total expected > total matched from alignment
    # The alignment already handles this correctly via Levenshtein deletion

    # Scoring: match +1, near_correct +1, partial +0.5, others 0
    match_count = sum(1 for r in results if r["type"] == "match")
    near_correct_count = sum(1 for r in results if r["type"] == "near_correct")
    order_error_count = sum(1 for r in results if r["type"] == "order_error")
    substitution_count = sum(1 for r in results if r["type"] == "substitution")
    deletion_count = sum(1 for r in results if r["type"] == "deletion")
    insertion_count = sum(1 for r in results if r["type"] == "insertion")
    partial_count = sum(1 for r in results if r["type"] == "partial")

    correct_count = match_count + near_correct_count
    effective_correct = correct_count + partial_count * 0.5
    accuracy = effective_correct / max(len(expected_words), 1) * 100

    # Error words for recording
    error_words = []
    for r in results:
        if not r["correct"] and r.get("expected"):
            error_words.append({
                "word": r["expected"],
                "user_input": r.get("actual", ""),
                "type": r.get("type", "substitution"),
                "similarity": r.get("similarity", 0),
                "edit_distance": r.get("edit_distance", 0),
            })
        elif r.get("type") == "near_correct" and r.get("expected"):
            error_words.append({
                "word": r["expected"],
                "user_input": r.get("actual", ""),
                "type": "near_correct",
                "similarity": r.get("similarity", 0),
                "edit_distance": r.get("edit_distance", 0),
            })

    # Summary stats
    summary = {
        "spelling_errors": substitution_count,
        "missed": deletion_count,
        "extra": insertion_count,
        "order_errors": order_error_count,
        "partial": partial_count,
        "near_correct": near_correct_count,
        "match": match_count,
    }

    return {
        "results": results,
        "accuracy": round(accuracy, 1),
        "expected": " ".join(expected_words),
        "user_input": " ".join(user_words_raw),
        "error_words": error_words,
        "summary": summary,
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

            # 应用用户自定义评分权重
            user_settings = user.get("settings", {})
            custom_weights = user_settings.get("scoring_weights", None)
            if custom_weights:
                pw = float(custom_weights.get("pronunciation", 0.55))
                cw = float(custom_weights.get("completeness", 0.25))
                fw = float(custom_weights.get("fluency", 0.20))
                total_w = pw + cw + fw
                if total_w > 0:
                    pw, cw, fw = pw/total_w, cw/total_w, fw/total_w
                eval_result.overall_score = round(min(100.0, max(0.0,
                    eval_result.pronunciation_score * pw +
                    eval_result.completeness_score * cw +
                    eval_result.fluency_score * fw)), 1)

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
    过滤功能词、缩写、标点等，只注册有学习价值的实词。
    """
    try:
        from learning_algorithm import _clean_word
        fsrs = get_fsrs_db()
        words = sentence_text.lower().split()
        for w in words:
            # 使用统一的清理函数过滤功能词、缩写、标点
            w_clean = _clean_word(w)
            if w_clean:
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


# ============================================================
# 元认知 (Metacognition) API
# ============================================================

@app.get("/api/metacognition/profile")
async def metacognition_profile(user: dict = Depends(get_current_user)):
    """获取用户的认知画像（学习原型、各项指标）"""
    user_id = user.get("id", "default")
    try:
        meta = get_metacognition()
        profile = meta.get_cognitive_profile(user_id)
        # 添加图标和名称
        from metacognition import ARCHETYPE_ICONS
        profile["archetype_name"] = profile.get("archetype", "学习者")
        profile["archetype_icon"] = ARCHETYPE_ICONS.get(profile.get("archetype", ""), "🧠")
        return profile
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取认知画像失败: {str(e)}")


@app.get("/api/metacognition/strategies")
async def metacognition_strategies(user: dict = Depends(get_current_user)):
    """获取策略推荐（基于用户认知画像）"""
    user_id = user.get("id", "default")
    try:
        meta = get_metacognition()
        strategies = meta.get_strategy_recommendations(user_id)
        return strategies
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取策略推荐失败: {str(e)}")


@app.post("/api/metacognition/prediction")
async def metacognition_prediction(data: dict, user: dict = Depends(get_current_user)):
    """记录预测校准条目（练习前后对比预测分数与实际分数）"""
    user_id = user.get("id", "default")
    card_id = data.get("card_id")
    card_type = data.get("card_type", "word")
    predicted_score = data.get("predicted_score")
    actual_score = data.get("actual_score")

    if card_id is None or predicted_score is None or actual_score is None:
        raise HTTPException(status_code=400, detail="缺少 card_id, predicted_score 或 actual_score")

    try:
        meta = get_metacognition()
        result = meta.record_prediction(
            user_id=user_id,
            card_id=card_id,
            card_type=card_type,
            predicted_score=float(predicted_score),
            actual_score=float(actual_score),
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"记录预测校准失败: {str(e)}")


@app.get("/api/metacognition/calibration")
async def metacognition_calibration(user: dict = Depends(get_current_user)):
    """获取预测校准统计"""
    user_id = user.get("id", "default")
    try:
        meta = get_metacognition()
        stats = meta.get_calibration_stats(user_id)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取校准统计失败: {str(e)}")


@app.post("/api/metacognition/session")
async def metacognition_session(data: dict, user: dict = Depends(get_current_user)):
    """记录学习会话"""
    user_id = user.get("id", "default")
    try:
        meta = get_metacognition()
        result = meta.record_session(user_id=user_id, session_data=data)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"记录学习会话失败: {str(e)}")


@app.get("/api/metacognition/session-quality")
async def metacognition_session_quality(user: dict = Depends(get_current_user)):
    """获取会话质量指标"""
    user_id = user.get("id", "default")
    try:
        meta = get_metacognition()
        quality = meta.get_session_quality(user_id)
        return quality
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取会话质量失败: {str(e)}")


@app.get("/api/achievements")
async def get_achievements(user: dict = Depends(get_current_user)):
    """获取用户成就列表和进度"""
    user_id = user.get("id", "default")
    try:
        from metacognition import check_achievements
        return check_achievements(user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取成就失败: {str(e)}")


# ============================================================
# 学习连续天数 / 每日目标 / 预报 / 收藏 / 导出 API
# ============================================================

@app.get("/api/streak")
async def get_streak(user: dict = Depends(get_current_user)):
    """获取学习连续天数"""
    user_id = user.get("id", "default")
    fsrs = get_fsrs_db()
    return fsrs.get_streak(user_id)


@app.get("/api/daily-goal")
async def get_daily_goal(
    date: Optional[str] = Query(None, description="日期 YYYY-MM-DD"),
    user: dict = Depends(get_current_user),
):
    """获取每日目标进度"""
    user_id = user.get("id", "default")
    fsrs = get_fsrs_db()
    return fsrs.get_daily_goal(user_id, date)


@app.put("/api/daily-goal")
async def update_daily_goal(data: dict, user: dict = Depends(get_current_user)):
    """设置每日目标（target_reviews, target_new, target_minutes）"""
    user_id = user.get("id", "default")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    target_reviews = data.get("target_reviews", 20)
    target_new = data.get("target_new", 5)
    target_minutes = data.get("target_minutes", 15)

    import sqlite3 as _sql3_goal
    fsrs = get_fsrs_db()
    conn = _sql3_goal.connect(fsrs.db_path)

    # Check if row exists
    row = conn.execute(
        "SELECT completed_reviews, completed_new, actual_minutes FROM daily_goals WHERE user_id=? AND date=?",
        (user_id, today)
    ).fetchone()

    if row:
        conn.execute(
            "UPDATE daily_goals SET target_reviews=?, target_new=?, target_minutes=? WHERE user_id=? AND date=?",
            (target_reviews, target_new, target_minutes, user_id, today)
        )
    else:
        conn.execute(
            "INSERT INTO daily_goals (user_id, date, target_reviews, completed_reviews, target_new, completed_new, target_minutes, actual_minutes) "
            "VALUES (?, ?, ?, 0, ?, 0, ?, 0)",
            (user_id, today, target_reviews, target_new, target_minutes)
        )

    conn.commit()
    conn.close()
    return fsrs.get_daily_goal(user_id, today)


@app.get("/api/forecast")
async def get_forecast(
    days: int = Query(30, description="预报天数"),
    user: dict = Depends(get_current_user),
):
    """获取复习预报（未来N天每天的到期复习数量）"""
    user_id = user.get("id", "default")
    fsrs = get_fsrs_db()
    return {"forecast": fsrs.get_forecast(user_id, days)}


@app.post("/api/words/bookmark")
async def bookmark_word(data: dict, user: dict = Depends(get_current_user)):
    """收藏单词到生词本"""
    user_id = user.get("id", "default")
    word = data.get("word", "").lower().strip()
    notes = data.get("notes", "")
    if not word:
        raise HTTPException(status_code=400, detail="缺少 word")
    fsrs = get_fsrs_db()
    return fsrs.bookmark_word(user_id, word, notes)


@app.delete("/api/words/bookmark")
async def unbookmark_word(data: dict, user: dict = Depends(get_current_user)):
    """从生词本移除单词"""
    user_id = user.get("id", "default")
    word = data.get("word", "").lower().strip()
    if not word:
        raise HTTPException(status_code=400, detail="缺少 word")
    fsrs = get_fsrs_db()
    return fsrs.unbookmark_word(user_id, word)


@app.get("/api/words/bookmarks")
async def get_bookmarked_words(user: dict = Depends(get_current_user)):
    """获取生词本列表"""
    user_id = user.get("id", "default")
    fsrs = get_fsrs_db()
    return {"words": fsrs.get_bookmarked_words(user_id)}


@app.get("/api/words/is-bookmarked")
async def is_word_bookmarked(
    word: str = Query(..., description="单词"),
    user: dict = Depends(get_current_user),
):
    """检查单词是否已收藏"""
    user_id = user.get("id", "default")
    fsrs = get_fsrs_db()
    return {"word": word, "bookmarked": fsrs.is_word_bookmarked(user_id, word.lower().strip())}


@app.get("/api/export")
async def export_user_data(user: dict = Depends(get_current_user)):
    """导出用户所有学习数据"""
    user_id = user.get("id", "default")
    fsrs = get_fsrs_db()
    return fsrs.export_user_data(user_id)


@app.post("/api/import")
async def import_user_data(data: dict, user: dict = Depends(get_current_user)):
    """导入用户学习数据"""
    user_id = user.get("id", "default")
    fsrs = get_fsrs_db()
    return fsrs.import_user_data(user_id, data)


@app.get("/api/learning/insights")
async def get_learning_insights(user: dict = Depends(get_current_user)):
    """获取针对性学习建议和洞察"""
    user_id = user.get("id", "default")
    try:
        meta = get_metacognition()
        insights = meta.get_learning_insights(user_id)
        return insights
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取学习建议失败: {str(e)}")


# ============================================================
# 语义网络 (Semantic Network) API
# ============================================================

@app.get("/api/semantic/network/{word}")
async def semantic_network_word(word: str, depth: int = Query(1, description="关系网络深度")):
    """获取单词的语义网络"""
    try:
        sn = get_semantic_network()
        network = sn.get_word_network(word, depth=depth)
        return network
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取语义网络失败: {str(e)}")


@app.get("/api/semantic/collocations/{word}")
async def semantic_collocations(word: str, min_strength: float = Query(0.1, description="最小搭配强度")):
    """获取单词的搭配词"""
    try:
        sn = get_semantic_network()
        collocations = sn.get_collocations(word, min_strength=min_strength)
        return {"word": word, "collocations": [{"word": c[0], "strength": round(c[1], 4)} for c in collocations]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取搭配词失败: {str(e)}")


@app.get("/api/semantic/related/{word}")
async def semantic_related(
    word: str,
    relation_type: Optional[str] = Query(None, description="关系类型: COOCCURRENCE, SEMANTIC_SIMILARITY, SYNTAGMATIC, PARADIGMATIC"),
    limit: int = Query(10, description="返回数量限制"),
):
    """获取相关词汇"""
    try:
        sn = get_semantic_network()
        related = sn.get_related_words(word, relation_type=relation_type, limit=limit)
        return {"word": word, "related": related}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取相关词失败: {str(e)}")


@app.get("/api/semantic/optimal-path")
async def semantic_optimal_path(
    target_words: Optional[str] = Query(None, description="目标词汇（逗号分隔）"),
    user: dict = Depends(get_current_user),
):
    """获取认知最优学习路径"""
    user_id = user.get("id", "default")
    try:
        sn = get_semantic_network()
        targets = None
        if target_words:
            targets = [w.strip() for w in target_words.split(",") if w.strip()]
        path = sn.get_optimal_path(user_id, target_words=targets)
        return {"path": path, "target_words": targets}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取最优路径失败: {str(e)}")


@app.get("/api/semantic/explore-next")
async def semantic_explore_next(
    card_type: str = Query("word", description="卡片类型"),
    user: dict = Depends(get_current_user),
):
    """获取下一张卡片（探索-利用平衡）"""
    user_id = user.get("id", "default")
    try:
        sn = get_semantic_network()
        result = sn.get_next_card_explore_exploit(user_id, card_type=card_type)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取探索卡片失败: {str(e)}")


@app.get("/api/semantic/field-coverage")
async def semantic_field_coverage(user: dict = Depends(get_current_user)):
    """获取语义场覆盖度统计"""
    user_id = user.get("id", "default")
    try:
        sn = get_semantic_network()
        coverage = sn.get_field_coverage(user_id)
        return {"coverage": coverage}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取语义场覆盖度失败: {str(e)}")


@app.get("/api/semantic/unexplored-fields")
async def semantic_unexplored_fields(user: dict = Depends(get_current_user)):
    """获取未探索的语义场"""
    user_id = user.get("id", "default")
    try:
        sn = get_semantic_network()
        fields = sn.get_unexplored_fields(user_id)
        return {"unexplored_fields": fields}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取未探索语义场失败: {str(e)}")


@app.post("/api/semantic/rebuild")
async def semantic_rebuild():
    """重建语义网络（从数据文件重新构建）"""
    try:
        sn = get_semantic_network()
        sn.build_network()
        stats = sn.get_network_stats()
        return {"ok": True, "message": "语义网络重建完成", "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重建语义网络失败: {str(e)}")


# ============================================================
# 设置 (Settings) API
# ============================================================

@app.get("/api/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    """获取用户当前设置（FSRS参数、期望保持率、探索率等）"""
    user_id = user.get("id", "default")
    try:
        fsrs = get_fsrs_db()
        params = fsrs.get_user_params(user_id)

        # 从用户 profile 获取扩展设置（get_current_user 已包含 settings 字段）
        user_settings = user.get("settings", {})

        # 合并 FSRS 参数和用户扩展设置
        result = {
            "desired_retention": params.get("desired_retention", 0.9),
            "new_per_day": params.get("new_per_day", 5),
            "maximum_interval": params.get("maximum_interval", 36500),
            "learning_steps": params.get("learning_steps", [1, 10]),
            "relearning_steps": params.get("relearning_steps", [10]),
            "fsrs_params": params.get("params", []),
            "fit_count": params.get("fit_count", 0),
            "last_fit_time": params.get("last_fit_time", 0),
            # 扩展设置（来自用户 profile settings）
            "exploration_rate": user_settings.get("exploration_rate", 0.3),
            "enable_prediction_calibration": user_settings.get("enable_prediction_calibration", True),
            "scoring_weights": user_settings.get("scoring_weights", {"pronunciation": 0.55, "completeness": 0.25, "fluency": 0.20}),
            "translation_priority": user_settings.get("translation_priority", "auto"),
            "tts_priority": user_settings.get("tts_priority", "browser"),
            "show_translation_first": user_settings.get("show_translation_first", False),
            "prefer_server_tts": user_settings.get("prefer_server_tts", False),
            "fsrs_fit_interval": user_settings.get("fsrs_fit_interval", 30),
            "translation_display": user_settings.get("translation_display", "after"),
        }
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取设置失败: {str(e)}")


@app.put("/api/settings")
async def update_settings(data: dict, user: dict = Depends(get_current_user)):
    """更新用户设置"""
    user_id = user.get("id", "default")
    try:
        fsrs = get_fsrs_db()

        # FSRS 相关参数
        fsrs_params = {}
        if "desired_retention" in data:
            fsrs_params["desired_retention"] = float(data["desired_retention"])
        if "new_per_day" in data:
            fsrs_params["new_per_day"] = int(data["new_per_day"])
        if "maximum_interval" in data:
            fsrs_params["maximum_interval"] = int(data["maximum_interval"])
        if "learning_steps" in data:
            fsrs_params["learning_steps"] = data["learning_steps"]
        if "relearning_steps" in data:
            fsrs_params["relearning_steps"] = data["relearning_steps"]
        if "fsrs_params" in data:
            fsrs_params["params"] = data["fsrs_params"]

        if fsrs_params:
            fsrs.set_user_params(user_id, fsrs_params)

        # 扩展设置（存入用户 profile settings）
        current_settings = dict(user.get("settings", {}))
        extended_keys = [
            "exploration_rate", "enable_prediction_calibration",
            "scoring_weights", "translation_priority", "tts_priority",
            "fsrs_fit_interval", "show_translation_first", "prefer_server_tts",
            "translation_display",
        ]
        updated = False
        for key in extended_keys:
            if key in data:
                current_settings[key] = data[key]
                updated = True

        if updated:
            try:
                auth = get_auth_service()
                auth.update_profile(user_id=user_id, settings=current_settings)
            except Exception as e:
                print(f"[设置] 更新扩展设置失败: {e}")

        return {"ok": True, "message": "设置已更新"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新设置失败: {str(e)}")


@app.get("/api/settings/defaults")
async def get_settings_defaults():
    """获取默认设置"""
    from fsrs_db import (
        DEFAULT_FSRS_PARAMS, DEFAULT_DESIRED_RETENTION,
        DEFAULT_LEARNING_STEPS, DEFAULT_RELEARNING_STEPS,
        DEFAULT_MAXIMUM_INTERVAL, DEFAULT_NEW_PER_DAY,
    )
    return {
        "desired_retention": DEFAULT_DESIRED_RETENTION,
        "new_per_day": DEFAULT_NEW_PER_DAY,
        "maximum_interval": DEFAULT_MAXIMUM_INTERVAL,
        "learning_steps": list(DEFAULT_LEARNING_STEPS),
        "relearning_steps": list(DEFAULT_RELEARNING_STEPS),
        "fsrs_params": list(DEFAULT_FSRS_PARAMS),
        "exploration_rate": 0.3,
        "enable_prediction_calibration": True,
    }


@app.post("/api/settings/reset")
async def reset_settings(user: dict = Depends(get_current_user)):
    """重置为默认设置"""
    user_id = user.get("id", "default")
    try:
        fsrs = get_fsrs_db()
        from fsrs_db import (
            DEFAULT_FSRS_PARAMS, DEFAULT_DESIRED_RETENTION,
            DEFAULT_LEARNING_STEPS, DEFAULT_RELEARNING_STEPS,
            DEFAULT_MAXIMUM_INTERVAL, DEFAULT_NEW_PER_DAY,
        )
        fsrs.set_user_params(user_id, {
            "params": list(DEFAULT_FSRS_PARAMS),
            "desired_retention": DEFAULT_DESIRED_RETENTION,
            "learning_steps": list(DEFAULT_LEARNING_STEPS),
            "relearning_steps": list(DEFAULT_RELEARNING_STEPS),
            "maximum_interval": DEFAULT_MAXIMUM_INTERVAL,
            "new_per_day": DEFAULT_NEW_PER_DAY,
        })

        # 重置扩展设置
        auth = get_auth_service()
        try:
            auth.update_profile(user_id=user_id, settings={
                "exploration_rate": 0.3,
                "enable_prediction_calibration": True,
            })
        except Exception:
            pass

        return {"ok": True, "message": "设置已重置为默认值"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重置设置失败: {str(e)}")


@app.post("/api/settings/fsrs-fit")
async def settings_fsrs_fit(user: dict = Depends(get_current_user)):
    """手动触发 FSRS 参数拟合"""
    user_id = user.get("id", "default")
    try:
        fsrs = get_fsrs_db()
        result = fsrs.fit_params(user_id=user_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"FSRS 参数拟合失败: {str(e)}")


@app.get("/api/settings/fsrs-params")
async def settings_fsrs_params(user: dict = Depends(get_current_user)):
    """获取当前 FSRS 参数（默认 + 用户自定义）"""
    user_id = user.get("id", "default")
    try:
        fsrs = get_fsrs_db()
        user_params = fsrs.get_user_params(user_id)

        from fsrs_db import DEFAULT_FSRS_PARAMS
        return {
            "default_params": list(DEFAULT_FSRS_PARAMS),
            "user_params": user_params.get("params", list(DEFAULT_FSRS_PARAMS)),
            "is_customized": user_params.get("params", []) != list(DEFAULT_FSRS_PARAMS),
            "fit_count": user_params.get("fit_count", 0),
            "last_fit_time": user_params.get("last_fit_time", 0),
            "desired_retention": user_params.get("desired_retention", 0.9),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取 FSRS 参数失败: {str(e)}")


# ============================================================
# 增强统计 (Enhanced Stats) API
# ============================================================

@app.get("/api/stats/enhanced")
async def get_enhanced_stats(user: dict = Depends(get_current_user)):
    """增强统计：认知画像 + 语义场覆盖 + 探索利用比 + 校准分数 + 会话质量趋势"""
    user_id = user.get("id", "default")

    result = {
        "cognitive_profile": {},
        "field_coverage": [],
        "exploration_exploitation": {},
        "calibration_score": {},
        "session_quality": {},
    }

    # 1. 认知画像
    try:
        meta = get_metacognition()
        profile = meta.get_cognitive_profile(user_id)
        result["cognitive_profile"] = {
            "archetype": profile.get("archetype", "未知"),
            "metrics": profile.get("metrics", {}),
        }
    except Exception as e:
        result["cognitive_profile"] = {"error": str(e)}

    # 2. 语义场覆盖
    try:
        sn = get_semantic_network()
        coverage = sn.get_field_coverage(user_id)
        result["field_coverage"] = coverage
    except Exception as e:
        result["field_coverage"] = [{"error": str(e)}]

    # 3. 探索-利用比
    try:
        sn = get_semantic_network()
        explore_stats = sn.get_exploration_stats(user_id)
        result["exploration_exploitation"] = explore_stats
    except Exception as e:
        result["exploration_exploitation"] = {"error": str(e)}

    # 4. 校准分数
    try:
        meta = get_metacognition()
        calibration = meta.get_calibration_stats(user_id)
        result["calibration_score"] = calibration
    except Exception as e:
        result["calibration_score"] = {"error": str(e)}

    # 5. 会话质量趋势
    try:
        meta = get_metacognition()
        quality = meta.get_session_quality(user_id)
        result["session_quality"] = quality
    except Exception as e:
        result["session_quality"] = {"error": str(e)}

    return result


@app.get("/api/stats/heatmap")
async def get_practice_heatmap(user: dict = Depends(get_current_user)):
    """获取练习热力图数据（过去365天每日练习次数和平均分）"""
    user_id = user.get("id", "default")
    learning = get_learning_algorithm()
    
    try:
        import sqlite3
        conn = sqlite3.connect(learning.db_path)
        # Get daily practice counts for the last 365 days
        # evaluated_at is Unix timestamp, must use 'unixepoch' modifier
        now_ts = time.time()
        year_ago_ts = now_ts - 365 * 86400
        rows = conn.execute("""
            SELECT DATE(evaluated_at, 'unixepoch', 'localtime') as date, 
                   COUNT(*) as count, 
                   AVG(overall_score) as avg_score
            FROM user_evaluations 
            WHERE user_id = ? AND evaluated_at >= ?
            GROUP BY DATE(evaluated_at, 'unixepoch', 'localtime')
            ORDER BY date
        """, (user_id, year_ago_ts)).fetchall()
        conn.close()
        
        heatmap = {}
        for r in rows:
            heatmap[r[0]] = {"count": r[1], "avg_score": round(r[2], 1) if r[2] else 0}
        
        return {"heatmap": heatmap}
    except Exception as e:
        return {"heatmap": {}}


@app.get("/api/stats/history")
async def get_practice_history(
    limit: int = Query(20, description="返回记录数量"),
    user: dict = Depends(get_current_user)
):
    """获取练习历史记录"""
    user_id = user.get("id", "default")
    learning = get_learning_algorithm()
    
    try:
        import sqlite3
        conn = sqlite3.connect(learning.db_path)
        rows = conn.execute("""
            SELECT sentence_id, overall_score, pronunciation_score, completeness_score, 
                   fluency_score, evaluated_at, duration
            FROM user_evaluations 
            WHERE user_id = ? 
            ORDER BY evaluated_at DESC 
            LIMIT ?
        """, (user_id, limit)).fetchall()
        conn.close()
        
        history = []
        for r in rows:
            # Convert Unix timestamp to ISO string for frontend
            eval_at = r[5]
            if eval_at and eval_at > 0:
                from datetime import datetime
                eval_at_str = datetime.fromtimestamp(eval_at).isoformat()
            else:
                eval_at_str = None
            history.append({
                "sentence_id": r[0],
                "overall_score": round(r[1], 1),
                "pronunciation_score": round(r[2], 1),
                "completeness_score": round(r[3], 1),
                "fluency_score": round(r[4], 1),
                "evaluated_at": eval_at_str,
                "duration": r[6],
            })
        
        return {"history": history}
    except Exception as e:
        return {"history": []}


@app.get("/api/sentence-state")
async def get_sentence_state(card_id: str = Query(...), user: dict = Depends(get_current_user)):
    """获取句子状态（收藏/已掌握）"""
    user_id = user.get("id", "default")
    try:
        fsrs = get_fsrs_db()
        import sqlite3
        conn = sqlite3.connect(fsrs.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS card_states (
                card_id TEXT, user_id TEXT, bookmarked INTEGER DEFAULT 0, mastered INTEGER DEFAULT 0,
                PRIMARY KEY (card_id, user_id)
            )
        """)
        row = conn.execute(
            "SELECT bookmarked, mastered FROM card_states WHERE card_id=? AND user_id=?",
            (card_id, user_id)
        ).fetchone()
        conn.close()
        if row:
            return {"bookmarked": bool(row[0]), "mastered": bool(row[1])}
        return {"bookmarked": False, "mastered": False}
    except:
        return {"bookmarked": False, "mastered": False}


@app.post("/api/sentence-state")
async def set_sentence_state(data: dict, user: dict = Depends(get_current_user)):
    """设置句子状态（收藏/已掌握）"""
    user_id = user.get("id", "default")
    card_id = data.get("card_id", "")
    bookmarked = data.get("bookmarked")
    mastered = data.get("mastered")
    
    if not card_id:
        raise HTTPException(status_code=400, detail="缺少 card_id")
    
    try:
        fsrs = get_fsrs_db()
        import sqlite3
        conn = sqlite3.connect(fsrs.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS card_states (
                card_id TEXT, user_id TEXT, bookmarked INTEGER DEFAULT 0, mastered INTEGER DEFAULT 0,
                PRIMARY KEY (card_id, user_id)
            )
        """)
        
        if bookmarked is not None:
            conn.execute("""
                INSERT OR REPLACE INTO card_states (card_id, user_id, bookmarked, mastered)
                VALUES (?, ?, ?, COALESCE((SELECT mastered FROM card_states WHERE card_id=? AND user_id=?), 0))
            """, (card_id, user_id, int(bookmarked), card_id, user_id))
        
        if mastered is not None:
            conn.execute("""
                INSERT OR REPLACE INTO card_states (card_id, user_id, bookmarked, mastered)
                VALUES (?, ?, COALESCE((SELECT bookmarked FROM card_states WHERE card_id=? AND user_id=?), 0), ?)
            """, (card_id, user_id, card_id, user_id, int(mastered)))
        
        conn.commit()
        conn.close()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sentences/bookmarked")
async def get_bookmarked_sentences(user: dict = Depends(get_current_user)):
    """获取用户收藏的句子列表"""
    user_id = user.get("id", "default")
    try:
        fsrs = get_fsrs_db()
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(fsrs.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS card_states (
                card_id TEXT, user_id TEXT, bookmarked INTEGER DEFAULT 0, mastered INTEGER DEFAULT 0,
                PRIMARY KEY (card_id, user_id)
            )
        """)
        rows = conn.execute(
            "SELECT card_id FROM card_states WHERE user_id=? AND bookmarked=1",
            (user_id,)
        ).fetchall()
        conn.close()

        sentences = []
        for (card_id,) in rows:
            sentence = _find_sentence_by_card_id(card_id)
            if sentence:
                enriched = await _enrich_sentence_async(sentence)
                enriched["card_id"] = card_id
                sentences.append(enriched)

        return {"sentences": sentences, "total": len(sentences)}
    except Exception as e:
        return {"sentences": [], "total": 0}


# 挂载前端
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
