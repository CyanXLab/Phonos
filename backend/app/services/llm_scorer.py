"""LLM 评分服务 - 用大模型给口语/听写/考试作答打分。

支持两种后端：
1. ModelScope API（默认，云端）：
   - MODELSCOPE_API_KEY
   - MODELSCOPE_BASE_URL=https://api-inference.modelscope.cn/v1
   - MODELSCOPE_MODEL=Qwen/Qwen3.5-122B-A10B
2. llama.cpp 本地（可选，离线）：
   - LLAMA_CPP_URL=http://127.0.0.1:8080/v1
   - LLAMA_CPP_MODEL=local

用于：
- 口语应答评分（内容相关性/关键词覆盖/语义完整度/语法可接受度）
- 信息转述评分
- 情景应答评分
- 看图说话评分
- 听写语义近似判断

许可证：
- ModelScope API: 商业（按调用计费，需用户自行注册 key）
- llama.cpp: MIT（本地部署，开源）
- Qwen 模型: Apache 2.0（阿里开源）
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Optional

import urllib.request
import urllib.error

from ..core.config import get_settings
from ..core.logging import get_logger


logger = get_logger("llm_scorer")


@dataclass
class LLMScore:
    """LLM 评分结果。"""
    overall: float  # 0-100
    content_relevance: float  # 内容相关性
    keyword_coverage: float  # 关键词覆盖
    semantic_completeness: float  # 语义完整度
    grammar_accuracy: float  # 语法可接受度
    pronunciation_clarity: float  # 发音清晰度（基于文本推测）
    fluency: float  # 流利度
    feedback: str  # 文字反馈
    raw_response: str = ""


class LLMScorer:
    """LLM 评分器。"""

    def __init__(self):
        settings = get_settings()
        self.api_key = os.environ.get("MODELSCOPE_API_KEY", settings.llm_api_key)
        self.base_url = os.environ.get("MODELSCOPE_BASE_URL", settings.llm_base_url)
        self.model = os.environ.get("MODELSCOPE_MODEL", settings.llm_model)
        self.provider = "modelscope" if self.api_key else "llama_cpp"
        # llama.cpp 本地
        self.llama_url = os.environ.get("LLAMA_CPP_URL", settings.llama_cpp_url)
        self.llama_model = os.environ.get("LLAMA_CPP_MODEL", "local")

    @property
    def available(self) -> bool:
        if self.api_key:
            return True
        if self.llama_url:
            try:
                req = urllib.request.Request(f"{self.llama_url}/models", method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    return resp.status == 200
            except Exception:
                return False
        return False

    def _call_openai_api(self, messages: list, temperature: float = 0.3, max_tokens: int = 800) -> str:
        """调用 OpenAI 兼容 API（ModelScope / llama.cpp 都兼容）。"""
        if self.api_key:
            url = f"{self.base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            model = self.model
        else:
            url = f"{self.llama_url}/chat/completions"
            headers = {"Content-Type": "application/json"}
            model = self.llama_model

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            logger.error("llm_api_error", status=e.code, body=body)
            raise
        except Exception as e:
            logger.error("llm_call_failed", error=str(e))
            raise

    def score_speaking_response(
        self,
        task_type: str,
        prompt: str,
        expected_answer: str,
        user_response: str,
        keywords: Optional[list] = None,
        pronunciation_score: Optional[float] = None,
        fluency_score: Optional[float] = None,
    ) -> LLMScore:
        """评分口语应答（情景应答/信息转述/看图说话/快速应答等）。"""
        keywords = keywords or []

        system_prompt = """你是一位上海高考英语听说考试评分专家。请根据以下标准给考生的口语应答打分：

评分维度（每项 0-100）：
1. content_relevance: 内容相关性 - 是否切题
2. keyword_coverage: 关键词覆盖 - 是否包含关键信息点
3. semantic_completeness: 语义完整度 - 表达是否完整
4. grammar_accuracy: 语法可接受度 - 语法是否正确
5. pronunciation_clarity: 发音清晰度（基于文本推测）
6. fluency: 流利度（基于文本长度和结构推测）

输出 JSON 格式（严格）：
{
  "content_relevance": 85,
  "keyword_coverage": 80,
  "semantic_completeness": 75,
  "grammar_accuracy": 90,
  "pronunciation_clarity": 80,
  "fluency": 85,
  "overall": 82,
  "feedback": "具体的改进建议，用中文"
}

注意：
- overall 应为各维度的加权平均（内容类 60% + 语言类 40%）
- feedback 必须具体、可操作，指出具体问题
- 只输出 JSON，不要其他文字"""

        user_prompt = f"""题型：{task_type}
题目：{prompt}
参考答案：{expected_answer}
关键词：{', '.join(keywords) if keywords else '无'}
考生作答：{user_response}
发音评分（如已评测）：{pronunciation_score or '未评测'}
流利度评分（如已评测）：{fluency_score or '未评测'}

请评分。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._call_openai_api(messages)
            # 解析 JSON
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(response)

            return LLMScore(
                overall=float(data.get("overall", 0)),
                content_relevance=float(data.get("content_relevance", 0)),
                keyword_coverage=float(data.get("keyword_coverage", 0)),
                semantic_completeness=float(data.get("semantic_completeness", 0)),
                grammar_accuracy=float(data.get("grammar_accuracy", 0)),
                pronunciation_clarity=float(data.get("pronunciation_clarity", pronunciation_score or 0)),
                fluency=float(data.get("fluency", fluency_score or 0)),
                feedback=data.get("feedback", ""),
                raw_response=response,
            )
        except json.JSONDecodeError as e:
            logger.error("llm_response_parse_failed", error=str(e), response=response[:300])
            return LLMScore(
                overall=0, content_relevance=0, keyword_coverage=0,
                semantic_completeness=0, grammar_accuracy=0,
                pronunciation_clarity=pronunciation_score or 0,
                fluency=fluency_score or 0,
                feedback=f"LLM 响应解析失败: {e}",
                raw_response=response,
            )
        except Exception as e:
            logger.error("llm_score_failed", error=str(e))
            return LLMScore(
                overall=0, content_relevance=0, keyword_coverage=0,
                semantic_completeness=0, grammar_accuracy=0,
                pronunciation_clarity=pronunciation_score or 0,
                fluency=fluency_score or 0,
                feedback=f"LLM 评分失败: {e}",
            )

    def score_dictation_semantic(self, expected: str, actual: str) -> dict:
        """听写语义近似判断（用 LLM 判断答案是否语义等价）。"""
        system_prompt = """你是英语听写评分专家。判断用户的听写答案与标准答案是否语义等价。

输出 JSON：
{
  "semantic_match": true/false,
  "score": 0-100,
  "differences": ["差异1", "差异2"],
  "feedback": "中文反馈"
}"""

        user_prompt = f"""标准答案：{expected}
用户听写：{actual}

请判断语义是否等价（允许拼写小错、同义词替换，但不允许漏掉关键信息）。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._call_openai_api(messages, max_tokens=300)
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(response)
        except Exception as e:
            return {
                "semantic_match": False,
                "score": 0,
                "differences": [],
                "feedback": f"LLM 判断失败: {e}",
            }

    def health(self) -> dict:
        return {
            "available": self.available,
            "provider": self.provider,
            "model": self.model if self.api_key else self.llama_model,
        }


_scorer_instance: Optional[LLMScorer] = None


def get_llm_scorer() -> LLMScorer:
    global _scorer_instance
    if _scorer_instance is None:
        _scorer_instance = LLMScorer()
    return _scorer_instance
