"""发音评测 API v2 - 使用 PronunciationProvider 抽象 + 评分 v2。"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException

from ..core.logging import get_logger
from ..core.security import evaluate_limiter
from .deps import get_current_user_v2
from ..services.pronunciation_provider import (
    ModelMode,
    ProviderKind,
    get_provider_registry,
    register_default_providers,
)
from ..services.scoring_v2 import evaluate_pronunciation_v2, result_v2_to_dict


router = APIRouter(prefix="/api/v2", tags=["evaluate"])
logger = get_logger("evaluate_v2")


@router.post("/evaluate")
async def evaluate_v2(
    audio: UploadFile = File(...),
    sentence_text: str = Form(...),
    provider: str = Form("auto"),
    mode: str = Form("balanced"),
    user: dict = Depends(get_current_user_v2),
):
    """发音评测 v2。

    - provider: auto / local_huper / azure / xfyun / youdao
    - mode: high_precision / balanced / low_latency
    """
    if not evaluate_limiter.check(user.get("id", "anon")):
        raise HTTPException(429, "请求过于频繁，请稍后再试")

    # 确保 Provider 已注册
    registry = get_provider_registry()
    if not registry.list_providers():
        register_default_providers()

    # 选择 Provider
    preferred = None
    if provider != "auto":
        try:
            preferred = ProviderKind(provider)
        except ValueError:
            raise HTTPException(400, f"unknown provider: {provider}")

    prov = registry.get_available(preferred)
    if prov is None:
        raise HTTPException(503, "无可用的发音诊断 Provider")

    # 隐私检查
    if prov.requires_network:
        from ..core.config import get_settings

        if not get_settings().upload_user_audio:
            raise HTTPException(
                403,
                f"Provider {prov.kind.value} 需要上传音频，但当前配置禁止上传。"
                "请在 .env 中设置 UPLOAD_USER_AUDIO=true 启用。",
            )

    # 保存音频
    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(await audio.read())
        temp_path = f.name
    try:
        # 加载音频
        audio_np, sr = await asyncio.get_event_loop().run_in_executor(
            None, _load_audio, temp_path
        )

        # G2P
        from g2p_service import get_g2p_service

        g2p = get_g2p_service()
        expected_phonemes = g2p.text_to_phonemes(sentence_text)
        word_boundaries = g2p.text_to_phonemes_with_words(sentence_text)
        expected_stress = g2p.get_stress_pattern(sentence_text)

        # 模式
        try:
            m = ModelMode(mode)
        except ValueError:
            m = ModelMode.BALANCED

        # Provider 诊断
        diagnostic = prov.diagnose(
            audio_np, sr, expected_phonemes, word_boundaries, m
        )

        # 评分 v2
        result = evaluate_pronunciation_v2(
            expected_phonemes=expected_phonemes,
            actual_phonemes=diagnostic.raw_phonemes,
            expected_stress=expected_stress,
            word_boundaries=word_boundaries,
            timeline=diagnostic.timeline,
            blank_segments=diagnostic.blank_segments,
            total_duration=diagnostic.total_duration,
            audio_quality_score=_quality_to_score(diagnostic.audio_quality),
            audio_quality_warning=diagnostic.audio_quality.warning,
            phone_confidences=[p.confidence for p in diagnostic.phonemes],
        )
        result.inference_ms = diagnostic.inference_ms
        result.provider = prov.kind.value
        result.tips = _merge_provider_tips(result.tips, diagnostic.extra)

        # 异步记录到 learning_algorithm
        try:
            from learning_algorithm import get_learning_algorithm

            learning = get_learning_algorithm()
            learning.record_evaluation(
                user_id=user["id"],
                sentence_text=sentence_text,
                expected_phonemes=expected_phonemes,
                actual_phonemes=diagnostic.raw_phonemes,
                scores={
                    "overall": result.scores.overall,
                    "pronunciation": result.scores.phoneme_accuracy,
                    "completeness": result.scores.completeness,
                    "fluency": result.scores.fluency,
                },
                errors=[
                    {
                        "expected": p.expected_phone,
                        "actual": p.recognized_phone,
                        "type": p.error_type.value,
                        "position": i,
                        "similarity": p.score,
                    }
                    for i, p in enumerate(result.phonemes)
                ],
                word_scores=[
                    {"word": w.word, "accuracy": w.accuracy}
                    for w in result.words
                ],
                duration=diagnostic.total_duration,
            )
        except Exception as e:
            logger.warning("record_evaluation_failed", error=str(e))

        return result_v2_to_dict(result)

    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


@router.get("/providers")
async def list_providers(user: dict = Depends(get_current_user_v2)):
    """列出所有可用的发音诊断 Provider。"""
    registry = get_provider_registry()
    if not registry.list_providers():
        register_default_providers()
    return {"providers": registry.list_providers()}


def _load_audio(path: str):
    """多策略音频加载（与 main.py 一致）。"""
    import soundfile as sf

    try:
        audio, sr = sf.read(path, dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=-1)
        return audio, sr
    except Exception:
        pass

    try:
        import librosa

        audio, sr = librosa.load(path, sr=None, mono=True)
        return audio, sr
    except Exception:
        pass

    import subprocess

    out = path + ".wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", path, "-ar", "16000", "-ac", "1", out],
        check=True, capture_output=True,
    )
    audio, sr = sf.read(out, dtype="float32")
    os.unlink(out)
    return audio, sr


def _quality_to_score(quality) -> float:
    """将 AudioQualityReport 转换为 0-100 分。"""
    score = 100.0
    if quality.is_clipped:
        score -= 20
    if quality.is_too_quiet:
        score -= 15
    if quality.is_too_noisy:
        score -= 25
    if quality.silence_ratio > 0.5:
        score -= 10
    return max(0.0, min(100.0, score))


def _merge_provider_tips(tips: list, extra: dict) -> list:
    """合并 Provider 特有的提示（如 Azure 的 prosody_score）。"""
    if extra:
        tips.append({
            "type": "provider_info",
            "description": f"Provider 返回额外评分：{extra}",
            "severity": "low",
        })
    return tips
