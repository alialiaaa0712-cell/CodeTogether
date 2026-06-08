from __future__ import annotations

import logging
import time
from typing import List, Literal, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import Session as SessionModel
from server.schemas import SessionCreate, SessionOut

router = APIRouter(prefix="/agents", tags=["agents"])


async def _broadcast_session_update(request: Request, session: SessionModel) -> None:
    """
    通过统一的 agent_update 消息广播最新会话快照，确保前后端字段结构一致。

    参数:
        request: 当前请求对象，用于读取应用上的 WebSocket 管理器。
        session: 已完成提交并刷新的会话 ORM 对象。

    返回值:
        无。
    """
    try:
        manager = request.app.state.ws_manager
        await manager.broadcast({
            "type": "agent_update",
            "data": SessionOut.model_validate(session).model_dump(),
        })
    except Exception as exc:
        logger.warning("Session WebSocket 广播失败: %s", exc)


class StatusUpdate(BaseModel):
    status: Literal["active", "stopped"]


class ParentUpdate(BaseModel):
    parent_id: Optional[str] = None


@router.post("", response_model=SessionOut)
async def create_session(body: SessionCreate, request: Request, db: DBSession = Depends(get_db)):
    """
    创建 Agent 会话，并在成功写库后向移动端广播最新会话数据。

    参数:
        body: 创建会话所需的字段。
        request: 当前请求对象，用于访问应用级 WebSocket 管理器。
        db: 数据库会话。

    返回值:
        创建后的会话对象；若会话已存在则返回现有记录。
    """
    existing = db.get(SessionModel, body.id)
    if existing:
        return existing
    session = SessionModel(**body.model_dump())
    db.add(session)
    db.commit()
    db.refresh(session)
    await _broadcast_session_update(request, session)
    return session


@router.get("", response_model=List[SessionOut])
def list_sessions(db: DBSession = Depends(get_db)):
    return db.query(SessionModel).all()


@router.patch("/{session_id}/status", response_model=SessionOut)
async def update_status(session_id: str, body: StatusUpdate, request: Request, db: DBSession = Depends(get_db)):
    """
    更新会话状态，并在状态变更后广播最新会话数据。

    参数:
        session_id: 目标会话 ID。
        body: 状态更新请求体。
        request: 当前请求对象，用于访问应用级 WebSocket 管理器。
        db: 数据库会话。

    返回值:
        更新后的会话对象。
    """
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.status = body.status
    if body.status == "stopped":
        session.ended_at = time.time()
    db.commit()
    db.refresh(session)
    await _broadcast_session_update(request, session)

    if body.status == "stopped":
        _trigger_extraction(session_id, session.project_id)

    return session


@router.patch("/{session_id}/parent", response_model=SessionOut)
async def update_parent(session_id: str, body: ParentUpdate, request: Request, db: DBSession = Depends(get_db)):
    """
    更新会话父子关系，并向前端广播最新会话数据。

    参数:
        session_id: 目标会话 ID。
        body: 父会话更新请求体。
        request: 当前请求对象，用于访问应用级 WebSocket 管理器。
        db: 数据库会话。

    返回值:
        更新后的会话对象。
    """
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.parent_id = body.parent_id
    db.commit()
    db.refresh(session)
    await _broadcast_session_update(request, session)
    return session


class ModelUpdate(BaseModel):
    model: str


class NotesUpdate(BaseModel):
    notes: str


@router.patch("/{session_id}/model", response_model=SessionOut)
async def update_model(session_id: str, body: ModelUpdate, request: Request, db: DBSession = Depends(get_db)):
    """
    更新会话模型名称，并向前端广播最新会话数据。

    参数:
        session_id: 目标会话 ID。
        body: 模型更新请求体。
        request: 当前请求对象，用于访问应用级 WebSocket 管理器。
        db: 数据库会话。

    返回值:
        更新后的会话对象。
    """
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.model = body.model
    db.commit()
    db.refresh(session)
    await _broadcast_session_update(request, session)
    return session


@router.patch("/{session_id}/notes", response_model=SessionOut)
async def update_notes(session_id: str, body: NotesUpdate, request: Request, db: DBSession = Depends(get_db)):
    """
    更新会话备注，并向前端广播最新会话数据。

    参数:
        session_id: 目标会话 ID。
        body: 备注更新请求体。
        request: 当前请求对象，用于访问应用级 WebSocket 管理器。
        db: 数据库会话。

    返回值:
        更新后的会话对象。
    """
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.notes = body.notes
    db.commit()
    db.refresh(session)
    await _broadcast_session_update(request, session)
    return session


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request, db: DBSession = Depends(get_db)):
    """
    删除指定会话及其关联的消息和事件记录。

    参数:
        session_id: 目标会话 ID。
        request: 当前请求对象，用于广播删除事件。
        db: 数据库会话。
    """
    from server.models import Message as MessageModel, Event as EventModel
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    db.query(MessageModel).filter(MessageModel.session_id == session_id).delete()
    db.query(EventModel).filter(EventModel.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    try:
        manager = request.app.state.ws_manager
        await manager.broadcast({"type": "agent_deleted", "data": {"id": session_id}})
    except Exception:
        pass



    """异步触发知识提炼，在后台线程中运行，不阻塞 HTTP 响应。"""
    import threading
    from server.services.extractor import extract_memories
    from server.models import Event as EventModel, Memory as MemoryModel
    from server.database import SessionLocal

    def _run():
        save_db = SessionLocal()
        try:
            recent_events = (
                save_db.query(EventModel)
                .filter(EventModel.session_id == session_id)
                .order_by(EventModel.created_at.asc())
                .limit(20)
                .all()
            )
            summary_lines = [
                f"{e.tool_name} input={str(e.input or '')[:100]} output={str(e.output or '')[:150]}"
                for e in recent_events
            ]
            summary = "\n".join(summary_lines)

            items = extract_memories(summary, project_id=project_id)

            for item in items:
                save_db.add(MemoryModel(
                    project_id=item.get("project_id"),
                    title=item["title"],
                    content=item["content"],
                    tags=item.get("tags"),
                    source_session_id=session_id,
                ))
            save_db.commit()
        except Exception as e:
            logger.warning("知识提炼后台任务失败: %s", e)
        finally:
            save_db.close()

    threading.Thread(target=_run, daemon=True).start()
