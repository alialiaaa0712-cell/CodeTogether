from __future__ import annotations

import json
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import Event as EventModel, Session as SessionModel
from server.routers.auth import get_current_key
from server.schemas import EventCreate, EventOut, SessionOut

router = APIRouter(prefix="/events", tags=["events"])


async def _broadcast_session_update(request: Request, session: SessionModel) -> None:
    """
    在事件导致会话首次出现时同步广播会话快照，避免移动端状态页漏掉新会话。

    参数:
        request: 当前请求对象，用于访问应用级 WebSocket 管理器。
        session: 需要广播的会话 ORM 对象。

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
        logging.getLogger(__name__).warning("Session WebSocket 广播失败: %s", exc)


@router.post("", response_model=EventOut)
async def receive_event(
    body: EventCreate,
    request: Request,
    db: DBSession = Depends(get_db),
    _key=Depends(get_current_key),
):
    """
    接收 hook 上报的工具调用事件；若会话首次出现，则先创建并广播会话快照，再广播事件本身。
    若事件携带 parent_session_id，同时回写子 Session 的 parent_id（首次写入时）。
    需要有效的 Bearer Token 才能写入。

    参数:
        body: 事件上报请求体。
        request: 当前请求对象，用于访问应用级 WebSocket 管理器。
        db: 数据库会话。

    返回值:
        创建后的事件对象。
    """
    created_session = None
    updated_session = None
    if not db.get(SessionModel, body.session_id):
        created_session = SessionModel(
            id=body.session_id,
            parent_id=body.parent_session_id,
        )
        db.add(created_session)
        db.flush()
    elif body.parent_session_id:
        session = db.get(SessionModel, body.session_id)
        if session and not session.parent_id:
            session.parent_id = body.parent_session_id
            updated_session = session

    input_str = json.dumps(body.input, ensure_ascii=False) if body.input else None
    event = EventModel(
        session_id=body.session_id,
        type=body.type,
        tool_name=body.tool_name,
        tool_use_id=body.tool_use_id,
        input=input_str,
        output=body.output,
        duration_ms=body.duration_ms,
        parent_session_id=body.parent_session_id,
    )
    db.add(event)
    db.commit()
    if created_session is not None:
        db.refresh(created_session)
    if updated_session is not None:
        db.refresh(updated_session)
    db.refresh(event)

    if created_session is not None:
        await _broadcast_session_update(request, created_session)
    elif updated_session is not None:
        await _broadcast_session_update(request, updated_session)

    try:
        manager = request.app.state.ws_manager
        await manager.broadcast({
            "type": "event",
            "data": EventOut.model_validate(event).model_dump(),
        })
    except Exception as exc:
        logging.getLogger(__name__).warning("WebSocket 广播失败: %s", exc)

    return event


@router.get("", response_model=List[EventOut])
def list_events(session_id: Optional[str] = None, include_children: bool = False, db: DBSession = Depends(get_db)):
    """
    列出事件；include_children=true 时同时包含所有子 Agent 的事件。

    参数:
        session_id: 可选，按会话 ID 过滤。
        include_children: 为 true 时，同时返回 parent_session_id=session_id 的子事件。
        db: 数据库会话。
    """
    q = db.query(EventModel).order_by(EventModel.created_at.desc())
    if session_id:
        if include_children:
            from sqlalchemy import or_
            q = q.filter(or_(
                EventModel.session_id == session_id,
                EventModel.parent_session_id == session_id,
            ))
        else:
            q = q.filter(EventModel.session_id == session_id)
    return q.limit(500).all()
