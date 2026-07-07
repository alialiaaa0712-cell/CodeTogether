from __future__ import annotations

import re
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import ApiKey
from server.models import Memory as MemoryModel
from server.models import MemoryFeedbackLog as MemoryFeedbackLogModel
from server.models import MemorySearchExposure as MemorySearchExposureModel
from server.models import Session as SessionModel
from server.routers.auth import get_current_key
from server.schemas import MemoryBatchDeleteRequest, MemoryCreate, MemoryFeedbackRequest, MemoryOut, MemorySearchRequest, MemoryUpdate

router = APIRouter(prefix="/memory", tags=["memory"])

_REVIEW_SCORE_THRESHOLD = 3
_DELETE_SCORE_THRESHOLD = -3
_EXPOSURE_TTL_SECONDS = 3600


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


def _tokenize_query(query: str) -> List[str]:
    """将搜索词切分为可用于记忆检索的 token 列表。

    参数:
        query: Agent 显式提供的搜索词。

    返回值:
        最多 10 个有效 token；若切分失败则退回原始 query。
    """
    tokens = [token for token in re.split(r"[\s/\-.,;:]+", query) if len(token) >= 2][:10]
    if tokens:
        return tokens
    stripped_query = query.strip()
    return [stripped_query] if stripped_query else []


def _query_memories(
    db: DBSession,
    query: str,
    project_id: Optional[str],
    tier: str,
    limit: int,
) -> List[MemoryModel]:
    """按 tier 查询命中的 active 记忆，并保持积分字段不变。

    参数:
        db: 数据库会话。
        query: 搜索词。
        project_id: 项目范围；为空时搜索全局记忆。
        tier: 目标层级，仅支持 short 或 long。
        limit: 本轮最多返回条数。

    返回值:
        匹配到的记忆列表。
    """
    tokens = _tokenize_query(query)
    if not tokens or limit <= 0:
        return []

    memory_query = db.query(MemoryModel).filter(
        MemoryModel.status == "active",
        MemoryModel.tier == tier,
    )
    if project_id:
        memory_query = memory_query.filter(MemoryModel.project_id == project_id)

    token_filters = []
    for token in tokens:
        tag_filter = MemoryModel.tags.contains(token)
        token_filters.append(or_(
            MemoryModel.title.contains(token),
            MemoryModel.content.contains(token),
            tag_filter,
        ))

    return (
        memory_query
        .filter(or_(*token_filters))
        .order_by(MemoryModel.score_total.desc(), MemoryModel.feedback_count.desc(), MemoryModel.updated_at.desc())
        .limit(limit)
        .all()
    )


def _record_search_exposures(
    db: DBSession,
    session_id: str,
    query: str,
    memories: List[MemoryModel],
    now: float,
) -> None:
    """记录当前会话本次搜索曝光，并清理过期曝光记录。

    参数:
        db: 数据库会话。
        session_id: 发起搜索的会话 ID。
        query: 本次搜索词。
        memories: 本次返回给 Agent 的记忆列表。
        now: 当前时间戳。

    返回值:
        无。
    """
    db.query(MemorySearchExposureModel).filter(
        MemorySearchExposureModel.session_id == session_id,
        MemorySearchExposureModel.exposed_at < now - _EXPOSURE_TTL_SECONDS,
    ).delete(synchronize_session=False)

    for memory in memories:
        db.add(MemorySearchExposureModel(
            memory_id=memory.id,
            session_id=session_id,
            query=query,
            exposed_at=now,
        ))


def _was_exposed_to_session(db: DBSession, session_id: str, memory_id: str, now: float) -> bool:
    """判断指定记忆是否曾在曝光有效期内返回给当前会话或其父/子会话。

    父子 session 共享曝光上下文：子 Agent 搜索到的记忆，父 Agent 可以反馈；反之亦然。

    参数:
        db: 数据库会话。
        session_id: 提交反馈的会话 ID。
        memory_id: 目标记忆 ID。
        now: 当前时间戳。

    返回值:
        若命中有效曝光记录则返回 True，否则返回 False。
    """
    session = db.get(SessionModel, session_id)
    # 收集需要检查的 session ID：自身 + 父 session + 所有子 session
    related_ids = {session_id}
    if session:
        if session.parent_id:
            related_ids.add(session.parent_id)
        child_ids = db.query(SessionModel.id).filter(SessionModel.parent_id == session_id).all()
        related_ids.update(row.id for row in child_ids)

    return db.query(MemorySearchExposureModel).filter(
        MemorySearchExposureModel.session_id.in_(related_ids),
        MemorySearchExposureModel.memory_id == memory_id,
        MemorySearchExposureModel.exposed_at >= now - _EXPOSURE_TTL_SECONDS,
    ).first() is not None


def _delete_memory_with_relations(db: DBSession, memory: MemoryModel) -> None:
    """删除记忆及其关联曝光、反馈记录，避免外键残留。

    参数:
        db: 数据库会话。
        memory: 目标记忆 ORM 对象。

    返回值:
        无。
    """
    db.query(MemoryFeedbackLogModel).filter(MemoryFeedbackLogModel.memory_id == memory.id).delete(synchronize_session=False)
    db.query(MemorySearchExposureModel).filter(MemorySearchExposureModel.memory_id == memory.id).delete(synchronize_session=False)
    db.delete(memory)


@router.post("", response_model=MemoryOut)
def create_memory(body: MemoryCreate, db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
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


@router.post("/search", response_model=List[MemoryOut])
def search_memories(body: MemorySearchRequest, db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
    """按 Agent 显式给出的 query 搜索记忆，并记录本次曝光。

    参数:
        body: 搜索请求体，包含 query、session_id 与返回条数上限。
        db: 数据库会话。

    返回值:
        命中的 active 记忆列表；优先返回长期记忆，再补足短期记忆。
    """
    resolved_project_id = _resolve_project_id(db, body.session_id, None)
    limit = max(1, min(body.limit, 10))

    long_memories = _query_memories(db, body.query, resolved_project_id, "long", limit)
    remaining = limit - len(long_memories)
    short_memories = _query_memories(db, body.query, resolved_project_id, "short", remaining)
    memories = long_memories + short_memories

    now = time.time()
    _record_search_exposures(db, body.session_id, body.query, memories, now)
    db.commit()
    return memories


@router.post("/{memory_id}/feedback", response_model=MemoryOut)
def submit_memory_feedback(memory_id: str, body: MemoryFeedbackRequest, db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
    """提交 Agent 对记忆的显式反馈，并按累计积分驱动状态流转。

    参数:
        memory_id: 目标记忆 ID。
        body: 反馈请求体，包含 session_id、score 与 reason。
        db: 数据库会话。

    返回值:
        更新后的记忆；若短期记忆达到负阈值则返回删除前快照。
    """
    memory = db.get(MemoryModel, memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="memory not found")

    now = time.time()
    if not _was_exposed_to_session(db, body.session_id, memory_id, now):
        raise HTTPException(status_code=400, detail="memory must be exposed before feedback")

    memory.score_total += body.score
    memory.feedback_count += 1
    memory.last_feedback_at = now
    memory.updated_at = now

    db.add(MemoryFeedbackLogModel(
        memory_id=memory.id,
        session_id=body.session_id,
        feedback=str(body.score),
        score_delta=body.score,
        reason=body.reason,
        created_at=now,
    ))

    if memory.tier == "short" and memory.score_total >= _REVIEW_SCORE_THRESHOLD:
        memory.status = "review"
        memory.review_reason = "score_threshold"
        memory.review_score = memory.score_total

    if memory.tier == "short" and memory.score_total <= _DELETE_SCORE_THRESHOLD:
        snapshot = MemoryOut.model_validate(memory)
        _delete_memory_with_relations(db, memory)
        db.commit()
        return snapshot

    db.commit()
    db.refresh(memory)
    return memory


@router.get("", response_model=List[MemoryOut])
def list_memories(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    tier: Optional[str] = None,
    db: DBSession = Depends(get_db),
    _key: Optional[ApiKey] = Depends(get_current_key),
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
def update_memory(memory_id: str, body: MemoryUpdate, db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
    """
    支持任意状态流转与 tier 更新，仅限合理路径（晋升为长期需满足条件）。

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

    if has_status:
        if body.status == "review":
            raise HTTPException(status_code=400, detail="review 状态由系统自动流转，不支持手动设置")
        if body.status == "active" and memory.status != "active":
            memory.activated_at = now
        memory.status = body.status
        memory.updated_at = now
    elif body.tier == "long":
        if memory.status != "review" or memory.tier != "short":
            raise HTTPException(status_code=422, detail="仅 review/short 记忆可晋升为长期")
        memory.tier = "long"
        memory.status = "active"
        memory.updated_at = now
    else:
        raise HTTPException(status_code=400, detail="仅支持更新 status 或将 review 短期记忆晋升为长期")

    db.commit()
    db.refresh(memory)
    return memory


@router.post("/batch-delete", status_code=204)
def batch_delete_memories(body: MemoryBatchDeleteRequest, db: DBSession = Depends(get_db)):
    """
    批量删除指定 ID 的记忆，不存在的 ID 静默跳过。

    参数:
        body: 包含 ids 列表的请求体。
        db: 数据库会话。

    返回值:
        无。
    """
    if not body.ids:
        return
    # 先确认哪些 ID 真实存在，避免删除不属于当前项目的记忆
    existing_ids = [
        row.id for row in db.query(MemoryModel.id).filter(MemoryModel.id.in_(body.ids)).all()
    ]
    if not existing_ids:
        return
    db.query(MemoryFeedbackLogModel).filter(MemoryFeedbackLogModel.memory_id.in_(existing_ids)).delete(synchronize_session=False)
    db.query(MemorySearchExposureModel).filter(MemorySearchExposureModel.memory_id.in_(existing_ids)).delete(synchronize_session=False)
    db.query(MemoryModel).filter(MemoryModel.id.in_(existing_ids)).delete(synchronize_session=False)
    db.commit()


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: str, db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
    """
    删除指定记忆及其关联曝光与反馈记录。

    参数:
        memory_id: 目标记忆 ID。
        db: 数据库会话。

    返回值:
        无。
    """
    memory = db.get(MemoryModel, memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="memory not found")

    _delete_memory_with_relations(db, memory)
    db.commit()

