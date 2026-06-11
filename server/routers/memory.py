from __future__ import annotations

import re
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import Memory as MemoryModel
from server.models import Session as SessionModel
from server.schemas import MemoryCreate, MemoryOut, MemoryUpdate

router = APIRouter(prefix="/memory", tags=["memory"])

_REVIEW_HIT_THRESHOLD = 3
_7_DAYS = 7 * 86400


def _resolve_project_id(
    db: DBSession,
    session_id: Optional[str],
    fallback_project_id: Optional[str],
) -> Optional[str]:
    """
    优先根据 session_id 解析所属项目，仅当会话没有项目时才回退到显式 project_id。

    参数:
        db: 数据库会话。
        session_id: 调用方传入的会话 ID。
        fallback_project_id: 调用方传入的项目回退值。

    返回值:
        解析出的项目 ID；若两者都不可用则返回 None。
    """
    if session_id:
        session = db.get(SessionModel, session_id)
        if session and session.project_id:
            return session.project_id
    return fallback_project_id


def _bump_short_memory_hit(memory: MemoryModel, now: float) -> None:
    """
    更新短期活跃记忆的 7 天命中统计，并在达到阈值后转入 review。

    参数:
        memory: 本次命中的记忆对象。
        now: 当前时间戳。

    返回值:
        无。
    """
    if memory.last_hit_at is None or now - memory.last_hit_at > _7_DAYS:
        memory.hit_count_7d = 1
    else:
        memory.hit_count_7d += 1

    memory.last_hit_at = now
    memory.updated_at = now

    if memory.hit_count_7d >= _REVIEW_HIT_THRESHOLD:
        memory.status = "review"
        memory.review_reason = "hit_threshold"
        memory.review_hit_count = memory.hit_count_7d


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
def search_memories(
    q: str,
    project_id: Optional[str] = None,
    session_id: Optional[str] = None,
    db: DBSession = Depends(get_db),
):
    """
    搜索记忆：先返回 long+active，不足 3 条再补 short+active，合计最多 3 条。

    参数:
        q: 搜索关键词，匹配 title/content/tags。
        project_id: 可选项目 ID 过滤。
        session_id: 可选会话 ID，用于优先解析当前项目范围。
        db: 数据库会话。

    返回值:
        匹配的记忆列表，长期记忆优先。
    """
    resolved_project_id = _resolve_project_id(db, session_id, project_id)

    def _query(tier: str):
        qr = db.query(MemoryModel).filter(
            MemoryModel.status == "active",
            MemoryModel.tier == tier,
        )
        if resolved_project_id:
            qr = qr.filter(MemoryModel.project_id == resolved_project_id)
        # 按空格/标点拆词，任意一个词命中 title/content/tags 即匹配
        tokens = [t for t in re.split(r"[\s/\-.,;:]+", q) if len(t) >= 2][:10]
        if not tokens:
            tokens = [q]
        word_conds = [
            or_(
                MemoryModel.title.contains(t),
                MemoryModel.content.contains(t),
                MemoryModel.tags.contains(t),
            )
            for t in tokens
        ]
        return qr.filter(or_(*word_conds))

    results = _query("long").limit(3).all()
    remaining = 3 - len(results)
    now = time.time()
    changed = False

    if remaining > 0:
        short_results = []
        for memory in _query("short").all():
            if len(short_results) >= remaining:
                break
            _bump_short_memory_hit(memory, now)
            changed = True
            if memory.status == "active":
                short_results.append(memory)
        results = results + short_results

    if changed:
        db.commit()
        for memory in results:
            db.refresh(memory)

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
    仅支持两类人工确认流转：pending 启用为短期记忆，或 review 短期记忆晋升为长期记忆。

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
    has_status = body.status is not None
    has_tier = body.tier is not None

    if has_status == has_tier:
        raise HTTPException(status_code=400, detail="必须且只能更新 status 或 tier 其中一个字段")

    if body.status == "active":
        if memory.status != "pending":
            raise HTTPException(status_code=422, detail="仅 pending 记忆可启用")
        memory.status = "active"
        memory.activated_at = now
        memory.updated_at = now
    elif body.tier == "long":
        if memory.status != "review" or memory.tier != "short":
            raise HTTPException(status_code=422, detail="仅 review/short 记忆可晋升为长期")
        memory.tier = "long"
        memory.status = "active"
        memory.updated_at = now
    else:
        raise HTTPException(status_code=400, detail="仅支持启用短期记忆或将 review 短期记忆晋升为长期")

    db.commit()
    db.refresh(memory)
    return memory


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: str, db: DBSession = Depends(get_db)):
    """
    删除指定记忆，用于拒绝 pending 或 review 记忆。

    参数:
        memory_id: 目标记忆 ID。
        db: 数据库会话。

    返回值:
        无。
    """
    memory = db.get(MemoryModel, memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="memory not found")

    db.delete(memory)
    db.commit()
