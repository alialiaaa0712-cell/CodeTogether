from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import Message as MessageModel, Session as SessionModel
from server.schemas import MessageCreate, MessageOut

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=MessageOut)
def send_message(body: MessageCreate, db: DBSession = Depends(get_db)):
    """手机端发送消息，初始状态为 pending；会话不存在时返回 404。"""
    if not db.get(SessionModel, body.session_id):
        raise HTTPException(status_code=404, detail="session not found")
    msg = MessageModel(session_id=body.session_id, content=body.content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


@router.get("/{session_id}/poll", response_model=List[MessageOut])
def poll_messages(session_id: str, db: DBSession = Depends(get_db)):
    """PreToolUse hook 调用：原子性取走该会话所有 pending 消息，标记为 delivered。"""
    messages = (
        db.query(MessageModel)
        .filter(MessageModel.session_id == session_id, MessageModel.status == "pending")
        .with_for_update()
        .all()
    )
    for msg in messages:
        msg.status = "delivered"
    db.commit()
    return messages


@router.get("/{session_id}/history", response_model=List[MessageOut])
def message_history(session_id: str, db: DBSession = Depends(get_db)):
    return (
        db.query(MessageModel)
        .filter(MessageModel.session_id == session_id)
        .order_by(MessageModel.created_at.desc())
        .limit(100)
        .all()
    )
