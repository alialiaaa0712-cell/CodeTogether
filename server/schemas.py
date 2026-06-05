from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict


# 会话相关 schemas
class SessionCreate(BaseModel):
    id: str
    project_id: Optional[str] = None
    parent_id: Optional[str] = None
    cwd: Optional[str] = None
    model: Optional[str] = None


class SessionOut(BaseModel):
    id: str
    project_id: Optional[str] = None
    parent_id: Optional[str] = None
    status: str
    cwd: Optional[str] = None
    model: Optional[str] = None
    notes: Optional[str] = None
    started_at: float
    ended_at: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


# 事件相关 schemas
class EventCreate(BaseModel):
    session_id: str
    type: str
    tool_name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None  # ORM 存 JSON 字符串，路由层负责转换
    output: Optional[str] = None
    duration_ms: Optional[int] = None


class EventOut(BaseModel):
    id: str
    session_id: str
    type: str
    tool_name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None  # ORM 存 JSON 字符串，路由层负责转换
    output: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: float

    model_config = ConfigDict(from_attributes=True)


# 消息相关 schemas
class MessageCreate(BaseModel):
    session_id: str
    content: str


class MessageOut(BaseModel):
    id: str
    session_id: str
    content: str
    status: str
    created_at: float

    model_config = ConfigDict(from_attributes=True)


# 记忆相关 schemas
class MemoryCreate(BaseModel):
    project_id: Optional[str] = None
    title: str
    content: str
    tags: Optional[str] = None
    source_session_id: Optional[str] = None


class MemoryOut(BaseModel):
    id: str
    project_id: Optional[str] = None
    title: str
    content: str
    tags: Optional[str] = None
    status: str
    source_session_id: Optional[str] = None
    created_at: float
    activated_at: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class MemoryUpdate(BaseModel):
    status: str  # "active" | "rejected"
