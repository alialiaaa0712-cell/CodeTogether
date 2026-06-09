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
    """
    创建新记忆条目，默认状态为 pending，tier 为 short。

    参数:
        body: 记忆创建请求体。
        db: 数据库会话。

    返回值:
        创建后的记忆对象。
    """
    memory = MemoryModel(**body.model_dump())
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


@router.get("/search", response_model=List[MemoryOut])
def search_memories(q: str, project_id: Optional[str] = None, db: DBSession = Depends(get_db)):
    """
    搜索记忆：先返回 long+active，不足 3 条再补 short+active，合计最多 3 条。

    参数:
        q: 搜索关键词，匹配 title/content/tags。
        project_id: 可选项目 ID 过滤。
        db: 数据库会话。

    返回值:
        匹配的记忆列表，长期记忆优先。
    """
    def _query(tier: str):
        qr = db.query(MemoryModel).filter(
            MemoryModel.status == "active",
            MemoryModel.tier == tier,
        )
        if project_id:
            qr = qr.filter(MemoryModel.project_id == project_id)
        return qr.filter(
            or_(
                MemoryModel.title.contains(q),
                MemoryModel.content.contains(q),
                MemoryModel.tags.contains(q),
            )
        )

    results = _query("long").limit(3).all()
    if len(results) < 3:
        remaining = 3 - len(results)
        short_results = _query("short").limit(remaining).all()
        results = results + short_results
    return results


@router.get("", response_model=List[MemoryOut])
def list_memories(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    tier: Optional[str] = None,
    db: DBSession = Depends(get_db),
):
    """
    列出记忆，支持按 project_id、status、tier 过滤，最多返回 200 条。

    参数:
        project_id: 可选项目 ID 过滤。
        status: 可选状态过滤（pending/active/rejected/review）。
        tier: 可选层级过滤（short/long）。
        db: 数据库会话。

    返回值:
        按创建时间倒序的记忆列表。
    """
    q = db.query(MemoryModel)
    if project_id:
        q = q.filter(MemoryModel.project_id == project_id)
    if status:
        q = q.filter(MemoryModel.status == status)
    if tier:
        q = q.filter(MemoryModel.tier == tier)
    return q.order_by(MemoryModel.created_at.desc()).limit(200).all()


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_memory(memory_id: str, body: MemoryUpdate, db: DBSession = Depends(get_db)):
    """
    更新记忆状态或 tier：
    - tier=short：降级操作，将 review/long 改回 short/active
    - status：直接更新状态，active 时记录 activated_at
    - tier=long：仅升级 tier（通常由定时任务触发，此接口供测试使用）
    每次操作均更新 updated_at。

    参数:
        memory_id: 目标记忆 ID。
        body: 更新请求体（status 或 tier）。
        db: 数据库会话。

    返回值:
        更新后的记忆对象。
    """
    memory = db.get(MemoryModel, memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="memory not found")

    now = time.time()

    if body.tier == "short":
        # 降级：review/long → short/active
        memory.tier = "short"
        memory.status = "active"
        memory.updated_at = now
    elif body.status is not None:
        if body.status == "review" and memory.status != "active":
            raise HTTPException(status_code=422, detail="仅 active 状态的记忆可标记为 review")
        if body.status == "rejected":
            db.delete(memory)
            db.commit()
            return memory
        memory.status = body.status
        if body.status == "active":
            memory.activated_at = now
        memory.updated_at = now
    elif body.tier == "long":
        memory.tier = "long"
        memory.updated_at = now
    else:
        raise HTTPException(status_code=400, detail="请提供 status 或 tier 字段")

    db.commit()
    db.refresh(memory)
    return memory
