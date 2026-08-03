"""用 optimum 导出 wav2vec2-base ONNX + INT8 量化（标准方式）。

optimum 是 HuggingFace 官方的 ONNX 导出工具，兼容性最好。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main():
    models_dir = Path("/home/z/my-project/Phonos/models")
    model_dir = models_dir / "wav2vec2_base"
    out_dir = models_dir / "huper_onnx_int8_dynamic"
    out_dir.mkdir(parents=True, exist_ok=True)

    int8_onnx = out_dir / "model_quantized.onnx"

    if int8_onnx.exists() and int8_onnx.stat().st_size > 10_000_000:
        print(f"[跳过] INT8 已存在: {int8_onnx} ({int8_onnx.stat().st_size/1024/1024:.1f} MB)")
        return

    print(f"[1/3] 用 optimum 导出 ONNX...", flush=True)
    from optimum.onnxruntime import ORTModelForCTC
    from transformers import Wav2Vec2Processor

    t0 = time.time()
    ort_model = ORTModelForCTC.from_pretrained(
        "facebook/wav2vec2-base-960h",
        from_transformers=True,
        cache_dir=str(model_dir),
    )
    ort_model.save_pretrained(str(out_dir))
    fp_onnx = out_dir / "model.onnx"
    print(f"  导出耗时: {time.time()-t0:.1f}s, 大小: {fp_onnx.stat().st_size/1024/1024:.1f} MB", flush=True)

    # 保存 processor
    processor = Wav2Vec2Processor.from_pretrained("facebook/wav2vec2-base-960h", cache_dir=str(model_dir))
    processor.save_pretrained(out_dir)

    print(f"[2/3] INT8 动态量化...", flush=True)
    from optimum.onnxruntime import ORTOptimizer, ORTQuantizer
    from optimum.onnxruntime.configuration import OptimizationConfig, DynamicQuantizationConfig

    optimizer = ORTOptimizer.from_pretrained(ort_model)
    optimization_config = OptimizationConfig(optimization_level=99)
    optimizer.optimize(save_dir=str(out_dir), optimization_config=optimization_config)
    optimized_onnx = out_dir / "model_optimized.onnx"

    quantizer = ORTQuantizer.from_pretrained(ort_model)
    dyn_config = DynamicQuantizationConfig(
        weight_type="QInt8",
        op_types_to_quantize=["MatMul", "Gemm"],
        per_channel=True,
        reduce_range=False,
    )
    quantizer.quantize(save_dir=str(out_dir), quantization_config=dyn_config)

    # 找量化后的文件
    candidates = list(out_dir.glob("*quantized*.onnx")) + list(out_dir.glob("model_quantized.onnx"))
    if candidates:
        final = candidates[0]
        if final != int8_onnx:
            final.rename(int8_onnx)
        print(f"  量化后: {int8_onnx.stat().st_size/1024/1024:.1f} MB", flush=True)
    else:
        # 直接用 onnxruntime 量化 optimized 模型
        print("  回退到直接量化...", flush=True)
        from onnxruntime.quantization import quantize_dynamic, QuantType
        quantize_dynamic(
            str(optimized_onnx if optimized_onnx.exists() else str(fp_onnx)),
            str(int8_onnx),
            weight_type=QuantType.QInt8,
            op_types_to_quantize=["MatMul", "Gemm"],
            per_channel=False,
            reduce_range=False,
        )
        print(f"  量化后: {int8_onnx.stat().st_size/1024/1024:.1f} MB", flush=True)

    print(f"\n[3/3] 完成")
    print(f"  FP32: {fp_onnx.stat().st_size/1024/1024:.1f} MB")
    print(f"  INT8: {int8_onnx.stat().st_size/1024/1024:.1f} MB")
    print(f"  压缩率: {int8_onnx.stat().st_size/fp_onnx.stat().st_size*100:.0f}%")


if __name__ == "__main__":
    main()
