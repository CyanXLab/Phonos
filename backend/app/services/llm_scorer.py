"""LLM 评分服务 - 用大模型给口语/听写/考试作答打分 + 诊断 + 解析 + AI 助手。

支持两种后端：
1. ModelScope API（默认，云端）：
   - MODELSCOPE_API_KEY
   - MODELSCOPE_BASE_URL=https://api-inference.modelscope.cn/v1
   - MODELSCOPE_MODEL=Qwen/Qwen3.5-122B-A10B
2. llama.cpp 本地（可选，离线）：
   - LLAMA_CPP_URL=http://127.0.0.1:8080/v1

功能：
- 口语应答评分（6 维）
- 朗读诊断（发音问题 + 改进建议）
- 听写错因分析（语义判断 + 错因分类）
- 学习画像诊断（错误模式 + 弱项 + 提分路径）
- 个性化推荐（针对弱项生成练习计划）
- AI 助手对话（学生可问英语学习问题）
- 题目解析（每道题的考点 + 解题思路）

防限速：每次 API 调用前等待 llm_api_delay（默认 1.5 秒，可配置）
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
    overall: float
    content_relevance: float
    keyword_coverage: float
    semantic_completeness: float
    grammar_accuracy: float
    pronunciation_clarity: float
    fluency: float
    feedback: str
    raw_response: str = ""


class LLMScorer:
    """LLM 评分器（多场景）。"""

    def __init__(self):
        settings = get_settings()
        self.api_key = os.environ.get("MODELSCOPE_API_KEY", settings.llm_api_key)
        self.base_url = os.environ.get("MODELSCOPE_BASE_URL", settings.llm_base_url)
        self.model = os.environ.get("MODELSCOPE_MODEL", settings.llm_model)
        self.provider = "modelscope" if self.api_key else "llama_cpp"
        self.llama_url = os.environ.get("LLAMA_CPP_URL", settings.llama_cpp_url)
        self.llama_model = os.environ.get("LLAMA_CPP_MODEL", "local")
        self.api_delay = settings.llm_api_delay
        self._last_call_time = 0

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

    def _wait_rate_limit(self):
        """防限速：确保两次调用间隔 >= api_delay。"""
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self.api_delay:
            time.sleep(self.api_delay - elapsed)
        self._last_call_time = time.time()

    def _call_openai_api(self, messages: list, temperature: float = 0.3, max_tokens: int = 800) -> str:
        """调用 OpenAI 兼容 API（ModelScope / llama.cpp 都兼容）。"""
        self._wait_rate_limit()  # 防限速

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
            url, data=json.dumps(payload).encode(),
            headers=headers, method="POST",
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

    # ============================================================
    # 1. 口语应答评分
    # ============================================================
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
        """评分口语应答。"""
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
        except Exception as e:
            logger.error("llm_score_failed", error=str(e))
            return LLMScore(
                overall=0, content_relevance=0, keyword_coverage=0,
                semantic_completeness=0, grammar_accuracy=0,
                pronunciation_clarity=pronunciation_score or 0,
                fluency=fluency_score or 0,
                feedback=f"LLM 评分失败: {e}",
            )

    # ============================================================
    # 2. 朗读诊断（基于音素错误，LLM 给改进建议）
    # ============================================================
    def diagnose_reading(
        self,
        text: str,
        phoneme_errors: list,
        pronunciation_score: float,
        fluency_score: float,
        completeness_score: float,
    ) -> dict:
        """朗读诊断：根据音素错误，给出具体改进建议。

        Args:
            text: 朗读文本
            phoneme_errors: 音素错误列表 [{expected, actual, type, position}]
            pronunciation_score: 发音分
            fluency_score: 流利度分
            completeness_score: 完整度分
        """
        system_prompt = """你是英语发音诊断专家，专门帮助中国学生改进英语发音。

根据学生的音素错误，给出：
1. 错误模式分析（哪些音素反复出错）
2. 母语干扰判断（中文发音习惯导致的问题）
3. 具体改进建议（可操作的练习方法）
4. 推荐练习材料

输出 JSON：
{
  "error_pattern": "错误模式描述",
  "native_interference": "母语干扰分析",
  "suggestions": ["建议1", "建议2", "建议3"],
  "practice_materials": ["练习材料1", "练习材料2"],
  "priority_phonemes": ["最需优先改进的音素1", "音素2"]
}

只输出 JSON。"""

        errors_str = json.dumps(phoneme_errors[:20], ensure_ascii=False)  # 限制数量
        user_prompt = f"""朗读文本：{text}

发音分：{pronunciation_score}
流利度分：{fluency_score}
完整度分：{completeness_score}

音素错误（前20个）：
{errors_str}

请诊断。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._call_openai_api(messages, max_tokens=600)
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(response)
        except Exception as e:
            return {
                "error_pattern": "诊断失败",
                "native_interference": "",
                "suggestions": [f"LLM 诊断失败: {e}"],
                "practice_materials": [],
                "priority_phonemes": [],
            }

    # ============================================================
    # 3. 听写错因分析
    # ============================================================
    def analyze_dictation_errors(
        self,
        expected: str,
        actual: str,
        word_matches: list,
    ) -> dict:
        """听写错因分析：语义判断 + 错因分类。

        Args:
            expected: 标准答案
            actual: 用户听写
            word_matches: 词级对齐结果 [{expected, actual, match_type}]
        """
        system_prompt = """你是英语听写评分专家。分析学生的听写错误，给出错因分析和改进建议。

错因类型：
- phonetic_confusion: 音近词混淆（如 whether/weather）
- homophone: 同音词错误（如 their/there）
- spelling: 拼写错误
- grammar: 语法变形错误（如 go/went）
- missing_word: 漏词
- extra_word: 多词
- order: 顺序错误
- semantic: 语义近似但表达不同

输出 JSON：
{
  "semantic_match": true/false,
  "overall_score": 0-100,
  "error_causes": [
    {"type": "phonetic_confusion", "word": "weather", "actual": "whether", "explanation": "..."}
  ],
  "suggestions": ["建议1", "建议2"],
  "practice_focus": "重点练习方向"
}

只输出 JSON。"""

        user_prompt = f"""标准答案：{expected}
学生听写：{actual}

词级对齐：
{json.dumps(word_matches[:30], ensure_ascii=False)}

请分析错因。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._call_openai_api(messages, max_tokens=500)
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(response)
        except Exception as e:
            return {
                "semantic_match": False,
                "overall_score": 0,
                "error_causes": [],
                "suggestions": [f"LLM 分析失败: {e}"],
                "practice_focus": "",
            }

    # ============================================================
    # 4. 学习画像诊断
    # ============================================================
    def diagnose_learning_profile(
        self,
        user_stats: dict,
        recent_evaluations: list,
        error_phonemes: list,
        error_words: list,
        weak_task_types: list,
    ) -> dict:
        """学习画像诊断：错误模式 + 弱项 + 提分路径。

        Args:
            user_stats: 用户统计 {total_practice, avg_score, ...}
            recent_evaluations: 最近评测记录 [{score, task_type, ...}]
            error_phonemes: 错误音素 Top N
            error_words: 错误词 Top N
            weak_task_types: 弱项题型
        """
        system_prompt = """你是英语学习诊断专家，专门分析上海高考听说考试学生的学习数据。

根据学生的学习数据，输出：
1. learning_pattern: 学习模式分析（如"发音问题为主"、"语法薄弱"等）
2. weak_areas: 弱项清单（具体到音素/题型/技能）
3. error_root_causes: 错误根因（母语干扰/认知/习惯）
4. improvement_path: 提分路径（分阶段计划）
5. estimated_potential: 提分潜力评估（能提多少分）
6. priority_actions: 优先行动项（本周应做什么）

输出 JSON：
{
  "learning_pattern": "...",
  "weak_areas": ["..."],
  "error_root_causes": ["..."],
  "improvement_path": [
    {"stage": "第一阶段(1-2周)", "goal": "...", "actions": ["..."]},
    {"stage": "第二阶段(3-4周)", "goal": "...", "actions": ["..."]}
  ],
  "estimated_potential": "可提升 X-Y 分",
  "priority_actions": ["..."]
}

只输出 JSON。"""

        user_prompt = f"""学生统计：
{json.dumps(user_stats, ensure_ascii=False, default=str)}

最近 {len(recent_evaluations)} 次评测：
{json.dumps(recent_evaluations[:10], ensure_ascii=False, default=str)}

错误音素 Top 10：
{json.dumps(error_phonemes[:10], ensure_ascii=False)}

错误词 Top 10：
{json.dumps(error_words[:10], ensure_ascii=False)}

弱项题型：
{json.dumps(weak_task_types, ensure_ascii=False)}

请诊断。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._call_openai_api(messages, max_tokens=1000)
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(response)
        except Exception as e:
            return {
                "learning_pattern": "诊断失败",
                "weak_areas": [],
                "error_root_causes": [],
                "improvement_path": [],
                "estimated_potential": "",
                "priority_actions": [f"LLM 诊断失败: {e}"],
            }

    # ============================================================
    # 5. 题目解析
    # ============================================================
    def explain_task(
        self,
        task_type: str,
        prompt: str,
        expected_answer: str,
        options: Optional[list] = None,
        correct_option: Optional[int] = None,
        keywords: Optional[list] = None,
    ) -> dict:
        """题目解析：考点 + 解题思路 + 干扰项分析。"""
        system_prompt = """你是上海高考英语听说考试解析专家。为题目生成详细解析。

输出 JSON：
{
  "examination_point": "考点",
  "difficulty_analysis": "难度分析",
  "solution_approach": "解题思路",
  "key_clues": ["关键线索1", "关键线索2"],
  "distractor_analysis": [{"option": "A", "why_wrong": "..."}],
  "tips": "答题技巧",
  "related_knowledge": ["相关知识1", "相关知识2"]
}

只输出 JSON。"""

        options_str = ""
        if options:
            options_str = "\n选项：\n" + "\n".join(
                f"{chr(65+i)}. {opt}" for i, opt in enumerate(options)
            )
            if correct_option is not None:
                options_str += f"\n正确答案：{chr(65+correct_option)}"

        user_prompt = f"""题型：{task_type}
题目：{prompt}
参考答案：{expected_answer}{options_str}
关键词：{', '.join(keywords) if keywords else '无'}

请解析。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._call_openai_api(messages, max_tokens=600)
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(response)
        except Exception as e:
            return {
                "examination_point": "解析失败",
                "difficulty_analysis": "",
                "solution_approach": "",
                "key_clues": [],
                "distractor_analysis": [],
                "tips": f"LLM 解析失败: {e}",
                "related_knowledge": [],
            }

    # ============================================================
    # 6. AI 助手对话
    # ============================================================
    def chat(self, user_message: str, context: Optional[dict] = None) -> str:
        """AI 助手对话：学生可问英语学习问题。

        Args:
            user_message: 学生问题
            context: 上下文（如最近评测、弱项等）
        """
        system_prompt = """你是 Phonos 英语学习助手，专门帮助中国学生准备上海高考英语听说考试。

你的职责：
1. 解答英语学习问题（发音、语法、词汇、听力、口语）
2. 提供备考建议
3. 根据学生的学习数据给出个性化指导
4. 鼓励和激励学生

回答要求：
- 用中文回答
- 简洁明了，避免冗长
- 给出具体可操作的建议
- 适当举例说明
- 如涉及发音，用 IPA 或 ARPAbet 标注"""

        context_str = ""
        if context:
            context_str = f"\n\n学生背景：\n{json.dumps(context, ensure_ascii=False, default=str)}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message + context_str},
        ]

        try:
            return self._call_openai_api(messages, temperature=0.7, max_tokens=500)
        except Exception as e:
            return f"抱歉，AI 助手暂时无法响应：{e}"

    # ============================================================
    # 7. 听写语义判断（旧接口保留）
    # ============================================================
    def score_dictation_semantic(self, expected: str, actual: str) -> dict:
        """听写语义近似判断。"""
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
            "api_delay": self.api_delay,
        }


_scorer_instance: Optional[LLMScorer] = None


def get_llm_scorer() -> LLMScorer:
    global _scorer_instance
    if _scorer_instance is None:
        _scorer_instance = LLMScorer()
    return _scorer_instance
