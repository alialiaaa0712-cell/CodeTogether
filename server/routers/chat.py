from __future__ import annotations

import subprocess
import threading
from typing import List, Optional, Set
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import ApiKey, Message as MessageModel, Session as SessionModel
from server.routers.auth import get_current_key
from server.schemas import MessageCreate, MessageOut

router = APIRouter(prefix="/chat", tags=["chat"])

_waking: Set[str] = set()
_waking_lock = threading.Lock()


def _wake_session(session_id: str, cwd: str, content: str) -> None:
    """
    在后台线程中通过 claude -p --resume 唤醒已停止的 session。

    使用 _waking 集合防止同一 session 并发启动多个唤醒进程；
    唤醒结束后自动从集合移除，允许下次唤醒。
    """
    with _waking_lock:
        if session_id in _waking:
            return
        _waking.add(session_id)

    def _run():
        try:
            subprocess.run(
                ["claude", "-p", "--resume", session_id, content],
                cwd=cwd or None,
                timeout=300,
            )
        except Exception:
            pass
        finally:
            with _waking_lock:
                _waking.discard(session_id)

    threading.Thread(target=_run, daemon=True).start()


@router.post("", response_model=MessageOut)
async def send_message(body: MessageCreate, request: Request, db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
    """写入手机端或 transcript 同步过来的消息，并按来源决定是否进入待注入队列。

    参数:
        body: 消息内容、角色、去重用 source_uuid 及可选原始时间戳。
        request: 当前请求对象，用于广播聊天消息事件。
        db: 数据库会话。

    返回值:
        新建或命中的消息对象；transcript 同步消息不会重新进入 pending 队列。
    """
    session = db.get(SessionModel, body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    if body.source_uuid:
        existing = db.query(MessageModel).filter(MessageModel.source_uuid == body.source_uuid).first()
        if existing:
            return existing
    is_transcript_sync = bool(body.source_uuid)
    initial_status = "delivered" if is_transcript_sync else "pending"
    msg = MessageModel(
        session_id=body.session_id,
        content=body.content,
        role=body.role,
        status=initial_status,
        source_uuid=body.source_uuid,
        created_at=body.created_at if body.created_at is not None else None,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    try:
        manager = request.app.state.ws_manager
        await manager.broadcast({
            "type": "chat_message",
            "data": {"session_id": msg.session_id, "role": msg.role},
        })
    except Exception:
        pass

    if session.status == "stopped" and not is_transcript_sync:
        msg.status = "delivered"
        db.commit()
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
