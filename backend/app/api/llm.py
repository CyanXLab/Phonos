"""LLM 评分 / 诊断 / 助手 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .deps import require_user
from ..services.llm_scorer import get_llm_scorer


router = APIRouter(prefix="/api/llm", tags=["llm"])


class ScoreSpeakingRequest(BaseModel):
    task_type: str
    prompt: str
    expected_answer: str
    user_response: str
    keywords: list[str] = Field(default_factory=list)
    pronunciation_score: float | None = None
    fluency_score: float | None = None


class DiagnoseReadingRequest(BaseModel):
    text: str
    phoneme_errors: list
    pronunciation_score: float
    fluency_score: float
    completeness_score: float


class AnalyzeDictationRequest(BaseModel):
    expected: str
    actual: str
    word_matches: list


class DiagnoseLearningRequest(BaseModel):
    user_stats: dict
    recent_evaluations: list = Field(default_factory=list)
    error_phonemes: list = Field(default_factory=list)
    error_words: list = Field(default_factory=list)
    weak_task_types: list = Field(default_factory=list)


class ExplainTaskRequest(BaseModel):
    task_type: str
    prompt: str
    expected_answer: str
    options: list | None = None
    correct_option: int | None = None
    keywords: list | None = None


class ChatRequest(BaseModel):
    message: str
    context: dict | None = None


@router.get("/health")
async def health(user: dict = Depends(require_user)):
    """LLM 服务健康检查。"""
    scorer = get_llm_scorer()
    return scorer.health()


@router.post("/score")
async def score_speaking(req: ScoreSpeakingRequest, user: dict = Depends(require_user)):
    """评分口语应答。"""
    scorer = get_llm_scorer()
    if not scorer.available:
        raise HTTPException(503, "LLM 服务不可用")
    result = scorer.score_speaking_response(
        task_type=req.task_type, prompt=req.prompt,
        expected_answer=req.expected_answer, user_response=req.user_response,
        keywords=req.keywords, pronunciation_score=req.pronunciation_score,
        fluency_score=req.fluency_score,
    )
    return {
        "overall": result.overall,
        "content_relevance": result.content_relevance,
        "keyword_coverage": result.keyword_coverage,
        "semantic_completeness": result.semantic_completeness,
        "grammar_accuracy": result.grammar_accuracy,
        "pronunciation_clarity": result.pronunciation_clarity,
        "fluency": result.fluency,
        "feedback": result.feedback,
    }


@router.post("/diagnose-reading")
async def diagnose_reading(req: DiagnoseReadingRequest, user: dict = Depends(require_user)):
    """朗读诊断（发音问题 + 改进建议）。"""
    scorer = get_llm_scorer()
    if not scorer.available:
        raise HTTPException(503, "LLM 服务不可用")
    return scorer.diagnose_reading(
        text=req.text, phoneme_errors=req.phoneme_errors,
        pronunciation_score=req.pronunciation_score,
        fluency_score=req.fluency_score,
        completeness_score=req.completeness_score,
    )


@router.post("/analyze-dictation")
async def analyze_dictation(req: AnalyzeDictationRequest, user: dict = Depends(require_user)):
    """听写错因分析（语义判断 + 错因分类）。"""
    scorer = get_llm_scorer()
    if not scorer.available:
        raise HTTPException(503, "LLM 服务不可用")
    return scorer.analyze_dictation_errors(
        expected=req.expected, actual=req.actual, word_matches=req.word_matches,
    )


@router.post("/diagnose-learning")
async def diagnose_learning(req: DiagnoseLearningRequest, user: dict = Depends(require_user)):
    """学习画像诊断（错误模式 + 弱项 + 提分路径）。"""
    scorer = get_llm_scorer()
    if not scorer.available:
        raise HTTPException(503, "LLM 服务不可用")
    return scorer.diagnose_learning_profile(
        user_stats=req.user_stats,
        recent_evaluations=req.recent_evaluations,
        error_phonemes=req.error_phonemes,
        error_words=req.error_words,
        weak_task_types=req.weak_task_types,
    )


@router.post("/explain-task")
async def explain_task(req: ExplainTaskRequest, user: dict = Depends(require_user)):
    """题目解析（考点 + 解题思路 + 干扰项分析）。"""
    scorer = get_llm_scorer()
    if not scorer.available:
        raise HTTPException(503, "LLM 服务不可用")
    return scorer.explain_task(
        task_type=req.task_type, prompt=req.prompt,
        expected_answer=req.expected_answer, options=req.options,
        correct_option=req.correct_option, keywords=req.keywords,
    )


@router.post("/chat")
async def chat(req: ChatRequest, user: dict = Depends(require_user)):
    """AI 助手对话（学生可问英语学习问题）。"""
    scorer = get_llm_scorer()
    if not scorer.available:
        raise HTTPException(503, "LLM 服务不可用")
    response = scorer.chat(req.message, req.context)
    return {"response": response, "user_id": user.get("id")}


@router.post("/dictation-semantic")
async def dictation_semantic(req: dict, user: dict = Depends(require_user)):
    """听写语义近似判断（旧接口）。"""
    scorer = get_llm_scorer()
    if not scorer.available:
        raise HTTPException(503, "LLM 服务不可用")
    return scorer.score_dictation_semantic(req.get("expected", ""), req.get("actual", ""))
