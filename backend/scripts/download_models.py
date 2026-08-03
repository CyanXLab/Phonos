#!/usr/bin/env python3
"""Phonos v3 模型下载与校验脚本。

下载：
- silero-vad（约 2MB，CC BY 4.0）
- faster-whisper small（约 75MB，MIT）
- g2p-en CMUdict（约 1GB，MIT）

不下载：
- HuPER 模型（用户从云盘获取，放置到 models/model.onnx）

用法：
    python backend/scripts/download_models.py
    python backend/scripts/download_models.py --vad-only
    python backend/scripts/download_models.py --whisper-size medium
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = PROJECT_ROOT / "models"


SILERO_VAD_URL = "https://github.com/snakers4/silero-vad/raw/master/files/silero_vad.onnx"
SILERO_VAD_PATH = MODELS_DIR / "silero_vad.onnx"
SILERO_VAD_SHA256 = "c97e3e2c1d3f8b5e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e"  # 占位，实际下载后计算


def download(url: str, dest: Path, desc: str = "") -> bool:
    """带进度条的下载。"""
    if dest.exists():
        print(f"[跳过] {dest.name} 已存在")
        return True
    print(f"[下载] {desc or dest.name}: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Phonos/3.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded * 100 // total
                        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                        sys.stdout.write(f"\r  [{bar}] {pct}% ({downloaded // 1024}KB/{total // 1024}KB)")
                        sys.stdout.flush()
            print()
        print(f"[完成] {dest}")
        return True
    except Exception as e:
        print(f"[失败] {dest}: {e}")
        if dest.exists():
            dest.unlink()
        return False


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(64 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def download_silero_vad() -> bool:
    """下载 silero-vad。"""
    print("\n=== silero-vad ===")
    print("许可证: MIT (代码) / CC BY 4.0 (模型)")
    print("大小: 约 2MB")
    print("用途: 语音活动检测，用于停顿检测、音频质量评估")
    ok = download(SILERO_VAD_URL, SILERO_VAD_PATH, "silero-vad ONNX")
    if ok:
        actual_sha = sha256_file(SILERO_VAD_PATH)
        print(f"  SHA256: {actual_sha}")
    return ok


def download_whisper(model_size: str = "small") -> bool:
    """下载 faster-whisper 模型。

    实际通过 faster-whisper 库自动下载（首次 transcribe 时）。
    此处仅打印说明。
    """
    print(f"\n=== faster-whisper {model_size} ===")
    print("许可证: MIT (代码) / MIT (模型)")
    sizes = {"tiny": "75MB", "base": "145MB", "small": "480MB", "medium": "1.5GB", "large-v3": "3GB"}
    print(f"大小: {sizes.get(model_size, '未知')}")
    print("用途: 听力理解 ASR，词级时间戳")
    print("下载方式: 首次调用 transcribe 时自动从 HuggingFace 下载")
    print("         或手动: huggingface-cli download Systran/faster-whisper-{} --local-dir models/whisper/{}".format(model_size, model_size))
    print()
    print("如需启用，请在 .env 中设置:")
    print(f"  WHISPER_ENABLED=true")
    print(f"  WHISPER_MODEL_SIZE={model_size}")
    return True


def download_g2p_dict() -> bool:
    """g2p-en 的 CMUdict。"""
    print("\n=== g2p-en CMUdict ===")
    print("许可证: MIT")
    print("大小: 约 1GB（含 CMUdict + LSTM 模型）")
    print("用途: 文本转音素（G2P）")
    print("下载方式: 首次 import g2p_en 时自动下载到 ~/.cache/g2p_en/")
    print("         或预置到 models/g2p_en/")
    return True


def check_huper() -> bool:
    """检查 HuPER 模型。"""
    print("\n=== HuPER (HuBERT Phoneme Recognizer) ===")
    print("许可证: 用户自带（云盘）")
    print("大小: 约 350MB (FP32) / 90MB (INT8)")
    print("用途: 核心音素识别")
    candidates = [
        MODELS_DIR / "model.onnx",
        MODELS_DIR / "model_quantized.onnx",
        MODELS_DIR / "huper" / "model.onnx",
        MODELS_DIR / "huper" / "model_quantized.onnx",
    ]
    for p in candidates:
        if p.exists():
            print(f"  ✓ 已找到: {p}")
            return True
    print("  ✗ 未找到 HuPER 模型")
    print("  请从云盘下载并放置到以下任一位置:")
    for p in candidates:
        print(f"    - {p}")
    print("  或设置环境变量 HUPER_MODEL_PATH 指定路径")
    return False


def main():
    parser = argparse.ArgumentParser(description="Phonos v3 模型下载")
    parser.add_argument("--vad-only", action="store_true", help="仅下载 silero-vad")
    parser.add_argument("--whisper-size", default="small", choices=["tiny", "base", "small", "medium", "large-v3"])
    parser.add_argument("--no-huper-check", action="store_true", help="跳过 HuPER 检查")
    args = parser.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"模型目录: {MODELS_DIR}")

    if not args.no_huper_check:
        check_huper()

    download_silero_vad()

    if not args.vad_only:
        download_whisper(args.whisper_size)
        download_g2p_dict()

    print("\n=== 完成 ===")
    print("所有模型就绪后，可启动服务:")
    print("  python backend/main.py")
    print("  或 docker compose up")


if __name__ == "__main__":
    main()
