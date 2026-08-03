"""Pytest 配置与 fixtures。"""

import os
import sys
from pathlib import Path

import pytest

# 添加 backend 到 path
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# 测试环境变量
os.environ.setdefault("ENV", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("CORS_ALLOWED_ORIGINS_STR", "http://localhost")


def pytest_collection_modifyitems(config, items):
    """自动跳过 e2e/ 目录下的测试（需手动运行）。"""
    skip_marker = pytest.mark.skip(reason="E2E/安全测试需手动运行: python backend/tests/e2e/test_playwright.py")
    for item in items:
        if "e2e" in str(item.fspath) or "security" in str(item.fspath):
            item.add_marker(skip_marker)


@pytest.fixture
def tmp_db(tmp_path):
    """临时数据库目录。"""
    return tmp_path / "test_dbs"


@pytest.fixture
def sample_audio_16k():
    """生成 1 秒 16kHz 正弦波测试音频。"""
    import numpy as np

    sr = 16000
    t = np.linspace(0, 1, sr, endpoint=False)
    audio = 0.5 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
    return audio, sr


@pytest.fixture
def sample_audio_silence():
    """生成 1 秒静音音频。"""
    import numpy as np

    sr = 16000
    return np.zeros(sr, dtype=np.float32), sr
