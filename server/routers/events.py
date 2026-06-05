from __future__ import annotations

import json
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import Event as EventModel, Session as SessionModel
from server.schemas import EventCreate, EventOut

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventOut)
async def receive_event(body: EventCreate, request: Request, db: DBSession = Depends(get_db)):
    """接收 hook 上报的工具调用事件，会话不存在时自动创建。"""
    if not db.get(SessionModel, body.session_id):
        db.add(SessionModel(id=body.session_id))
        db.flush()

    input_str = json.dumps(body.input, ensure_ascii=False) if body.input else None
    event = EventModel(
        session_id=body.session_id,
        type=body.type,
        tool_name=body.tool_name,
        input=input_str,
        output=body.output,
        duration_ms=body.duration_ms,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    try:
        manager = request.app.state.ws_manager
        await manager.broadcast({
            "type": "event",
            "data": {
                "id": event.id,
                "session_id": event.session_id,
                "type": event.type,
                "tool_name": event.tool_name,
                "created_at": event.created_at,
            }
        })
    except Exception as exc:
        logging.getLogger(__name__).warning("WebSocket 广播失败: %s", exc)

    return event


@router.get("", response_model=List[EventOut])
def list_events(session_id: Optional[str] = None, db: DBSession = Depends(get_db)):
    q = db.query(EventModel).order_by(EventModel.created_at.desc())
    if session_id:
        q = q.filter(EventModel.session_id == session_id)
    return q.limit(500).all()
