"""模型管理 API：列出可用模型、加载状态、切换模式。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..core.config import get_settings
from ..core.logging import get_logger
from .deps import require_user
from ..services.pronunciation_provider import (
    ModelMode,
    get_provider_registry,
    register_default_providers,
)


router = APIRouter(prefix="/api/models", tags=["models"])
logger = get_logger("models_api")


@router.get("/")
async def list_models(user: dict = Depends(require_user)):
    """列出所有模型与 Provider 状态。"""
    settings = get_settings()
    registry = get_provider_registry()
    if not registry.list_providers():
        register_default_providers()

    return {
        "huper": {
            "path": settings.effective_huper_model_path() or None,
            "provider": settings.huper_provider,
            "mode": settings.huper_model_mode,
            "intra_op_threads": settings.huper_intra_op_threads,
            "inter_op_threads": settings.huper_inter_op_threads,
        },
        "whisper": {
            "enabled": settings.whisper_enabled,
            "model_size": settings.whisper_model_size,
            "compute_type": settings.whisper_compute_type,
            "device": settings.whisper_device,
        },
        "vad": {
            "model_path": settings.vad_model_path or "auto",
            "threshold": settings.vad_threshold,
        },
        "forced_aligner": settings.forced_aligner,
        "providers": registry.list_providers(),
        "commercial_apis_enabled": {
            "azure": settings.enable_azure_pronunciation,
            "xfyun": settings.enable_xfyun_ise,
            "youdao": settings.enable_youdao,
        },
        "privacy": {
            "upload_user_audio": settings.upload_user_audio,
            "allow_online_dict": settings.allow_online_dict,
            "allow_online_translate": settings.allow_online_translate,
            "allow_online_tts": settings.allow_online_tts,
        },
    }


@router.get("/download-info")
async def download_info(user: dict = Depends(require_user)):
    """返回各模型的下载信息（许可证、大小、来源）。"""
    return {
        "models": [
            {
                "name": "HuPER (HuBERT Phoneme Recognizer)",
                "license": "用户自带（云盘）",
                "online": False,
                "size_mb": "约 350 (FP32) / 90 (INT8)",
                "download": "用户从云盘获取，放置到 models/model.onnx",
                "fallback": "无（核心模型）",
            },
            {
                "name": "silero-vad",
                "license": "MIT (代码) / CC BY 4.0 (模型)",
                "online": True,
                "size_mb": "约 2",
                "download": "首次使用自动从 silero CDN 下载，或预置 models/silero_vad.onnx",
                "fallback": "能量阈值法（无依赖）",
            },
            {
                "name": "faster-whisper (small/medium/large-v3)",
                "license": "MIT (代码) / MIT (模型)",
                "online": True,
                "size_mb": "75 (small) / 240 (medium) / 1500 (large-v3)",
                "download": "首次使用自动从 HuggingFace 下载到 models/whisper/",
                "fallback": "本地 HuPER 音素识别（无词级时间戳）",
            },
            {
                "name": "g2p-en",
                "license": "MIT",
                "online": True,
                "size_mb": "约 1000 (含 CMUdict)",
                "download": "首次 import 自动下载",
                "fallback": "内置 50 词回退词典 + 字母级映射",
            },
        ],
        "commercial_apis": [
            {
                "name": "Azure Pronunciation Assessment",
                "license": "商业（按调用计费）",
                "online": True,
                "requires_key": True,
                "default_enabled": False,
                "privacy": "音频上传到 Azure 云端",
            },
            {
                "name": "讯飞 ISE 口语评测",
                "license": "商业",
                "online": True,
                "requires_key": True,
                "default_enabled": False,
                "privacy": "音频上传到讯飞云端",
            },
            {
                "name": "有道智云口语评测",
                "license": "商业",
                "online": True,
                "requires_key": True,
                "default_enabled": False,
                "privacy": "音频上传到有道云端",
            },
        ],
    }
