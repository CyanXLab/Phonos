"""
ONNX 推理服务 - HuPER 音素识别

基于 infer_huper.py 的推理逻辑封装为服务
"""

import numpy as np
from typing import List, Tuple, Optional


# 音素词汇表
VOCAB = {
    "<PAD>": 0, "<UNK>": 1, "<BOS>": 2, "<EOS>": 3, "|": 4,
    "AA": 5, "AE": 6, "AH": 7, "AW": 8, "AY": 9,
    "B": 10, "CH": 11, "D": 12, "DH": 13, "DX": 14,
    "EH": 15, "ER": 16, "EY": 17, "F": 18, "G": 19,
    "HH": 20, "IH": 21, "IY": 22, "JH": 23, "K": 24,
    "L": 25, "M": 26, "N": 27, "NG": 28, "OW": 29,
    "OY": 30, "P": 31, "R": 32, "S": 33, "SH": 34,
    "T": 35, "TH": 36, "UH": 37, "UW": 38, "V": 39,
    "W": 40, "Y": 41, "Z": 42, "ZH": 43,
    "<s>": 44, "</s>": 45,
}

ID2TOKEN = {v: k for k, v in VOCAB.items()}
BLANK_ID = 0

MODEL_CONFIG = {
    "sampling_rate": 16000,
    "do_normalize": True,
    "vocab_size": 46,
}


class HuPERRecognizer:
    """HuPER ONNX 音素识别器"""

    def __init__(self, model_path: str):
        """
        初始化识别器

        参数:
            model_path: ONNX 模型文件路径
        """
        import onnxruntime as ort

        providers = [
            ("CUDAExecutionProvider", {"device_id": 0}),
            "CPUExecutionProvider",
        ]

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_options.intra_op_num_threads = 4

        self.session = ort.InferenceSession(
            model_path,
            sess_options=sess_options,
            providers=providers,
        )

        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.provider = self.session.get_providers()[0]
        print(f"[HuPER] 模型加载成功, Provider: {self.provider}")

    def preprocess_audio(self, audio: np.ndarray, sr: int = 16000) -> np.ndarray:
        """
        音频预处理 (与 Wav2Vec2FeatureExtractor 一致)

        参数:
            audio: 原始音频数据 (float32)
            sr: 采样率

        返回:
            预处理后的音频, shape (1, seq_len)
        """
        import librosa

        # 重采样
        if sr != MODEL_CONFIG["sampling_rate"]:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=MODEL_CONFIG["sampling_rate"])

        # 单声道
        if audio.ndim > 1:
            audio = audio.mean(axis=-1)

        # float32
        audio = audio.astype(np.float32)

        # 标准化
        if audio.std() > 1e-10:
            audio = (audio - audio.mean()) / audio.std()

        # 添加 batch 维度
        audio = np.expand_dims(audio, axis=0)

        return audio

    def ctc_greedy_decode(self, logits: np.ndarray) -> List[str]:
        """
        CTC 贪婪解码

        参数:
            logits: 模型输出, shape (1, time, vocab_size)

        返回:
            解码后的音素列表
        """
        predicted_ids = np.argmax(logits[0], axis=-1)

        decoded = []
        prev_id = None
        for token_id in predicted_ids:
            tid = int(token_id)
            if tid != BLANK_ID and tid != prev_id:
                token = ID2TOKEN.get(tid, f"<unk_{tid}>")
                # 跳过特殊 token
                if token not in ("<UNK>", "<BOS>", "<EOS>", "<s>", "</s>", "|"):
                    decoded.append(token)
            prev_id = tid

        return decoded

    def recognize(self, audio: np.ndarray, sr: int = 16000) -> Tuple[List[str], np.ndarray]:
        """
        音素识别

        参数:
            audio: 原始音频数据
            sr: 采样率

        返回:
            (phonemes, logits): 音素列表和原始 logits
        """
        # 预处理
        input_values = self.preprocess_audio(audio, sr)

        # 推理
        outputs = self.session.run([self.output_name], {self.input_name: input_values})
        logits = outputs[0]

        # 解码
        phonemes = self.ctc_greedy_decode(logits)

        return phonemes, logits

    def recognize_with_timestamps(self, audio: np.ndarray, sr: int = 16000) -> dict:
        """
        带时间戳的音素识别（用于流利度分析）

        参数:
            audio: 原始音频数据
            sr: 采样率

        返回:
            dict: 包含音素列表和时间信息
        """
        input_values = self.preprocess_audio(audio, sr)

        # 音频总时长
        audio_duration = len(audio) / MODEL_CONFIG["sampling_rate"]

        # 推理
        outputs = self.session.run([self.output_name], {self.input_name: input_values})
        logits = outputs[0]

        # 解码（保留重复信息用于分析停顿）
        predicted_ids = np.argmax(logits[0], axis=-1)
        num_frames = len(predicted_ids)
        frame_duration = audio_duration / num_frames if num_frames > 0 else 0

        # 分析每个音素的时间信息
        phoneme_timeline = []
        prev_id = None
        current_start = 0

        for t, token_id in enumerate(predicted_ids):
            tid = int(token_id)
            if tid != prev_id:
                if prev_id is not None and prev_id != BLANK_ID:
                    token = ID2TOKEN.get(prev_id, "")
                    if token and token not in ("<UNK>", "<BOS>", "<EOS>", "<s>", "</s>", "|"):
                        phoneme_timeline.append({
                            "phoneme": token,
                            "start_frame": current_start,
                            "end_frame": t,
                            "start_time": current_start * frame_duration,
                            "end_time": t * frame_duration,
                            "duration": (t - current_start) * frame_duration,
                        })
                current_start = t
            prev_id = tid

        # 最后一个音素
        if prev_id is not None and prev_id != BLANK_ID:
            token = ID2TOKEN.get(prev_id, "")
            if token and token not in ("<UNK>", "<BOS>", "<EOS>", "<s>", "</s>", "|"):
                phoneme_timeline.append({
                    "phoneme": token,
                    "start_frame": current_start,
                    "end_frame": num_frames,
                    "start_time": current_start * frame_duration,
                    "end_time": num_frames * frame_duration,
                    "duration": (num_frames - current_start) * frame_duration,
                })

        # 计算空白段（停顿）
        blank_segments = []
        in_blank = False
        blank_start = 0
        for t, token_id in enumerate(predicted_ids):
            tid = int(token_id)
            if tid == BLANK_ID:
                if not in_blank:
                    blank_start = t
                    in_blank = True
            else:
                if in_blank:
                    blank_dur = (t - blank_start) * frame_duration
                    if blank_dur > 0.15:  # 超过150ms算停顿
                        blank_segments.append({
                            "start_time": blank_start * frame_duration,
                            "end_time": t * frame_duration,
                            "duration": blank_dur,
                        })
                    in_blank = False

        # 去重去空白的最终音素列表
        phonemes = self.ctc_greedy_decode(logits)

        return {
            "phonemes": phonemes,
            "timeline": phoneme_timeline,
            "blank_segments": blank_segments,
            "total_duration": audio_duration,
            "num_frames": num_frames,
        }


# 全局模型实例
_model_instance: Optional[HuPERRecognizer] = None


def get_recognizer(model_path: str = None) -> HuPERRecognizer:
    """获取全局模型实例（懒加载）"""
    global _model_instance
    if _model_instance is None:
        if model_path is None:
            raise ValueError("首次调用必须提供 model_path")
        _model_instance = HuPERRecognizer(model_path)
    return _model_instance
