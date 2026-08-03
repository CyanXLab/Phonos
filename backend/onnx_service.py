"""
ONNX 推理服务 - HuPER 音素识别

v3 升级点：
1. softmax 置信度输出（不再仅 argmax）
2. providers / intra_op / inter_op 可配置
3. 帧级 confidence 与音素级 confidence 双层输出
4. 兼容旧接口 recognize / recognize_with_timestamps
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
    """HuPER ONNX 音素识别器（v3）。"""

    def __init__(
        self,
        model_path: str,
        providers: Optional[list] = None,
        intra_op_threads: int = 4,
        inter_op_threads: int = 0,
    ):
        import onnxruntime as ort

        if providers is None:
            providers = [
                ("CUDAExecutionProvider", {"device_id": 0}),
                "CPUExecutionProvider",
            ]

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_options.intra_op_num_threads = intra_op_threads
        if inter_op_threads > 0:
            sess_options.inter_op_num_threads = inter_op_threads

        self.session = ort.InferenceSession(
            model_path,
            sess_options=sess_options,
            providers=providers,
        )

        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.provider = self.session.get_providers()[0]
        self.model_path = model_path
        print(f"[HuPER] 模型加载成功, Provider: {self.provider}")

    def preprocess_audio(self, audio: np.ndarray, sr: int = 16000) -> np.ndarray:
        """音频预处理（含增益+降噪+标准化）"""
        import librosa

        if sr != MODEL_CONFIG["sampling_rate"]:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=MODEL_CONFIG["sampling_rate"])

        if audio.ndim > 1:
            audio = audio.mean(axis=-1)

        audio = audio.astype(np.float32)

        audio = process_audio(
            audio,
            sr=MODEL_CONFIG["sampling_rate"],
            enable_agc=True,
            enable_denoise=True,
        )

        if audio.std() > 1e-10:
            audio = (audio - audio.mean()) / audio.std()

        audio = np.expand_dims(audio, axis=0)
        return audio

    def _softmax(self, logits: np.ndarray) -> np.ndarray:
        """数值稳定的 softmax。"""
        x = logits - np.max(logits, axis=-1, keepdims=True)
        e = np.exp(x)
        return e / np.sum(e, axis=-1, keepdims=True)

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
        """音素识别（兼容旧接口）"""
        input_values = self.preprocess_audio(audio, sr)
        outputs = self.session.run([self.output_name], {self.input_name: input_values})
        logits = outputs[0]
        phonemes = self.ctc_greedy_decode(logits)
        return phonemes, logits

    def recognize_with_confidence(self, audio: np.ndarray, sr: int = 16000) -> dict:
        """带置信度的音素识别（v3 新增）。

        返回：
            phonemes: List[str]
            timeline: List[dict]  每个音素含 start_time/end_time/duration/confidence
            blank_segments: List[dict]
            total_duration: float
            num_frames: int
            frame_confidences: List[float]  每帧的 max softmax 概率
        """
        input_values = self.preprocess_audio(audio, sr)
        audio_duration = len(audio) / MODEL_CONFIG["sampling_rate"]

        outputs = self.session.run([self.output_name], {self.input_name: input_values})
        logits = outputs[0]

        # softmax 概率
        probs = self._softmax(logits[0])  # [T, V]
        frame_confidences = np.max(probs, axis=-1)  # [T]
        predicted_ids = np.argmax(logits[0], axis=-1)

        num_frames = len(predicted_ids)
        frame_duration = audio_duration / num_frames if num_frames > 0 else 0

        phoneme_timeline = []
        prev_id = None
        current_start = 0
        current_confidences: list = []

        for t, token_id in enumerate(predicted_ids):
            tid = int(token_id)
            if tid != prev_id:
                if prev_id is not None and prev_id != BLANK_ID:
                    token = ID2TOKEN.get(prev_id, "")
                    if token and token not in ("<UNK>", "<BOS>", "<EOS>", "<s>", "</s>", "|"):
                        # 音素级置信度 = 该音素持续帧的平均 max prob
                        avg_conf = (
                            float(np.mean(current_confidences)) if current_confidences else 0.8
                        )
                        phoneme_timeline.append(
                            {
                                "phoneme": token,
                                "start_frame": current_start,
                                "end_frame": t,
                                "start_time": round(current_start * frame_duration, 3),
                                "end_time": round(t * frame_duration, 3),
                                "duration": round((t - current_start) * frame_duration, 3),
                                "confidence": round(avg_conf, 3),
                            }
                        )
                current_start = t
                current_confidences = []
            current_confidences.append(float(frame_confidences[t]))
            prev_id = tid

        # 最后一个音素
        if prev_id is not None and prev_id != BLANK_ID:
            token = ID2TOKEN.get(prev_id, "")
            if token and token not in ("<UNK>", "<BOS>", "<EOS>", "<s>", "</s>", "|"):
                avg_conf = float(np.mean(current_confidences)) if current_confidences else 0.8
                phoneme_timeline.append(
                    {
                        "phoneme": token,
                        "start_frame": current_start,
                        "end_frame": num_frames,
                        "start_time": round(current_start * frame_duration, 3),
                        "end_time": round(num_frames * frame_duration, 3),
                        "duration": round((num_frames - current_start) * frame_duration, 3),
                        "confidence": round(avg_conf, 3),
                    }
                )

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
                        blank_segments.append(
                            {
                                "start_time": round(blank_start * frame_duration, 3),
                                "end_time": round(t * frame_duration, 3),
                                "duration": round(blank_dur, 3),
                            }
                        )
                    in_blank = False

        phonemes = self.ctc_greedy_decode(logits)

        return {
            "phonemes": phonemes,
            "timeline": phoneme_timeline,
            "blank_segments": blank_segments,
            "total_duration": round(audio_duration, 2),
            "num_frames": num_frames,
            "frame_confidences": frame_confidences.tolist(),
        }

    def recognize_with_timestamps(self, audio: np.ndarray, sr: int = 16000) -> dict:
        """带时间戳的音素识别（兼容旧接口，内部调用 recognize_with_confidence）。"""
        result = self.recognize_with_confidence(audio, sr)
        # 旧接口不要求 frame_confidences，但保留 timeline 中的 confidence
        return result


_model_instance: Optional[HuPERRecognizer] = None


def get_recognizer(model_path: str = None) -> HuPERRecognizer:
    """获取全局模型实例（懒加载）"""
    global _model_instance
    if _model_instance is None:
        if model_path is None or model_path == "":
            # 兜底：从 settings 查找
            try:
                from app.core.config import get_settings

                model_path = get_settings().effective_huper_model_path()
            except Exception:
                model_path = ""
        if not model_path:
            raise ValueError("未找到 HuPER 模型路径，请配置 HUPER_MODEL_PATH 或放置模型文件")
        _model_instance = HuPERRecognizer(model_path)
    return _model_instance


def reset_recognizer() -> None:
    """重置单例（测试用 / 模型热替换）。"""
    global _model_instance
    _model_instance = None
