from __future__ import annotations

import json
from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import Event as EventModel, Session as SessionModel
from server.schemas import EventCreate, EventOut

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventOut)
def receive_event(body: EventCreate, db: DBSession = Depends(get_db)):
    """接收 hook 上报的工具调用事件，会话不存在时自动创建。"""
    if not db.get(SessionModel, body.session_id):
        db.add(SessionModel(id=body.session_id))
        db.flush()  # 分配 PK，不提交

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
    return event


@router.get("", response_model=List[EventOut])
def list_events(session_id: Optional[str] = None, db: DBSession = Depends(get_db)):
    q = db.query(EventModel).order_by(EventModel.created_at.desc())
    if session_id:
        q = q.filter(EventModel.session_id == session_id)
    return q.limit(500).all()
