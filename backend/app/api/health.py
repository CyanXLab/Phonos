"""增强版健康检查 API：模型/DB/磁盘/模型缓存/商业 API 状态。"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter

from ..core.config import get_settings
from ..core.logging import get_logger


router = APIRouter(prefix="/api", tags=["health"])
logger = get_logger("health")


@router.get("/health")
async def health_check_basic():
    """轻量级健康检查（兼容旧接口）。"""
    return {"status": "ok"}


@router.get("/health/v2")
async def health_check_full():
    """完整健康检查：包含子模块状态、磁盘、模型缓存、商业 API。"""
    settings = get_settings()
    checks: dict = {}
    overall = "ok"

    # 1. 模型
    huper_path = settings.effective_huper_model_path()
    checks["huper_model"] = {
        "available": bool(huper_path),
        "path": huper_path or None,
    }
    if not huper_path:
        overall = "degraded"

    # 2. ONNX Runtime provider
    try:
        import onnxruntime as ort
        checks["onnxruntime"] = {
            "version": ort.__version__,
            "providers": ort.get_available_providers(),
        }
    except ImportError:
        checks["onnxruntime"] = {"available": False}
        overall = "degraded"

    # 3. G2P
    try:
        from g2p_service import get_g2p_service

        g2p = get_g2p_service()
        checks["g2p"] = {"available": g2p.available}
        if not g2p.available:
            overall = "degraded"
    except Exception as e:
        checks["g2p"] = {"available": False, "error": str(e)}
        overall = "degraded"

    # 4. TTS
    try:
        from tts_service import check_tts_available

        tts_status = check_tts_available()
        checks["tts"] = tts_status
        if not any(tts_status.values()):
            overall = "degraded"
    except Exception as e:
        checks["tts"] = {"error": str(e)}

    # 5. FSRS DB
    try:
        from fsrs_db import get_fsrs_db

        fsrs = get_fsrs_db()
        checks["fsrs"] = {"available": True, "db_path": fsrs.db_path}
    except Exception as e:
        checks["fsrs"] = {"available": False, "error": str(e)}
        overall = "degraded"

    # 6. 翻译
    try:
        from translate_service import get_translate_status

        checks["translate"] = get_translate_status()
    except Exception as e:
        checks["translate"] = {"error": str(e)}

    # 7. 磁盘空间
    if settings.health_check_disk:
        try:
            disk = shutil.disk_usage("/")
            free_gb = disk.free / (1024 ** 3)
            checks["disk"] = {
                "free_gb": round(free_gb, 2),
                "ok": free_gb >= settings.health_check_min_disk_gb,
            }
            if free_gb < settings.health_check_min_disk_gb:
                overall = "degraded"
        except Exception as e:
            checks["disk"] = {"error": str(e)}

    # 8. Whisper（可选）
    checks["whisper"] = {
        "enabled": settings.whisper_enabled,
        "model_size": settings.whisper_model_size,
    }

    # 9. VAD
    try:
        from ..services.vad_service import get_vad_service

        vad = get_vad_service()
        checks["vad"] = {"available": vad.available}
    except Exception as e:
        checks["vad"] = {"available": False, "error": str(e)}

    # 10. 商业 API（脱敏）
    checks["commercial_apis"] = {
        "azure": {"enabled": settings.enable_azure_pronunciation},
        "xfyun": {"enabled": settings.enable_xfyun_ise},
        "youdao": {"enabled": settings.enable_youdao},
    }

    # 11. 上海考试
    try:
        from ..services.shanghai_exam_service import get_shanghai_exam_service

        exam = get_shanghai_exam_service()
        checks["shanghai_exam"] = {
            "available": True,
            "task_types": len(exam.list_task_types()),
            "corpus_count": exam.corpus_count(),
        }
    except Exception as e:
        checks["shanghai_exam"] = {"available": False, "error": str(e)}

    return {
        "status": overall,
        "version": settings.app_version,
        "env": settings.env,
        "timestamp": time.time(),
        "checks": checks,
    }


@router.get("/readiness")
async def readiness():
    """Kubernetes readiness：模型必须加载完成。"""
    try:
        from onnx_service import get_recognizer
        from phoneme_data import PRESET_SENTENCES

        settings = get_settings()
        path = settings.effective_huper_model_path()
        if not path:
            return {"ready": False, "reason": "model_not_found"}
        get_recognizer(path)
        return {"ready": True, "sentences": len(PRESET_SENTENCES)}
    except Exception as e:
        return {"ready": False, "reason": str(e)}


@router.get("/liveness")
async def liveness():
    return {"alive": True}
