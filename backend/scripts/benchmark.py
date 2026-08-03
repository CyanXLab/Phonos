"""benchmark 脚本：测量发音评测延迟与吞吐。

用法：
    python backend/scripts/benchmark.py --audio test.wav --text "hello world"
    python backend/scripts/benchmark.py --suite  # 跑完整测试集
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))


def benchmark_single(audio_path: str, text: str, iterations: int = 10) -> dict:
    """单条音频 benchmark。"""
    import numpy as np
    import soundfile as sf

    from audio_processor import process_audio
    from g2p_service import get_g2p_service
    from onnx_service import get_recognizer
    from scoring import evaluate_pronunciation, generate_error_tips, result_to_dict
    from app.core.config import get_settings

    settings = get_settings()
    model_path = settings.effective_huper_model_path()
    if not model_path:
        return {"error": "HuPER model not found"}

    # 加载音频
    audio, sr = sf.read(audio_path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=-1)

    # G2P
    g2p = get_g2p_service()
    expected_phonemes = g2p.text_to_phonemes(text)

    # 预热
    recognizer = get_recognizer(model_path)
    recognizer.recognize_with_timestamps(audio, sr)

    # 正式 benchmark
    latencies = []
    for i in range(iterations):
        t0 = time.perf_counter()
        result = recognizer.recognize_with_timestamps(audio, sr)
        eval_result = evaluate_pronunciation(
            expected_phonemes=expected_phonemes,
            actual_phonemes=result["phonemes"],
            timeline=result["timeline"],
            blank_segments=result["blank_segments"],
            total_duration=result["total_duration"],
        )
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000)

    latencies.sort()
    return {
        "audio_path": audio_path,
        "audio_duration_sec": round(len(audio) / sr, 2),
        "iterations": iterations,
        "latency_ms": {
            "min": round(latencies[0], 1),
            "p50": round(statistics.median(latencies), 1),
            "p95": round(latencies[int(len(latencies) * 0.95)], 1),
            "p99": round(latencies[int(len(latencies) * 0.99)], 1),
            "max": round(latencies[-1], 1),
            "mean": round(statistics.mean(latencies), 1),
            "stdev": round(statistics.stdev(latencies), 1) if len(latencies) > 1 else 0,
        },
        "rtf": round(statistics.mean(latencies) / (len(audio) / sr * 1000), 3),  # 实时率
        "provider": recognizer.provider,
        "model_mode": settings.huper_model_mode,
    }


def benchmark_provider_registry():
    """Provider 注册表 benchmark。"""
    from app.services.pronunciation_provider import (
        get_provider_registry,
        register_default_providers,
    )

    register_default_providers()
    registry = get_provider_registry()
    return {"providers": registry.list_providers()}


def main():
    parser = argparse.ArgumentParser(description="Phonos v3 Benchmark")
    parser.add_argument("--audio", help="音频文件路径")
    parser.add_argument("--text", default="The weather is beautiful today", help="评测文本")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--suite", action="store_true", help="跑完整测试套件")
    parser.add_argument("--output", default="benchmark_results.json", help="结果输出文件")
    args = parser.parse_args()

    results = {
        "timestamp": time.time(),
        "version": "3.0.0",
    }

    # Provider 状态
    results["providers"] = benchmark_provider_registry()

    # 单条 benchmark
    if args.audio:
        results["single"] = benchmark_single(args.audio, args.text, args.iterations)
        print(json.dumps(results["single"], indent=2, ensure_ascii=False))

    # 完整套件
    if args.suite:
        suite_dir = PROJECT_ROOT / "bench" / "calibration_set"
        if suite_dir.is_dir():
            suite_results = []
            for wav in suite_dir.glob("*.wav"):
                txt_file = wav.with_suffix(".txt")
                text = txt_file.read_text(encoding="utf-8").strip() if txt_file.exists() else "hello"
                r = benchmark_single(str(wav), text, args.iterations)
                r["file"] = wav.name
                suite_results.append(r)
            results["suite"] = suite_results
            # 汇总
            all_p95 = [r["latency_ms"]["p95"] for r in suite_results if "latency_ms" in r]
            if all_p95:
                results["summary"] = {
                    "files_tested": len(suite_results),
                    "p95_mean": round(statistics.mean(all_p95), 1),
                    "p95_max": round(max(all_p95), 1),
                    "target_p95_cpu_ms": 2000,
                    "target_p95_gpu_ms": 500,
                    "meets_cpu_target": all(p < 2000 for p in all_p95),
                }
        else:
            print(f"[警告] 测试集目录不存在: {suite_dir}")

    # 输出
    output_path = PROJECT_ROOT / args.output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {output_path}")


if __name__ == "__main__":
    main()
