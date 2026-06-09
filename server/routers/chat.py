from __future__ import annotations

import subprocess
import threading
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import Message as MessageModel, Session as SessionModel
from server.schemas import MessageCreate, MessageOut

router = APIRouter(prefix="/chat", tags=["chat"])


def _wake_session(session_id: str, cwd: str, content: str) -> None:
    """
    在后台线程中通过 claude -p --resume 唤醒已停止的 session。

    Claude 完成后 Stop hook 会自动同步消息并检查下一条 pending 消息，
    无需在此处处理输出。
    """
    def _run():
        try:
            subprocess.run(
                ["claude", "-p", "--resume", session_id, content],
                cwd=cwd or None,
                timeout=300,
            )
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


@router.post("", response_model=MessageOut)
def send_message(body: MessageCreate, db: DBSession = Depends(get_db)):
    """手机端发送消息，初始状态为 pending；会话不存在时返回 404。source_uuid 用于去重。
    若会话已停止，后台唤醒 claude --resume 让其处理消息。"""
    session = db.get(SessionModel, body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    if body.source_uuid:
        existing = db.query(MessageModel).filter(MessageModel.source_uuid == body.source_uuid).first()
        if existing:
            return existing
    msg = MessageModel(
        session_id=body.session_id,
        content=body.content,
        role=body.role,
        source_uuid=body.source_uuid,
        created_at=body.created_at if body.created_at is not None else None,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    if session.status == "stopped":
        _wake_session(body.session_id, session.cwd or "", body.content)

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
    """
    返回指定会话最近的聊天历史，供移动端渲染消息列表。

    参数:
        session_id: 目标会话 ID。
        db: 数据库会话。

    返回值:
        按创建时间倒序排列的最近 100 条消息。
    """
    return (
        db.query(MessageModel)
        .filter(MessageModel.session_id == session_id)
        .order_by(MessageModel.created_at.desc())
        .limit(100)
        .all()
    )
