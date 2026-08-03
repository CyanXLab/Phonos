"""数据导出/导入 API（隐私合规必需）。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from ..core.config import get_settings
from ..core.logging import get_logger
from .deps import require_user


router = APIRouter(prefix="/api/data", tags=["data"])
logger = get_logger("data_api")


@router.get("/export")
async def export_user_data(user: dict = Depends(require_user)):
    """导出当前用户的所有数据（GDPR/隐私合规）。"""
    user_id = user["id"]
    settings = get_settings()
    data = {"user_id": user_id, "exported_at": time.time(), "modules": {}}

    # FSRS
    try:
        from fsrs_db import get_fsrs_db

        fsrs = get_fsrs_db()
        data["modules"]["fsrs"] = _export_fsrs(fsrs, user_id)
    except Exception as e:
        logger.warning("export_fsrs_failed", error=str(e))

    # Learning
    try:
        from learning_algorithm import get_learning_algorithm

        learning = get_learning_algorithm()
        data["modules"]["learning"] = _export_learning(learning, user_id)
    except Exception as e:
        logger.warning("export_learning_failed", error=str(e))

    # Metacognition
    try:
        from metacognition import get_metacognition

        meta = get_metacognition()
        data["modules"]["metacognition"] = _export_metacognition(meta, user_id)
    except Exception as e:
        logger.warning("export_metacognition_failed", error=str(e))

    return data


@router.delete("/purge")
async def purge_user_data(user: dict = Depends(require_user)):
    """删除当前用户的所有数据（不可恢复）。"""
    user_id = user["id"]
    deleted = {}

    try:
        from fsrs_db import get_fsrs_db

        fsrs = get_fsrs_db()
        for table in ["cards", "review_log", "user_fsrs_params", "study_streaks", "daily_goals", "word_bookmarks"]:
            n = fsrs._conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,)).rowcount
            deleted[f"fsrs.{table}"] = n
        fsrs._conn.commit()
    except Exception as e:
        logger.warning("purge_fsrs_failed", error=str(e))

    try:
        from learning_algorithm import get_learning_algorithm

        learning = get_learning_algorithm()
        for table in ["user_evaluations", "user_word_progress", "user_phoneme_stats", "user_word_errors"]:
            n = learning._get_conn().execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,)).rowcount
            deleted[f"learning.{table}"] = n
        learning._get_conn().commit()
    except Exception as e:
        logger.warning("purge_learning_failed", error=str(e))

    return {"deleted": deleted, "purged_at": time.time()}


@router.get("/privacy")
async def privacy_info():
    """隐私说明。"""
    settings = get_settings()
    return {
        "default_local": True,
        "upload_user_audio": settings.upload_user_audio,
        "online_services": {
            "dict": settings.allow_online_dict,
            "translate": settings.allow_online_translate,
            "tts": settings.allow_online_tts,
        },
        "commercial_apis": {
            "azure": settings.enable_azure_pronunciation,
            "xfyun": settings.enable_xfyun_ise,
            "youdao": settings.enable_youdao,
        },
        "data_storage": {
            "database": "本地 SQLite",
            "audio_files": "临时文件，评测后立即删除",
            "logs": "本地文件，不包含原始音频",
        },
        "user_rights": [
            "随时导出全部数据（/api/data/export）",
            "随时删除全部数据（/api/data/purge）",
            "查看隐私说明（/api/data/privacy）",
            "禁用所有联网功能（设置 upload_user_audio=false 等）",
        ],
    }


def _export_fsrs(fsrs, user_id: str) -> dict:
    conn = fsrs._get_conn() if hasattr(fsrs, "_get_conn") else fsrs._conn
    data = {}
    for table in ["cards", "review_log", "user_fsrs_params", "study_streaks", "daily_goals", "word_bookmarks"]:
        rows = conn.execute(f"SELECT * FROM {table} WHERE user_id = ?", (user_id,)).fetchall()
        cols = [d[0] for d in conn.execute(f"SELECT * FROM {table} WHERE user_id = ?", (user_id,)).description] if rows else []
        data[table] = [dict(zip(cols, r)) for r in rows]
    return data


def _export_learning(learning, user_id: str) -> dict:
    conn = learning._get_conn()
    data = {}
    for table in ["user_evaluations", "user_word_progress", "user_phoneme_stats", "user_word_errors"]:
        try:
            cur = conn.execute(f"SELECT * FROM {table} WHERE user_id = ?", (user_id,))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if rows else []
            data[table] = [dict(zip(cols, r)) for r in rows]
        except Exception:
            data[table] = []
    return data


def _export_metacognition(meta, user_id: str) -> dict:
    conn = meta._get_conn()
    data = {}
    for table in ["cognitive_profiles", "prediction_calibrations", "learning_sessions", "achievements"]:
        try:
            cur = conn.execute(f"SELECT * FROM {table} WHERE user_id = ?", (user_id,))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if rows else []
            data[table] = [dict(zip(cols, r)) for r in rows]
        except Exception:
            data[table] = []
    return data
