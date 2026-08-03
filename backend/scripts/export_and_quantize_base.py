"""导出 wav2vec2-base-960h 为 ONNX + INT8 量化。

这个模型比 HuBERT-large 小 4 倍，导出和量化更快，内存占用更低。
CTC 输出 32 类字符（小写字母 + | + special），运行时映射到 ARPAbet。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main():
    import torch
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    models_dir = Path("/home/z/my-project/Phonos/models")
    model_dir = models_dir / "wav2vec2_base"
    out_dir = models_dir / "huper_onnx_int8_dynamic"
    out_dir.mkdir(parents=True, exist_ok=True)

    fp_onnx = out_dir / "model.onnx"
    int8_onnx = out_dir / "model_quantized.onnx"

    if int8_onnx.exists() and int8_onnx.stat().st_size > 1_000_000:
        print(f"[跳过] INT8 已存在: {int8_onnx} ({int8_onnx.stat().st_size/1024/1024:.1f} MB)")
        return

    print(f"[1/3] 加载 PyTorch 模型: {model_dir}", flush=True)
    model = Wav2Vec2ForCTC.from_pretrained(
        "facebook/wav2vec2-base-960h",
        cache_dir=str(model_dir),
    )
    model.eval()

    vocab_size = model.config.vocab_size
    print(f"  vocab_size: {vocab_size}", flush=True)

    # 保存 processor（含 tokenizer）
    processor = Wav2Vec2Processor.from_pretrained("facebook/wav2vec2-base-960h", cache_dir=str(model_dir))
    processor.save_pretrained(out_dir)

    # dummy input
    dummy = torch.zeros(1, 16000, dtype=torch.float32)

    print(f"[2/3] 导出 ONNX: {fp_onnx}", flush=True)
    t0 = time.time()
    torch.onnx.export(
        model,
        (dummy,),
        str(fp_onnx),
        input_names=["input_values"],
        output_names=["logits"],
        dynamic_axes={
            "input_values": {0: "batch", 1: "time"},
            "logits": {0: "batch", 1: "time"},
        },
        opset_version=14,
        do_constant_folding=True,
    )
    print(f"  ONNX 导出耗时: {time.time()-t0:.1f}s, 大小: {fp_onnx.stat().st_size/1024/1024:.1f} MB", flush=True)

    print(f"[3/3] INT8 动态量化: {int8_onnx}", flush=True)
    from onnxruntime.quantization import quantize_dynamic, QuantType
    t0 = time.time()
    quantize_dynamic(
        str(fp_onnx),
        str(int8_onnx),
        weight_type=QuantType.QInt8,
        op_types_to_quantize=["MatMul", "Gemm", "Conv"],
        per_channel=True,
        reduce_range=False,
    )
    print(f"  量化耗时: {time.time()-t0:.1f}s, 大小: {int8_onnx.stat().st_size/1024/1024:.1f} MB", flush=True)
    print(f"\n[完成] INT8 模型: {int8_onnx}", flush=True)
    print(f"  原始: {fp_onnx.stat().st_size/1024/1024:.1f} MB", flush=True)
    print(f"  量化: {int8_onnx.stat().st_size/1024/1024:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
