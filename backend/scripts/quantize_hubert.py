"""wav2vec2-base-960h → ONNX → INT8 量化（小模型，可在 4GB 内存沙盒运行）。

输出：models/huper_onnx_int8_dynamic/model_quantized.onnx
原始：360MB → INT8：约 90-117MB
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main():
    import torch
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    models_dir = Path(__file__).resolve().parents[2] / "models"
    model_dir = models_dir / "wav2vec2_base"
    out_dir = models_dir / "huper_onnx_int8_dynamic"
    out_dir.mkdir(parents=True, exist_ok=True)

    fp_onnx = out_dir / "model.onnx"
    int8_onnx = out_dir / "model_quantized.onnx"

    if int8_onnx.exists() and int8_onnx.stat().st_size > 10_000_000:
        print(f"[跳过] INT8 已存在: {int8_onnx} ({int8_onnx.stat().st_size/1024/1024:.1f} MB)")
        return

    print(f"[1/3] 加载 wav2vec2-base-960h", flush=True)
    model = Wav2Vec2ForCTC.from_pretrained("facebook/wav2vec2-base-960h", cache_dir=str(model_dir))
    model.eval()
    print(f"  vocab_size: {model.config.vocab_size}", flush=True)

    processor = Wav2Vec2Processor.from_pretrained("facebook/wav2vec2-base-960h", cache_dir=str(model_dir))
    processor.save_pretrained(out_dir)

    dummy = torch.zeros(1, 8000, dtype=torch.float32)

    print(f"[2/3] 导出 ONNX (opset 17, dynamo=False)", flush=True)
    t0 = time.time()
    torch.onnx.export(
        model, (dummy,), str(fp_onnx),
        input_names=["input_values"], output_names=["logits"],
        dynamic_axes={"input_values": {0: "batch", 1: "time"}, "logits": {0: "batch", 1: "time"}},
        opset_version=17, do_constant_folding=True, dynamo=False,
    )
    print(f"  耗时: {time.time()-t0:.1f}s, FP32: {fp_onnx.stat().st_size/1024/1024:.1f} MB", flush=True)

    print(f"[3/3] INT8 动态量化", flush=True)
    from onnxruntime.quantization import quantize_dynamic, QuantType
    t0 = time.time()
    quantize_dynamic(
        str(fp_onnx), str(int8_onnx),
        weight_type=QuantType.QInt8,
        op_types_to_quantize=["MatMul", "Gemm"],
        per_channel=False, reduce_range=False,
    )
    print(f"  耗时: {time.time()-t0:.1f}s, INT8: {int8_onnx.stat().st_size/1024/1024:.1f} MB", flush=True)

    print(f"\n[完成]")
    print(f"  FP32: {fp_onnx.stat().st_size/1024/1024:.1f} MB")
    print(f"  INT8: {int8_onnx.stat().st_size/1024/1024:.1f} MB")
    fp_onnx.unlink()
    print(f"  已删除 FP32")


if __name__ == "__main__":
    main()
