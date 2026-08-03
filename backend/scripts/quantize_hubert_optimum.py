"""用 optimum 导出 HuBERT-large ONNX + INT8 量化（更高效）。

optimum 用 dynamo=False 的方式，避免 torch.onnx.export 的性能问题。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main():
    models_dir = Path(__file__).resolve().parents[2] / "models"
    model_dir = models_dir / "hubert_large"
    out_dir = models_dir / "huper_onnx_int8_dynamic"
    out_dir.mkdir(parents=True, exist_ok=True)

    int8_onnx = out_dir / "model_quantized.onnx"

    if int8_onnx.exists() and int8_onnx.stat().st_size > 100_000_000:
        print(f"[跳过] INT8 已存在: {int8_onnx} ({int8_onnx.stat().st_size/1024/1024:.1f} MB)")
        return

    print(f"[1/3] 用 optimum 导出 HuBERT-large ONNX...", flush=True)
    from optimum.onnxruntime import ORTModelForCTC
    from transformers import Wav2Vec2Processor

    t0 = time.time()
    try:
        ort_model = ORTModelForCTC.from_pretrained(
            "facebook/hubert-large-ls960-ft",
            cache_dir=str(model_dir),
            export=True,
            provider="CPUExecutionProvider",
        )
        ort_model.save_pretrained(str(out_dir))
        fp_onnx = out_dir / "model.onnx"
        print(f"  导出耗时: {time.time()-t0:.1f}s, 大小: {fp_onnx.stat().st_size/1024/1024:.1f} MB", flush=True)
    except Exception as e:
        print(f"  optimum 导出失败: {e}", flush=True)
        print("  回退到 torch.onnx.export...", flush=True)
        # 回退
        import torch
        from transformers import HubertForCTC
        model = HubertForCTC.from_pretrained("facebook/hubert-large-ls960-ft", cache_dir=str(model_dir))
        model.eval()
        dummy = torch.zeros(1, 16000, dtype=torch.float32)
        torch.onnx.export(
            model, (dummy,), str(out_dir / "model.onnx"),
            input_names=["input_values"], output_names=["logits"],
            dynamic_axes={"input_values": {0: "batch", 1: "time"}, "logits": {0: "batch", 1: "time"}},
            opset_version=17, do_constant_folding=True, dynamo=False,
        )
        fp_onnx = out_dir / "model.onnx"

    # 保存 processor
    processor = Wav2Vec2Processor.from_pretrained("facebook/hubert-large-ls960-ft", cache_dir=str(model_dir))
    processor.save_pretrained(out_dir)

    print(f"[2/3] INT8 动态量化...", flush=True)
    from onnxruntime.quantization import quantize_dynamic, QuantType
    t0 = time.time()
    quantize_dynamic(
        str(fp_onnx), str(int8_onnx),
        weight_type=QuantType.QInt8,
        op_types_to_quantize=["MatMul", "Gemm"],
        per_channel=False, reduce_range=False,
    )
    print(f"  量化耗时: {time.time()-t0:.1f}s, INT8 大小: {int8_onnx.stat().st_size/1024/1024:.1f} MB", flush=True)

    print(f"\n[完成]")
    print(f"  FP32: {fp_onnx.stat().st_size/1024/1024:.1f} MB")
    print(f"  INT8: {int8_onnx.stat().st_size/1024/1024:.1f} MB")
    # 删除 FP32 节省空间
    fp_onnx.unlink()
    print(f"  已删除 FP32")


if __name__ == "__main__":
    main()
