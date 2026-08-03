"""Phonos 全局配置（Pydantic Settings v2）。

特性：
- 从 .env 文件加载
- 环境变量覆盖
- 类型校验
- 默认本地优先、隐私安全
- 模型路径、provider、量化等级可配置
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# config.py 在 backend/app/core/config.py
# parents[0]=core, parents[1]=app, parents[2]=backend, parents[3]=项目根
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_DIR = _PROJECT_ROOT / "backend"


class Settings(BaseSettings):
    """Phonos 全局配置。"""

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 基础 ----------
    app_name: str = "Phonos"
    app_version: str = "3.0.0"
    env: str = Field(default="local", description="local/dev/staging/prod")
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    log_format: str = Field(default="json", description="json 或 console")

    # ---------- 安全 ----------
    # 逗号分隔的允许来源，例如 "https://app.example.com,http://localhost:5173"
    # 逗号分隔字符串，避免 pydantic-settings 对 List 的 JSON 解析问题
    cors_allowed_origins_str: str = Field(
        default="http://localhost:5173,http://localhost:8000,http://127.0.0.1:5173,http://127.0.0.1:8000",
        description="逗号分隔的允许来源列表",
    )
    cors_allow_credentials: bool = True
    secret_key: str = Field(
        default="phonos-dev-secret-change-me-in-production",
        description="用于 JWT/HMAC，生产必须替换",
    )
    bcrypt_rounds: int = 12

    # ---------- 数据库 ----------
    # 默认 SQLite WAL（单用户本地），可切 PostgreSQL（多用户/学校版）
    database_url: str = Field(
        default=f"sqlite:///{_BACKEND_DIR / 'phonos_main.db'}",
        description="SQLAlchemy 2 数据库 URL",
    )
    # 旧版独立 SQLite 路径（用于兼容老数据）
    legacy_fsrs_db: str = str(_BACKEND_DIR / "phonos_fsrs.db")
    legacy_learning_db: str = str(_BACKEND_DIR / "phonos_learning.db")
    legacy_metacognition_db: str = str(_BACKEND_DIR / "phonos_metacognition.db")
    legacy_auth_db: str = str(_BACKEND_DIR / "phonos_auth.db")
    legacy_semantic_db: str = str(_BACKEND_DIR / "phonos_semantic.db")

    # ---------- 模型路径 ----------
    models_dir: str = str(_PROJECT_ROOT / "models")
    huper_model_path: str = ""  # 留空则自动查找
    huper_provider: str = Field(
        default="auto",
        description="auto / cpu / cuda / tensorrt / directml",
    )
    huper_intra_op_threads: int = 4
    huper_inter_op_threads: int = 0  # 0 表示按 CPU 数
    huper_model_mode: str = Field(
        default="balanced",
        description="high_precision / balanced / low_latency",
    )

    # ---------- VAD（silero-vad）----------
    vad_model_path: str = ""  # 留空则使用 silero-vad 自带
    vad_threshold: float = 0.5
    vad_min_speech_duration_ms: int = 250
    vad_min_silence_duration_ms: int = 100
    vad_speech_pad_ms: int = 30

    # ---------- ASR（faster-whisper）----------
    whisper_model_path: str = ""  # 留空则使用缓存目录
    whisper_model_size: str = Field(
        default="small",
        description="tiny / base / small / medium / large-v3",
    )
    whisper_compute_type: str = Field(
        default="int8",
        description="int8 / int8_float16 / float16 / float32",
    )
    whisper_device: str = Field(default="auto", description="auto / cpu / cuda")
    whisper_cpu_threads: int = 4
    whisper_num_workers: int = 1
    whisper_enabled: bool = False  # 默认关闭，按需启用

    # ---------- 强制对齐 ----------
    forced_aligner: str = Field(
        default="ctc_segmentation",
        description="ctc_segmentation / whisperx / mfa",
    )

    # ---------- G2P ----------
    g2p_use_phonemizer: bool = False  # 需安装 espeak/festival，默认关闭
    g2p_custom_dict_path: str = str(_BACKEND_DIR / "shanghai_corpus" / "custom_dict.json")

    # ---------- 商业 API（默认关闭）----------
    enable_azure_pronunciation: bool = False
    azure_speech_key: str = ""
    azure_speech_region: str = "eastasia"

    enable_xfyun_ise: bool = False
    xfyun_app_id: str = ""
    xfyun_api_key: str = ""
    xfyun_api_secret: str = ""

    enable_youdao: bool = False
    youdao_app_key: str = ""
    youdao_app_secret: str = ""

    # ---------- 隐私 ----------
    upload_user_audio: bool = False  # 默认不上传用户音频到任何外部服务
    allow_online_dict: bool = True
    allow_online_translate: bool = True
    allow_online_tts: bool = True

    # ---------- 性能 ----------
    max_audio_duration_sec: int = 60  # 超过自动切片
    batch_inference: bool = False
    request_timeout_sec: int = 60

    # ---------- 评分 ----------
    scoring_weights_pron: float = 0.45
    scoring_weights_comp: float = 0.20
    scoring_weights_flu: float = 0.15
    scoring_weights_prosody: float = 0.10
    scoring_weights_quality: float = 0.10

    # ---------- FSRS ----------
    fsrs_desired_retention: float = 0.9
    fsrs_new_per_day: int = 5
    fsrs_fit_interval: int = 30
    fsrs_fit_min_reviews: int = 30

    # ---------- 上海考试 ----------
    shanghai_exam_strict_timing: bool = True
    shanghai_exam_auto_submit: bool = True
    shanghai_exam_record_audio_check: bool = True

    # ---------- 校准 ----------
    calibration_dataset_dir: str = str(_PROJECT_ROOT / "bench" / "calibration_set")

    # ---------- LLM 评分 ----------
    # 默认 ModelScope 云端（用户需配置 API key）
    llm_api_key: str = Field(default="", description="ModelScope API key 或 OpenAI 兼容 key")
    llm_base_url: str = Field(
        default="https://api-inference.modelscope.cn/v1",
        description="OpenAI 兼容 API base URL",
    )
    llm_model: str = Field(
        default="Qwen/Qwen3.5-122B-A10B",
        description="LLM 模型名（ModelScope Qwen / 本地 llama.cpp）",
    )
    # llama.cpp 本地可选
    llama_cpp_url: str = Field(default="http://127.0.0.1:8080/v1", description="本地 llama.cpp server URL")
    llm_enabled: bool = Field(default=True, description="是否启用 LLM 评分")

    # ---------- 健康检查 ----------
    health_check_db: bool = True
    health_check_disk: bool = True
    health_check_min_disk_gb: float = 1.0

    @field_validator("env")
    @classmethod
    def _lower_env(cls, v):
        return v.lower()

    @property
    def cors_allowed_origins(self) -> List[str]:
        """解析逗号分隔的 CORS 来源列表。"""
        return [s.strip() for s in self.cors_allowed_origins_str.split(",") if s.strip()]

    @property
    def is_production(self) -> bool:
        return self.env == "prod"

    @property
    def is_local(self) -> bool:
        return self.env == "local"

    def effective_huper_model_path(self) -> str:
        """返回实际使用的 HuPER 模型路径（含环境变量与自动查找）。"""
        env_path = os.environ.get("HUPER_MODEL_PATH", "")
        if env_path:
            # 支持相对路径（相对于项目根）
            p = Path(env_path)
            if not p.is_absolute():
                p = _PROJECT_ROOT / p
            if p.is_file():
                return str(p)
        if self.huper_model_path:
            p = Path(self.huper_model_path)
            if not p.is_absolute():
                p = _PROJECT_ROOT / p
            if p.is_file():
                return str(p)

        # 兼容旧查找路径
        candidates = [
            _PROJECT_ROOT / self.models_dir / "huper_onnx_int8_dynamic" / "model_quantized.onnx",
            _PROJECT_ROOT / self.models_dir / "model.onnx",
            _PROJECT_ROOT / self.models_dir / "model_quantized.onnx",
            _PROJECT_ROOT / self.models_dir / "huper" / "model.onnx",
            _PROJECT_ROOT / self.models_dir / "huper" / "model_quantized.onnx",
            _BACKEND_DIR / "models" / "model.onnx",
            _BACKEND_DIR / "models" / "model_quantized.onnx",
            _PROJECT_ROOT / "huper_onnx" / "model.onnx",
            _PROJECT_ROOT / "huper_onnx_int8_dynamic" / "model_quantized.onnx",
        ]
        for p in candidates:
            if p.is_file():
                return str(p)
        return ""

    def effective_whisper_model_path(self) -> str:
        env_path = os.environ.get("WHISPER_MODEL_PATH", "")
        if env_path:
            return env_path
        if self.whisper_model_path:
            return self.whisper_model_path
        return str(Path(self.models_dir) / "whisper")

    def get_provider_list(self) -> list:
        """根据配置返回 ONNX Runtime provider 列表。"""
        p = self.huper_provider.lower()
        if p == "auto":
            return [
                ("CUDAExecutionProvider", {"device_id": 0}),
                ("CPUExecutionProvider",),
            ]
        if p == "cuda":
            return [
                ("CUDAExecutionProvider", {"device_id": 0}),
                ("CPUExecutionProvider",),
            ]
        if p == "tensorrt":
            return [
                ("TensorrtExecutionProvider",),
                ("CUDAExecutionProvider", {"device_id": 0}),
                ("CPUExecutionProvider",),
            ]
        if p == "directml":
            return [
                ("DmlExecutionProvider",),
                ("CPUExecutionProvider",),
            ]
        return ["CPUExecutionProvider"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """全局单例 Settings。"""
    return Settings()


def reload_settings() -> Settings:
    """清除缓存重新加载（测试用）。"""
    get_settings.cache_clear()
    return get_settings()
