"""ONNX INT8 动态量化。

用法：python _quantize_onnx.py <input.onnx> <output.onnx>
"""

import sys
from pathlib import Path


def main():
    in_path = sys.argv[1]
    out_path = sys.argv[2]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    print(f"INT8 动态量化: {in_path} → {out_path}", flush=True)

    from onnxruntime.quantization import quantize_dynamic, QuantType

    quantize_dynamic(
        in_path,
        out_path,
        weight_type=QuantType.QInt8,
        op_types_to_quantize=["MatMul", "Gemm", "Conv"],
        per_channel=True,
        reduce_range=False,
    )

    in_size = Path(in_path).stat().st_size / 1024 / 1024
    out_size = Path(out_path).stat().st_size / 1024 / 1024
    print(f"[OK] {in_size:.1f} MB → {out_size:.1f} MB (压缩率 {out_size/in_size*100:.0f}%)", flush=True)


if __name__ == "__main__":
    main()
