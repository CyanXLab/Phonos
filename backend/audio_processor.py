"""
音频处理器 - 增益 + 降噪

对用户录音进行：
1. 自动增益控制 (AGC) - 归一化音量
2. 降噪 - 基于频谱门控的降噪算法
3. 预加重 - 增强高频成分，提升识别精度
"""

import numpy as np
from typing import Tuple


def auto_gain(audio: np.ndarray, target_level: float = -3.0) -> np.ndarray:
    """
    自动增益控制 (AGC)

    将音频归一化到目标电平（dBFS）

    参数:
        audio: 输入音频 (float32)
        target_level: 目标电平 dBFS (默认 -3 dBFS)

    返回:
        增益后的音频
    """
    if len(audio) == 0:
        return audio

    # 计算当前 RMS 电平
    rms = np.sqrt(np.mean(audio ** 2))

    if rms < 1e-10:
        return audio  # 静音，不处理

    current_level_db = 20 * np.log10(rms + 1e-10)
    target_db = target_level

    gain_db = target_db - current_level_db
    gain_linear = 10 ** (gain_db / 20.0)

    # 限制增益范围防止爆音
    gain_linear = np.clip(gain_linear, 0.1, 20.0)

    result = audio * gain_linear

    # 硬限幅防止爆音
    max_val = np.max(np.abs(result))
    if max_val > 0.98:
        result = result * (0.98 / max_val)

    return result.astype(np.float32)


def spectral_gate_denoise(
    audio: np.ndarray,
    sr: int = 16000,
    noise_frames: int = 10,
    threshold_factor: float = 1.5,
    frame_size: int = 512,
    hop_size: int = 256,
) -> np.ndarray:
    """
    基于频谱门控的降噪算法

    原理：
    1. 从音频前几帧估计噪声频谱
    2. 对每帧频谱，低于阈值的分量置零或衰减
    3. 重构音频

    参数:
        audio: 输入音频 (float32)
        sr: 采样率
        noise_frames: 用于噪声估计的帧数（默认取前10帧）
        threshold_factor: 噪声阈值因子（越大保留越多原始信号）
        frame_size: FFT帧大小
        hop_size: 帧移大小

    返回:
        降噪后的音频
    """
    if len(audio) < frame_size:
        return audio

    # 加窗
    window = np.hanning(frame_size)

    # 计算帧数
    n_frames = 1 + (len(audio) - frame_size) // hop_size

    # 估计噪声频谱（取前几帧的平均功率谱）
    noise_frames = min(noise_frames, n_frames)
    noise_spectrum = np.zeros(frame_size // 2 + 1)

    for i in range(noise_frames):
        start = i * hop_size
        frame = audio[start:start + frame_size] * window
        spectrum = np.abs(np.fft.rfft(frame))
        noise_spectrum += spectrum

    noise_spectrum /= noise_frames
    noise_threshold = noise_spectrum * threshold_factor

    # 频谱门控降噪
    output = np.zeros_like(audio)
    window_sum = np.zeros(len(audio), dtype=np.float32)

    for i in range(n_frames):
        start = i * hop_size
        end = start + frame_size

        if end > len(audio):
            break

        frame = audio[start:end] * window
        spectrum = np.fft.rfft(frame)
        magnitude = np.abs(spectrum)
        phase = np.angle(spectrum)

        # 门控：低于阈值的频谱分量衰减
        mask = np.ones_like(magnitude)
        below_threshold = magnitude < noise_threshold
        # 软门控：不完全置零，而是大幅衰减
        mask[below_threshold] = magnitude[below_threshold] / (noise_threshold[below_threshold] + 1e-10)
        # 最低保留比例
        mask = np.clip(mask, 0.05, 1.0)

        # 应用掩码
        clean_spectrum = magnitude * mask * np.exp(1j * phase)
        clean_frame = np.fft.irfft(clean_spectrum)

        # 叠加回输出
        output[start:end] += clean_frame * window
        window_sum[start:end] += window ** 2

    # 归一化
    valid = window_sum > 1e-8
    output[valid] /= window_sum[valid]

    return output.astype(np.float32)


def pre_emphasis(audio: np.ndarray, coeff: float = 0.97) -> np.ndarray:
    """
    预加重滤波器

    增强高频成分，提升语音识别精度
    y[n] = x[n] - coeff * x[n-1]

    参数:
        audio: 输入音频
        coeff: 预加重系数（默认0.97）

    返回:
        预加重后的音频
    """
    return np.append(audio[0], audio[1:] - coeff * audio[:-1]).astype(np.float32)


def process_audio(
    audio: np.ndarray,
    sr: int = 16000,
    enable_agc: bool = True,
    enable_denoise: bool = True,
    enable_preemphasis: bool = False,
) -> np.ndarray:
    """
    完整的音频处理管线

    1. 降噪 → 2. 自动增益 → 3. 预加重(可选)

    参数:
        audio: 原始音频 (float32)
        sr: 采样率
        enable_agc: 是否启用自动增益
        enable_denoise: 是否启用降噪
        enable_preemphasis: 是否启用预加重

    返回:
        处理后的音频
    """
    result = audio.copy()

    # 1. 降噪（先降噪后增益，避免放大噪声）
    if enable_denoise:
        result = spectral_gate_denoise(result, sr=sr)

    # 2. 自动增益控制
    if enable_agc:
        result = auto_gain(result, target_level=-3.0)

    # 3. 预加重（可选，通常模型推理不需要，因为模型内部有特征提取）
    if enable_preemphasis:
        result = pre_emphasis(result)

    return result
