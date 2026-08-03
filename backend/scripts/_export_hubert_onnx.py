"""把 HuBERT-large PyTorch 模型导出为 ONNX。

从环境变量读取：
- MODEL_DIR: PyTorch 模型目录
- OUT_PATH: 输出 ONNX 路径
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import torch
import torch.nn as nn


def main():
    model_dir = os.environ["MODEL_DIR"]
    out_path = os.environ["OUT_PATH"]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    print(f"加载 PyTorch 模型: {model_dir}", flush=True)
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    # HuBERT-large 用 wav2vec2 架构
    model = Wav2Vec2ForCTC.from_pretrained(
        "facebook/hubert-large-ls960-ft",
        cache_dir=model_dir,
        torchscript=True,
    )
    model.eval()

    # 检查 vocab（ls960 是字符级，但 Phonos 期望 46 类 ARPAbet）
    # 实际：原 Phonos 项目用的是自定义 HuPER 模型，不是 facebook 官方
    # 我们这里导出 facebook 官方 HuBERT-large，CTC 输出是 32 类字符
    # 因此运行时需要做字符→ARPAbet 映射
    vocab_size = model.config.vocab_size
    print(f"vocab_size: {vocab_size}", flush=True)

    # 创建 dummy input（1 秒 16kHz 音频）
    dummy = torch.zeros(1, 16000, dtype=torch.float32)

    print(f"导出 ONNX: {out_path}", flush=True)
    torch.onnx.export(
        model,
        (dummy,),
        out_path,
        input_names=["input_values"],
        output_names=["logits"],
        dynamic_axes={
            "input_values": {0: "batch", 1: "time"},
            "logits": {0: "batch", 1: "time"},
        },
        opset_version=14,
        do_constant_folding=True,
    )

    size_mb = Path(out_path).stat().st_size / 1024 / 1024
    print(f"[OK] ONNX 导出: {size_mb:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
