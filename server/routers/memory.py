from __future__ import annotations

import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import Memory as MemoryModel
from server.schemas import MemoryCreate, MemoryOut, MemoryUpdate

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("", response_model=MemoryOut)
def create_memory(body: MemoryCreate, db: DBSession = Depends(get_db)):
    memory = MemoryModel(**body.model_dump())
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


@router.get("/search", response_model=List[MemoryOut])
def search_memories(q: str, project_id: Optional[str] = None, db: DBSession = Depends(get_db)):
    query = db.query(MemoryModel).filter(MemoryModel.status == "active")
    if project_id:
        query = query.filter(MemoryModel.project_id == project_id)
    query = query.filter(
        or_(
            MemoryModel.content.contains(q),
            MemoryModel.tags.contains(q),
            MemoryModel.title.contains(q),
        )
    )
    return query.limit(3).all()


@router.get("", response_model=List[MemoryOut])
def list_memories(project_id: Optional[str] = None, status: Optional[str] = None, db: DBSession = Depends(get_db)):
    q = db.query(MemoryModel)
    if project_id:
        q = q.filter(MemoryModel.project_id == project_id)
    if status:
        q = q.filter(MemoryModel.status == status)
    return q.order_by(MemoryModel.created_at.desc()).limit(200).all()


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_memory(memory_id: str, body: MemoryUpdate, db: DBSession = Depends(get_db)):
    memory = db.get(MemoryModel, memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="memory not found")
    memory.status = body.status
    if body.status == "active":
        memory.activated_at = time.time()
    db.commit()
    db.refresh(memory)
    return memory
