"""听写评分 v2 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .deps import get_current_user_v2
from ..services.dictation_v2 import evaluate_dictation_v2


router = APIRouter(prefix="/api/v2", tags=["dictation"])


class DictationCheckRequest(BaseModel):
    expected: str
    actual: str
    keywords: list[str] = Field(default_factory=list)


@router.post("/dictation/check")
async def check_dictation(
    req: DictationCheckRequest,
    user: dict = Depends(get_current_user_v2),
):
    """v2 听写评分：词级对齐 + 拼写容错 + 音近词 + 关键词权重。"""
    result = evaluate_dictation_v2(
        expected_text=req.expected,
        actual_text=req.actual,
        keywords=req.keywords,
    )
    return {
        "overall_score": result.overall_score,
        "summary": result.summary,
        "keywords_coverage": result.keywords_coverage,
        "tips": result.tips,
        "words": [
            {
                "expected": w.expected,
                "actual": w.actual,
                "match_type": w.match_type,
                "similarity": w.similarity,
                "expected_index": w.expected_index,
                "actual_index": w.actual_index,
                "is_keyword": w.is_keyword,
                "is_grammar_variant": w.is_grammar_variant,
                "is_phonetic_similar": w.is_phonetic_similar,
                "note": w.note,
            }
            for w in result.words
        ],
    }
