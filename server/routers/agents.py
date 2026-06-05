from __future__ import annotations

import logging
import time
from typing import List, Literal, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import Session as SessionModel
from server.schemas import SessionCreate, SessionOut

router = APIRouter(prefix="/agents", tags=["agents"])


class StatusUpdate(BaseModel):
    status: Literal["active", "stopped"]


class ParentUpdate(BaseModel):
    parent_id: Optional[str] = None


@router.post("", response_model=SessionOut)
def create_session(body: SessionCreate, db: DBSession = Depends(get_db)):
    existing = db.get(SessionModel, body.id)
    if existing:
        return existing
    session = SessionModel(**body.model_dump())
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("", response_model=List[SessionOut])
def list_sessions(db: DBSession = Depends(get_db)):
    return db.query(SessionModel).all()


@router.patch("/{session_id}/status", response_model=SessionOut)
def update_status(session_id: str, body: StatusUpdate, db: DBSession = Depends(get_db)):
    """Stop hook 调用，将会话标记为 stopped；stopped 时异步触发知识提炼。"""
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.status = body.status
    if body.status == "stopped":
        session.ended_at = time.time()
    db.commit()
    db.refresh(session)

    if body.status == "stopped":
        _trigger_extraction(session_id, session.project_id)

    return session


@router.patch("/{session_id}/parent", response_model=SessionOut)
def update_parent(session_id: str, body: ParentUpdate, db: DBSession = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.parent_id = body.parent_id
    db.commit()
    db.refresh(session)
    return session


class ModelUpdate(BaseModel):
    model: str


class NotesUpdate(BaseModel):
    notes: str


@router.patch("/{session_id}/model", response_model=SessionOut)
def update_model(session_id: str, body: ModelUpdate, db: DBSession = Depends(get_db)):
    """SessionStart hook 上报模型名称。"""
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.model = body.model
    db.commit()
    db.refresh(session)
    return session


@router.patch("/{session_id}/notes", response_model=SessionOut)
def update_notes(session_id: str, body: NotesUpdate, db: DBSession = Depends(get_db)):
    """用户在 Dashboard 添加备注。"""
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.notes = body.notes
    db.commit()
    db.refresh(session)
    return session


def _trigger_extraction(session_id: str, project_id: Optional[str]) -> None:
    """异步触发知识提炼，在后台线程中运行，不阻塞 HTTP 响应。"""
    import asyncio
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
                .order_by(EventModel.created_at.desc())
                .limit(20)
                .all()
            )
            summary_lines = [f"{e.tool_name}: {(e.output or '')[:200]}" for e in recent_events]
            summary = "\n".join(summary_lines)

            loop = asyncio.new_event_loop()
            items = loop.run_until_complete(extract_memories(summary, project_id=project_id))
            loop.close()

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
