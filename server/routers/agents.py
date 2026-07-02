from __future__ import annotations

import logging
import threading
import time
from pathlib import PurePath
from typing import List, Literal, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from server.database import SessionLocal, get_db
from server.models import ApiKey
from server.models import Event as EventModel
from server.models import Memory as MemoryModel
from server.models import Message as MessageModel
from server.models import Project as ProjectModel
from server.models import Session as SessionModel
from server.routers.auth import get_current_key
from server.schemas import SessionCreate, SessionOut
from server.services.extractor import extract_memories

router = APIRouter(prefix="/agents", tags=["agents"])


def _normalize_project_cwd(cwd: str) -> Optional[str]:
    """
    将会话 cwd 规范化为可稳定匹配项目的路径标识。

    参数:
        cwd: 原始工作目录路径。

    返回值:
        规范化后的完整路径；若路径为空则返回 None。
    """
    normalized_cwd = str(PurePath(cwd)).strip()
    if not normalized_cwd:
        return None
    return normalized_cwd


def _ensure_project_for_cwd(cwd: Optional[str], db: DBSession) -> Optional[str]:
    """
    根据 cwd 解析并确保项目存在，供会话创建和历史补齐链路复用。

    参数:
        cwd: 会话工作目录，允许为空。
        db: 数据库会话，用于查询或创建项目记录。

    返回值:
        若可确定项目则返回 project_id；否则返回 None。
    """
    if not cwd:
        return None

    normalized_cwd = _normalize_project_cwd(cwd)
    if not normalized_cwd:
        return None

    project_name = PurePath(normalized_cwd).name.strip()
    if not project_name:
        return None

    existing_project = db.query(ProjectModel).filter(ProjectModel.repo_url == normalized_cwd).first()
    if existing_project:
        return existing_project.id

    project = ProjectModel(name=project_name, repo_url=normalized_cwd)
    db.add(project)
    db.flush()
    return project.id


def _ensure_project_for_repo_url(repo_url: str, db: DBSession) -> Optional[str]:
    """
    按 git remote URL 精确匹配项目，未命中时自动创建。

    参数:
        repo_url: git remote origin URL，作为全局唯一项目键。
        db: 数据库会话。

    返回值:
        project_id 字符串。
    """
    repo_url = repo_url.strip()
    existing = db.query(ProjectModel).filter(ProjectModel.repo_url == repo_url).first()
    if existing:
        return existing.id
    # 取 URL 最后一段作为项目名，去掉 .git 后缀
    stem = PurePath(repo_url.rstrip("/")).name
    name = stem[:-4] if stem.endswith(".git") else stem
    name = name or repo_url
    project = ProjectModel(name=name, repo_url=repo_url)
    db.add(project)
    db.flush()
    return project.id


def _ensure_project_for_session(body: SessionCreate, db: DBSession) -> Optional[str]:
    """
    为会话解析 project_id：优先按 repo_url 精确匹配，无则按 cwd 回退。

    参数:
        body: 创建会话请求体。
        db: 数据库会话。

    返回值:
        project_id 字符串，或 None。
    """
    if body.project_id:
        return body.project_id
    if body.repo_url:
        return _ensure_project_for_repo_url(body.repo_url, db)
    return _ensure_project_for_cwd(body.cwd, db)


async def _broadcast_session_update(session: SessionModel) -> None:
    """
    广播最新会话快照给所有连接的手机端。

    参数:
        session: 已完成提交并刷新的会话 ORM 对象。

    返回值:
        无。
    """
    try:
        from server import broadcast
        await broadcast.publish({
            "type": "agent_update",
            "data": SessionOut.model_validate(session).model_dump(),
        })
    except Exception as exc:
        logger.warning("Session WebSocket 广播失败: %s", exc)


class StatusUpdate(BaseModel):
    status: Literal["active", "stopped"]


class ParentUpdate(BaseModel):
    parent_id: Optional[str] = None


@router.post("", response_model=SessionOut)
async def create_session(body: SessionCreate, request: Request, db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
    """
    创建 Agent 会话，并在成功写库后向移动端广播最新会话数据。

    参数:
        body: 创建会话所需的字段。
        request: 当前请求对象，用于访问应用级 WebSocket 管理器。
        db: 数据库会话。

    返回值:
        创建后的会话对象；若会话已存在则返回现有记录。
    """
    existing = db.get(SessionModel, body.id)
    if existing:
        changed = False
        if body.cwd and not existing.cwd:
            existing.cwd = body.cwd
            changed = True
        if body.cwd and not existing.project_id:
            existing.project_id = _ensure_project_for_session(body, db)
            changed = True
        if changed:
            db.commit()
            db.refresh(existing)
        return existing

    project_id = _ensure_project_for_session(body, db)
    session_payload = body.model_dump(exclude={"project_id", "repo_url"})
    session = SessionModel(**session_payload, project_id=project_id, user_label=_key.label if _key else None)
    db.add(session)
    db.commit()
    db.refresh(session)
    await _broadcast_session_update(session)
    return session


@router.get("", response_model=List[SessionOut])
def list_sessions(db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
    return db.query(SessionModel).all()


@router.patch("/{session_id}/status", response_model=SessionOut)
async def update_status(session_id: str, body: StatusUpdate, request: Request, db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
    """
    更新会话状态，并在状态变更后广播最新会话数据。

    参数:
        session_id: 目标会话 ID。
        body: 状态更新请求体。
        request: 当前请求对象，用于访问应用级 WebSocket 管理器。
        db: 数据库会话。

    返回值:
        更新后的会话对象。
    """
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.status = body.status
    if body.status == "stopped":
        session.ended_at = time.time()
    db.commit()
    db.refresh(session)
    await _broadcast_session_update(session)

    if body.status == "stopped":
        pass  # 记忆由 Claude 通过 memory_create MCP 工具主动创建，不再自动提炼

    return session


@router.patch("/{session_id}/parent", response_model=SessionOut)
async def update_parent(session_id: str, body: ParentUpdate, request: Request, db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
    """
    更新会话父子关系，并向前端广播最新会话数据。

    参数:
        session_id: 目标会话 ID。
        body: 父会话更新请求体。
        request: 当前请求对象，用于访问应用级 WebSocket 管理器。
        db: 数据库会话。

    返回值:
        更新后的会话对象。
    """
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.parent_id = body.parent_id
    db.commit()
    db.refresh(session)
    await _broadcast_session_update(session)
    return session


class ModelUpdate(BaseModel):
    model: str


class NotesUpdate(BaseModel):
    notes: str


@router.patch("/{session_id}/model", response_model=SessionOut)
async def update_model(session_id: str, body: ModelUpdate, request: Request, db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
    """
    更新会话模型名称，并向前端广播最新会话数据。

    参数:
        session_id: 目标会话 ID。
        body: 模型更新请求体。
        request: 当前请求对象，用于访问应用级 WebSocket 管理器。
        db: 数据库会话。

    返回值:
        更新后的会话对象。
    """
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.model = body.model
    db.commit()
    db.refresh(session)
    await _broadcast_session_update(session)
    return session


@router.patch("/{session_id}/notes", response_model=SessionOut)
async def update_notes(session_id: str, body: NotesUpdate, request: Request, db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
    """
    更新会话备注，并向前端广播最新会话数据。

    参数:
        session_id: 目标会话 ID。
        body: 备注更新请求体。
        request: 当前请求对象，用于访问应用级 WebSocket 管理器。
        db: 数据库会话。

    返回值:
        更新后的会话对象。
    """
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.notes = body.notes
    db.commit()
    db.refresh(session)
    await _broadcast_session_update(session)
    return session


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request, db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
    """
    删除指定会话及其关联的消息和事件记录。

    参数:
        session_id: 目标会话 ID。
        request: 当前请求对象，用于广播删除事件。
        db: 数据库会话。
    """
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    db.query(MessageModel).filter(MessageModel.session_id == session_id).delete()
    db.query(EventModel).filter(EventModel.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    try:
        from server import broadcast
        await broadcast.publish({"type": "agent_deleted", "data": {"id": session_id}})
    except Exception:
        pass


def _trigger_extraction(session_id: str, project_id: Optional[str]) -> None:
    """
    异步触发知识提炼，优先从聊天消息中提炼结论，并直接启用自动提炼出的短期记忆。

    参数:
        session_id: 触发提炼的会话 ID。
        project_id: 调用方已知的项目 ID；为空时会回退到 session 自身归属或 cwd 推导结果。

    返回值:
        无返回值；实际提炼与落库工作在后台线程中完成。
    """

    def _run():
        save_db = SessionLocal()
        try:
            recent_messages = (
                save_db.query(MessageModel)
                .filter(MessageModel.session_id == session_id)
                .order_by(MessageModel.created_at.desc())
                .limit(12)
                .all()
            )
            recent_messages = list(reversed(recent_messages))
            summary_lines = [
                f"{message.role}: {message.content[:200]}"
                for message in recent_messages
                if message.content and message.content.strip()
            ]
            if not summary_lines:
                recent_events = (
                    save_db.query(EventModel)
                    .filter(EventModel.session_id == session_id)
                    .order_by(EventModel.created_at.asc())
                    .limit(10)
                    .all()
                )
                summary_lines = [
                    f"{event.tool_name} input={str(event.input or '')[:80]} output={str(event.output or '')[:120]}"
                    for event in recent_events
                ]
            summary = "\n".join(summary_lines)

            session = save_db.get(SessionModel, session_id)
            resolved_project_id = project_id or (session.project_id if session else None)
            if session and not resolved_project_id:
                resolved_project_id = _ensure_project_for_cwd(session.cwd, save_db)
                if resolved_project_id and not session.project_id:
                    session.project_id = resolved_project_id

            items = extract_memories(summary, project_id=resolved_project_id)
            now = time.time()

            for item in items[:3]:
                save_db.add(MemoryModel(
                    project_id=resolved_project_id,
                    title=item["title"],
                    content=item["content"],
                    tags=item.get("tags"),
                    source_session_id=session_id,
                    status="active",
                    tier="short",
                    updated_at=now,
                    activated_at=now,
                ))
            save_db.commit()
        except Exception as e:
            logger.warning("知识提炼后台任务失败: %s", e)
        finally:
            save_db.close()

    threading.Thread(target=_run, daemon=True).start()
