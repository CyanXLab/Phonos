"""
ONNX 翻译模型服务 - 使用 optimum.onnxruntime 本地模型翻译

在线翻译失败时，使用本地 ONNX 量化 Seq2Seq 模型（如 Opus-MT）进行翻译。
模型路径与 HuPER 音素模型在同一 models/ 目录下。

使用方式:
  from onnx_translate_service import get_onnx_translator, translate_onnx
  
  translator = get_onnx_translator()  # 懒加载
  result = translate_onnx("Hello world")  # -> "你好世界"
"""

import os
import threading
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

# 翻译模型搜索路径（与 HuPER 模型同目录）
_TRANSLATE_MODEL_PATHS = [
    _PROJECT_ROOT / "models" / "onnx_quant",
    _PROJECT_ROOT / "models" / "translation_onnx",
    _SCRIPT_DIR / "models" / "onnx_quant",
    _SCRIPT_DIR / "models" / "translation_onnx",
]

# 环境变量覆盖
_TRANSLATE_MODEL_ENV = "PHONOS_TRANSLATE_MODEL_PATH"


class ONNXTranslator:
    """ONNX 翻译器（懒加载，线程安全）
    
    使用 optimum.onnxruntime 的 ORTModelForSeq2SeqLM 加载量化翻译模型，
    通过 transformers pipeline 执行翻译推理。
    """
    
    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._pipeline = None
        self._loaded = False
        self._load_failed = False  # 加载失败标记，避免反复尝试
        self._lock = threading.Lock()
        self._model_path = None
    
    def _find_model_path(self) -> Optional[str]:
        """自动查找翻译模型目录"""
        env_path = os.environ.get(_TRANSLATE_MODEL_ENV, "")
        if env_path and os.path.isdir(env_path):
            return env_path
        
        for p in _TRANSLATE_MODEL_PATHS:
            if p.is_dir():
                # 验证目录中包含必要的模型文件
                has_model = any(p.glob("*.onnx")) or any(p.glob("model*.json"))
                if has_model:
                    return str(p)
        
        return None
    
    def load(self) -> bool:
        """加载翻译模型（线程安全，仅首次加载）"""
        with self._lock:
            if self._loaded:
                return True
            if self._load_failed:
                return False
            
            try:
                model_path = self._find_model_path()
                if not model_path:
                    print("[翻译模型] 未找到 ONNX 翻译模型目录，跳过本地模型翻译")
                    print(f"[翻译模型] 搜索路径: {[str(p) for p in _TRANSLATE_MODEL_PATHS]}")
                    print(f"[翻译模型] 可设置环境变量 {_TRANSLATE_MODEL_ENV} 指定路径")
                    self._load_failed = True
                    return False
                
                self._model_path = model_path
                print(f"[翻译模型] 正在加载: {model_path}")
                
                # 优先使用 optimum.onnxruntime（ONNX 优化推理）
                try:
                    from optimum.onnxruntime import ORTModelForSeq2SeqLM
                    from transformers import AutoTokenizer, pipeline
                    
                    self._model = ORTModelForSeq2SeqLM.from_pretrained(model_path)
                    self._tokenizer = AutoTokenizer.from_pretrained(model_path)
                    self._pipeline = pipeline(
                        "translation_en_to_zh",
                        model=self._model,
                        tokenizer=self._tokenizer,
                    )
                    self._loaded = True
                    print(f"[翻译模型] ORTModelForSeq2SeqLM 加载成功")
                    return True
                    
                except ImportError as e:
                    print(f"[翻译模型] optimum.onnxruntime 未安装，尝试 transformers 回退: {e}")
                
                # 回退：使用 transformers 直接加载（如果不是 ONNX 格式也能用）
                try:
                    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, pipeline
                    
                    self._model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
                    self._tokenizer = AutoTokenizer.from_pretrained(model_path)
                    self._pipeline = pipeline(
                        "translation_en_to_zh",
                        model=self._model,
                        tokenizer=self._tokenizer,
                    )
                    self._loaded = True
                    print(f"[翻译模型] AutoModelForSeq2SeqLM 加载成功（非ONNX模式）")
                    return True
                    
                except Exception as e:
                    print(f"[翻译模型] transformers 回退加载也失败: {e}")
                
                self._load_failed = True
                return False
                
            except Exception as e:
                print(f"[翻译模型] 加载失败: {e}")
                self._load_failed = True
                return False
    
    def translate(self, text: str) -> Optional[str]:
        """翻译英文文本到中文
        
        Args:
            text: 英文文本
            
        Returns:
            翻译后的中文文本，失败返回 None
        """
        if not self._loaded and not self.load():
            return None
        
        try:
            result = self._pipeline(text)
            if result and isinstance(result, list) and len(result) > 0:
                translated = result[0].get("translation_text", "")
                if translated and translated.strip() != text.strip():
                    return translated.strip()
            return None
        except Exception as e:
            print(f"[翻译模型] 推理失败: {e}")
            return None
    
    @property
    def is_loaded(self) -> bool:
        return self._loaded
    
    @property
    def model_path(self) -> Optional[str]:
        return self._model_path


# ============================================================
# 全局单例
# ============================================================
_translator: Optional[ONNXTranslator] = None
_translator_lock = threading.Lock()


def get_onnx_translator() -> ONNXTranslator:
    """获取 ONNX 翻译器单例（懒加载）"""
    global _translator
    with _translator_lock:
        if _translator is None:
            _translator = ONNXTranslator()
        return _translator


def translate_onnx(text: str) -> Optional[str]:
    """使用 ONNX 翻译模型翻译（便捷函数）"""
    return get_onnx_translator().translate(text)


def is_onnx_translate_available() -> bool:
    """检查 ONNX 翻译模型是否可用"""
    translator = get_onnx_translator()
    return translator.is_loaded or translator._find_model_path() is not None
