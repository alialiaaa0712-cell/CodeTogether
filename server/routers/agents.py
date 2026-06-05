from __future__ import annotations

import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import Session as SessionModel
from server.schemas import SessionCreate, SessionOut

router = APIRouter(prefix="/agents", tags=["agents"])


class StatusUpdate(BaseModel):
    status: str


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
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.status = body.status
    if body.status == "stopped":
        session.ended_at = time.time()
    db.commit()
    db.refresh(session)
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
