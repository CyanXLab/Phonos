"""LLM 评分 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .deps import require_user
from ..services.llm_scorer import get_llm_scorer


router = APIRouter(prefix="/api/llm", tags=["llm"])


class ScoreSpeakingRequest(BaseModel):
    task_type: str = Field(..., description="题型")
    prompt: str = Field(..., description="题目")
    expected_answer: str = Field(..., description="参考答案")
    user_response: str = Field(..., description="考生作答")
    keywords: list[str] = Field(default_factory=list)
    pronunciation_score: float | None = None
    fluency_score: float | None = None


@router.get("/health")
async def health(user: dict = Depends(require_user)):
    """LLM 服务健康检查。"""
    scorer = get_llm_scorer()
    return scorer.health()


@router.post("/score")
async def score_speaking(
    req: ScoreSpeakingRequest,
    user: dict = Depends(require_user),
):
    """评分口语应答。"""
    scorer = get_llm_scorer()
    if not scorer.available:
        raise HTTPException(503, "LLM 评分服务不可用，请配置 MODELSCOPE_API_KEY 或启动 llama.cpp")
    result = scorer.score_speaking_response(
        task_type=req.task_type,
        prompt=req.prompt,
        expected_answer=req.expected_answer,
        user_response=req.user_response,
        keywords=req.keywords,
        pronunciation_score=req.pronunciation_score,
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


@router.post("/dictation-semantic")
async def dictation_semantic(
    req: dict,
    user: dict = Depends(require_user),
):
    """听写语义近似判断。"""
    scorer = get_llm_scorer()
    if not scorer.available:
        raise HTTPException(503, "LLM 服务不可用")
    return scorer.score_dictation_semantic(req.get("expected", ""), req.get("actual", ""))
