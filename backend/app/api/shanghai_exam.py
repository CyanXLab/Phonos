"""上海高考听说考试 API（按 2025 真实结构）。"""

from __future__ import annotations

import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.logging import get_logger
from .deps import get_current_user_v2, require_user
from ..services.shanghai_exam_service import (
    ExamMode,
    TaskType,
    get_shanghai_exam_service,
    DISCLAIMER,
    TASK_SCORES,
)


router = APIRouter(prefix="/api/shanghai-exam", tags=["shanghai_exam"])
logger = get_logger("shanghai_exam_api")


class CreateSessionRequest(BaseModel):
    mode: str = Field(default="practice")
    task_types: Optional[List[str]] = None
    task_count: int = 5
    full_exam: bool = Field(default=False, description="创建完整高考套卷（35分）")
    year: Optional[str] = Field(default=None, description="按年份/套卷创建（如 2025一模、2026秋考）")


class SubmitResponseRequest(BaseModel):
    task_id: str
    response: dict


@router.get("/task-types")
async def list_task_types():
    """列出所有题型（含真实分值与计时）。"""
    service = get_shanghai_exam_service()
    return {
        "task_types": service.list_task_types(),
        "total_full_score": 35.0,
        "structure": {
            "listening": {"full_score": 25.0, "sections": ["Section A 短文对话 10分", "Section B 短文/长对话 15分"]},
            "speaking": {"full_score": 10.0, "tasks": [
                "朗读句子 1分", "朗读短文 1分", "情景提问 2分",
                "看图作文 1.5分", "快速应答 2分", "简述与回答 2.5分",
            ]},
        },
        "disclaimer": DISCLAIMER,
    }


@router.get("/tasks")
async def list_tasks(
    task_type: Optional[str] = None,
    section: Optional[str] = None,
    difficulty: Optional[str] = None,
    year: Optional[str] = None,
    limit: int = 50,
    user: dict = Depends(require_user),
):
    service = get_shanghai_exam_service()
    tt = TaskType(task_type) if task_type else None
    return {"tasks": service.list_tasks(tt, section, difficulty, year, limit)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, user: dict = Depends(require_user)):
    service = get_shanghai_exam_service()
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    return task


@router.post("/sessions")
async def create_session(
    req: CreateSessionRequest,
    user: dict = Depends(require_user),
):
    """创建考试会话。full_exam=true 创建完整 35 分套卷。"""
    service = get_shanghai_exam_service()
    try:
        mode = ExamMode(req.mode)
    except ValueError:
        raise HTTPException(400, f"invalid mode: {req.mode}")

    if req.year:
        session = service.create_exam_by_year(user["id"], req.year, mode)
    elif req.full_exam:
        session = service.create_full_exam(user["id"], mode)
    else:
        task_types = None
        if req.task_types:
            try:
                task_types = [TaskType(t) for t in req.task_types]
            except ValueError as e:
                raise HTTPException(400, str(e))
        session = service.create_practice_session(user["id"], task_types, req.task_count)

    logger.info(
        "session_created",
        session_id=session.id,
        user_id=user["id"],
        mode=mode.value,
        task_count=len(session.tasks),
        full_exam=req.full_exam,
    )
    return {
        "session_id": session.id,
        "mode": session.mode.value,
        "tasks": [t.to_dict() for t in session.tasks],
        "started_at": session.started_at,
        "total_full_score": sum(t.full_score for t in session.tasks),
    }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user: dict = Depends(require_user)):
    service = get_shanghai_exam_service()
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    if session.user_id != user["id"]:
        raise HTTPException(403, "无权访问")
    return {
        "session_id": session.id,
        "mode": session.mode.value,
        "current_task_index": session.current_task_index,
        "tasks": [t.to_dict() for t in session.tasks],
        "started_at": session.started_at,
        "finished_at": session.finished_at,
        "responses_count": len(session.responses),
        "total_full_score": sum(t.full_score for t in session.tasks),
    }


@router.post("/sessions/{session_id}/submit")
async def submit_response(
    session_id: str,
    req: SubmitResponseRequest,
    user: dict = Depends(require_user),
):
    """提交单个任务作答。

    response 字段应包含：
    - score: 0-100（综合分）
    - feedback: 文字反馈
    - llm_scores: LLM 评分详情（口语部分）
    - audio_url: 录音 URL（可选）
    - selected_option: 选项 index（听力选择题）
    """
    service = get_shanghai_exam_service()
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    if session.user_id != user["id"]:
        raise HTTPException(403, "无权访问")
    if session.finished_at:
        raise HTTPException(400, "session 已结束")

    result = service.submit_response(session_id, req.task_id, req.response)
    session.current_task_index += 1
    return result


@router.post("/sessions/{session_id}/finish")
async def finish_session(session_id: str, user: dict = Depends(require_user)):
    service = get_shanghai_exam_service()
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    if session.user_id != user["id"]:
        raise HTTPException(403, "无权访问")
    service.finish_session(session_id)
    return {"ok": True, "finished_at": session.finished_at}


@router.get("/sessions/{session_id}/report")
async def get_report(session_id: str, user: dict = Depends(require_user)):
    """生成考试报告（35 分制）。"""
    service = get_shanghai_exam_service()
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    if session.user_id != user["id"]:
        raise HTTPException(403, "无权访问")
    if not session.finished_at:
        raise HTTPException(400, "session 尚未结束")

    report = service.generate_report(session_id)
    if not report:
        raise HTTPException(500, "report generation failed")
    return report.to_dict()


@router.get("/disclaimer")
async def get_disclaimer():
    """获取合规声明。"""
    return {"disclaimer": DISCLAIMER}


@router.get("/years")
async def list_years(user: dict = Depends(require_user)):
    """列出所有可用年份/套卷。"""
    service = get_shanghai_exam_service()
    years = service.list_years()
    # 统计每个年份的题数
    year_stats = {}
    for y in years:
        tasks = [t for t in service._corpus if y in t.year]
        year_stats[y] = {
            "count": len(tasks),
            "listening": len([t for t in tasks if t.section == "listening"]),
            "speaking": len([t for t in tasks if t.section == "speaking"]),
        }
    return {"years": years, "stats": year_stats}


@router.get("/structure")
async def get_exam_structure():
    """获取真实高考结构（2025 年起）。"""
    return {
        "total_score": 35,
        "total_duration_min": 35,
        "reform_year": "2025届起执行",
        "structure": {
            "listening": {
                "full_score": 25,
                "duration_min": 25,
                "sections": [
                    {"name": "Section A", "type": "短文对话选择", "score": 10},
                    {"name": "Section B", "type": "短文/长对话选择", "score": 15},
                ],
            },
            "speaking": {
                "full_score": 10,
                "duration_min": 10,
                "tasks": [
                    {"type": "朗读句子", "score": 1.0},
                    {"type": "朗读短文", "score": 1.0},
                    {"type": "情景提问", "score": 2.0},
                    {"type": "看图作文", "score": 1.5},
                    {"type": "快速应答", "score": 2.0},
                    {"type": "简述与回答", "score": 2.5},
                ],
            },
        },
        "scoring_method": "智能双评 + 人工仲裁",
        "exam_frequency": "一年两考（1月春考 + 6月秋考），取较高分",
        "disclaimer": DISCLAIMER,
        "sources": [
            "上海市教育考试院 2025 春考招生实施办法",
            "B站 2025.6 官方模拟试卷说明",
            "知乎 2026 秋考考生回忆",
            "百度百科 外语听说测试",
        ],
    }
