"""Phonos v3 应用工厂。

设计原则：
1. 不破坏旧代码：原 main.py 仍可独立运行
2. v3 通过 create_app() 创建应用，引入新模块
3. 旧路由仍可用（直接 import 自 main.py），新路由通过 include_router 引入
4. lifespan 替代 on_event
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.config import get_settings
from .core.logging import configure_logging, get_logger
from .core.middleware import (
    AccessLogMiddleware,
    ErrorHandlerMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)
from .api import (
    config_center,
    data,
    dictation_v2,
    evaluate_v2,
    health,
    models,
    shanghai_exam,
)
from .services.pronunciation_provider import register_default_providers


logger = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化、关闭时清理。"""
    settings = get_settings()
    configure_logging()
    logger.info("app_starting", env=settings.env, version=settings.app_version)

    # 后台加载模型（不阻塞）
    async def _background_init():
        try:
            # 注册 Provider
            register_default_providers()
            logger.info("providers_registered")

            # G2P
            from g2p_service import get_g2p_service

            g2p = get_g2p_service()
            logger.info("g2p_ready", available=g2p.available)

            # 词典
            from dict_service import get_dict_service

            get_dict_service()
            logger.info("dict_ready")

            # 音素缓存
            from phoneme_data import PRESET_SENTENCES, update_phoneme_cache
            from g2p_service import get_g2p_service

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, update_phoneme_cache, PRESET_SENTENCES, get_g2p_service()
            )

            # FSRS 卡片
            try:
                from fsrs_db import get_fsrs_db

                fsrs = get_fsrs_db()
                for sentence in PRESET_SENTENCES:
                    card_id = f"sentence_{sentence['id']}"
                    fsrs.ensure_card(card_id, card_type="sentence", user_id="default")
                logger.info("fsrs_cards_ready", count=len(PRESET_SENTENCES))
            except Exception as e:
                logger.warning("fsrs_init_failed", error=str(e))

            # 认证 + 学习
            try:
                from auth_service import get_auth_service
                from learning_algorithm import get_learning_algorithm

                get_auth_service()
                get_learning_algorithm()
                logger.info("auth_learning_ready")
            except Exception as e:
                logger.warning("auth_learning_failed", error=str(e))

            # 上海考试
            try:
                from .services.shanghai_exam_service import get_shanghai_exam_service

                exam = get_shanghai_exam_service()
                logger.info("shanghai_exam_ready", corpus=exam.corpus_count())
            except Exception as e:
                logger.warning("shanghai_exam_failed", error=str(e))

        except Exception as e:
            logger.exception("background_init_failed", error=str(e))

    task = asyncio.create_task(_background_init())

    yield

    # 关闭
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("app_stopped")


def create_app() -> FastAPI:
    """创建 Phonos v3 FastAPI 应用。"""
    settings = get_settings()
    configure_logging()

    app = FastAPI(
        title="Phonos 商业级英语听说训练系统",
        version=settings.app_version,
        description="本地优先 + 上海听说考试训练 + 多 Provider 发音诊断",
        lifespan=lifespan,
    )

    # 中间件（顺序：从外到内）
    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # CORS（从配置读取，不再用 ["*"]）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
    )

    # 注册新版路由
    app.include_router(health.router)
    app.include_router(evaluate_v2.router)
    app.include_router(dictation_v2.router)
    app.include_router(shanghai_exam.router)
    app.include_router(models.router)
    app.include_router(data.router)
    app.include_router(config_center.router)

    # 兼容：注册旧版路由（直接 import 原 main.py 的 app）
    try:
        # 把旧版所有 /api/* 路由挂到新 app
        # 方式：不替换旧 app，而是把旧 app 的路由 register 到新 app
        # 由于旧 main.py 用 @app.get 直接注册，无法直接迁移
        # 方案：保留旧 main.py 作为入口，新模块通过 import 自动注入
        # 此处不做强制挂载，由 main_v3.py 选择是否组合
        pass
    except Exception as e:
        logger.warning("legacy_routes_mount_failed", error=str(e))

    # 静态文件（仅 local/dev）
    if settings.env in ("local", "dev"):
        frontend_path = Path(__file__).resolve().parents[2] / "frontend"
        if frontend_path.is_dir():
            # 挂在 /app 路径下，避免与 API 冲突
            app.mount("/app", StaticFiles(directory=str(frontend_path), html=True), name="frontend_v3")

    return app


# 模块级 app 实例（供 uvicorn 直接引用）
# 用法：uvicorn app.main:app --reload
app = create_app()
