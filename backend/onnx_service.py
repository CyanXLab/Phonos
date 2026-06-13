"""
ONNX 推理服务 - HuPER 音素识别

基于 infer_huper.py 封装，集成音频预处理管线
"""

import numpy as np
from typing import List, Tuple, Optional

from phoneme_data import VOCAB, ID2TOKEN, BLANK_ID
from audio_processor import process_audio


MODEL_CONFIG = {
    "sampling_rate": 16000,
    "do_normalize": True,
    "vocab_size": 46,
}


class HuPERRecognizer:
    """HuPER ONNX 音素识别器"""

    def __init__(self, model_path: str):
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
        """音频预处理（含增益+降噪+标准化）"""
        import librosa

        # 重采样
        if sr != MODEL_CONFIG["sampling_rate"]:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=MODEL_CONFIG["sampling_rate"])

        # 单声道
        if audio.ndim > 1:
            audio = audio.mean(axis=-1)

        audio = audio.astype(np.float32)

        # 音频增强：增益 + 降噪
        audio = process_audio(audio, sr=MODEL_CONFIG["sampling_rate"],
                              enable_agc=True, enable_denoise=True)

        # 标准化（与 Wav2Vec2FeatureExtractor 一致）
        if audio.std() > 1e-10:
            audio = (audio - audio.mean()) / audio.std()

        # 添加 batch 维度
        audio = np.expand_dims(audio, axis=0)
        return audio

    def ctc_greedy_decode(self, logits: np.ndarray) -> List[str]:
        """CTC 贪婪解码"""
        predicted_ids = np.argmax(logits[0], axis=-1)
        decoded = []
        prev_id = None
        for token_id in predicted_ids:
            tid = int(token_id)
            if tid != BLANK_ID and tid != prev_id:
                token = ID2TOKEN.get(tid, f"<unk_{tid}>")
                if token not in ("<UNK>", "<BOS>", "<EOS>", "<s>", "</s>", "|"):
                    decoded.append(token)
            prev_id = tid
        return decoded

    def recognize(self, audio: np.ndarray, sr: int = 16000) -> Tuple[List[str], np.ndarray]:
        """音素识别"""
        input_values = self.preprocess_audio(audio, sr)
        outputs = self.session.run([self.output_name], {self.input_name: input_values})
        logits = outputs[0]
        phonemes = self.ctc_greedy_decode(logits)
        return phonemes, logits

    def recognize_with_timestamps(self, audio: np.ndarray, sr: int = 16000) -> dict:
        """带时间戳的音素识别"""
        input_values = self.preprocess_audio(audio, sr)
        audio_duration = len(audio) / MODEL_CONFIG["sampling_rate"]

        outputs = self.session.run([self.output_name], {self.input_name: input_values})
        logits = outputs[0]

        predicted_ids = np.argmax(logits[0], axis=-1)
        num_frames = len(predicted_ids)
        frame_duration = audio_duration / num_frames if num_frames > 0 else 0

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
                            "start_time": round(current_start * frame_duration, 3),
                            "end_time": round(t * frame_duration, 3),
                            "duration": round((t - current_start) * frame_duration, 3),
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
                    "start_time": round(current_start * frame_duration, 3),
                    "end_time": round(num_frames * frame_duration, 3),
                    "duration": round((num_frames - current_start) * frame_duration, 3),
                })

        # 停顿检测
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
                    if blank_dur > 0.15:
                        blank_segments.append({
                            "start_time": round(blank_start * frame_duration, 3),
                            "end_time": round(t * frame_duration, 3),
                            "duration": round(blank_dur, 3),
                        })
                    in_blank = False

        phonemes = self.ctc_greedy_decode(logits)

        return {
            "phonemes": phonemes,
            "timeline": phoneme_timeline,
            "blank_segments": blank_segments,
            "total_duration": round(audio_duration, 2),
            "num_frames": num_frames,
        }


_model_instance: Optional[HuPERRecognizer] = None


def get_recognizer(model_path: str = None) -> HuPERRecognizer:
    """获取全局模型实例（懒加载）"""
    global _model_instance
    if _model_instance is None:
        if model_path is None:
            raise ValueError("首次调用必须提供 model_path")
        _model_instance = HuPERRecognizer(model_path)
    return _model_instance
