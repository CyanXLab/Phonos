"""上海听说考试 API。"""

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
)


router = APIRouter(prefix="/api/shanghai-exam", tags=["shanghai_exam"])
logger = get_logger("shanghai_exam_api")


class CreateSessionRequest(BaseModel):
    mode: str = Field(default="practice", description="practice / exam")
    task_ids: Optional[List[str]] = None
    task_types: Optional[List[str]] = None
    task_count: int = 5


class SubmitResponseRequest(BaseModel):
    task_id: str
    response: dict


@router.get("/task-types")
async def list_task_types():
    """列出所有任务类型。"""
    service = get_shanghai_exam_service()
    return {"task_types": service.list_task_types()}


@router.get("/tasks")
async def list_tasks(
    task_type: Optional[str] = None,
    difficulty: Optional[str] = None,
    topic: Optional[str] = None,
    cefr: Optional[str] = None,
    limit: int = 50,
    user: dict = Depends(require_user),
):
    """列出任务语料（需登录）。"""
    service = get_shanghai_exam_service()
    tt = TaskType(task_type) if task_type else None
    return {"tasks": service.list_tasks(tt, difficulty, topic, cefr, limit)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
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
    """创建考试会话。"""
    service = get_shanghai_exam_service()
    try:
        mode = ExamMode(req.mode)
    except ValueError:
        raise HTTPException(400, f"invalid mode: {req.mode}")

    task_types = None
    if req.task_types:
        try:
            task_types = [TaskType(t) for t in req.task_types]
        except ValueError as e:
            raise HTTPException(400, str(e))

    session = service.create_session(
        user_id=user["id"],
        mode=mode,
        task_ids=req.task_ids,
        task_types=task_types,
        task_count=req.task_count,
    )
    logger.info(
        "session_created",
        session_id=session.id,
        user_id=user["id"],
        mode=mode.value,
        task_count=len(session.tasks),
    )
    return {
        "session_id": session.id,
        "mode": session.mode.value,
        "tasks": [t.to_dict() for t in session.tasks],
        "started_at": session.started_at,
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
        "auto_submitted": session.auto_submitted,
        "responses_count": len(session.responses),
    }


@router.post("/sessions/{session_id}/submit")
async def submit_response(
    session_id: str,
    req: SubmitResponseRequest,
    user: dict = Depends(require_user),
):
    """提交单个任务作答。"""
    service = get_shanghai_exam_service()
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    if session.user_id != user["id"]:
        raise HTTPException(403, "无权访问")
    if session.finished_at:
        raise HTTPException(400, "session 已结束")

    result = service.submit_response(session_id, req.task_id, req.response)
    # 推进任务指针
    session.current_task_index += 1
    return result


@router.post("/sessions/{session_id}/finish")
async def finish_session(session_id: str, user: dict = Depends(require_user)):
    """手动结束会话。"""
    service = get_shanghai_exam_service()
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    if session.user_id != user["id"]:
        raise HTTPException(403, "无权访问")
    session.finished_at = time.time()
    return {"ok": True, "finished_at": session.finished_at}


@router.get("/sessions/{session_id}/report")
async def get_report(session_id: str, user: dict = Depends(require_user)):
    """生成考试报告。"""
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
