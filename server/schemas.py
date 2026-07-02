from __future__ import annotations

from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


# 会话相关 schemas
class SessionCreate(BaseModel):
    id: str
    project_id: Optional[str] = None
    parent_id: Optional[str] = None
    cwd: Optional[str] = None
    model: Optional[str] = None
    repo_url: Optional[str] = None


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
    user_label: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# 事件相关 schemas
class EventCreate(BaseModel):
    session_id: str
    type: str
    tool_name: Optional[str] = None
    tool_use_id: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    output: Optional[str] = None
    duration_ms: Optional[int] = None
    parent_session_id: Optional[str] = None


class EventOut(BaseModel):
    id: str
    session_id: str
    type: str
    tool_name: Optional[str] = None
    tool_use_id: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    output: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: float
    parent_session_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def parse_input(cls, data: Any) -> Any:
        """ORM 层 input 存为 JSON 字符串，在 schema 层解析为 dict。"""
        import json
        if hasattr(data, "input") and isinstance(data.input, str):
            try:
                object.__setattr__(data, "input", json.loads(data.input))
            except Exception:
                pass
        elif isinstance(data, dict) and isinstance(data.get("input"), str):
            try:
                data["input"] = json.loads(data["input"])
            except Exception:
                pass
        return data


# 消息相关 schemas
class MessageCreate(BaseModel):
    session_id: str
    content: str
    role: str = "user"
    source_uuid: Optional[str] = None
    created_at: Optional[float] = None


class MessageOut(BaseModel):
    id: str
    session_id: str
    content: str
    role: str
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


class MemoryBatchDeleteRequest(BaseModel):
    ids: list[str] = Field(..., max_length=500)


class MemorySearchRequest(BaseModel):
    query: str
    session_id: str
    limit: int = 3


class MemoryFeedbackRequest(BaseModel):
    session_id: str
    score: Literal[-2, -1, 0, 1, 2]
    reason: str


class MemoryOut(BaseModel):
    id: str
    project_id: Optional[str] = None
    title: str
    content: str
    tags: Optional[str] = None
    status: str
    tier: str
    source_session_id: Optional[str] = None
    created_at: float
    activated_at: Optional[float] = None
    updated_at: float
    score_total: int
    feedback_count: int
    last_feedback_at: Optional[float] = None
    review_score: Optional[int] = None
    review_reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class MemoryUpdate(BaseModel):
    status: Optional[Literal["active", "rejected", "review"]] = None
    tier: Optional[Literal["short", "long"]] = None


class ApiKeyCreate(BaseModel):
    label: str = Field(..., max_length=128)
    is_admin: bool = False


class ApiKeyOut(BaseModel):
    id: str
    label: str
    is_admin: bool
    is_active: bool
    created_at: float

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def coerce_bools(cls, data: Any) -> Any:
        """SQLite 将 BOOL 存为 0/1 整数，统一转为 Python bool。"""
        if hasattr(data, "is_admin"):
            object.__setattr__(data, "is_admin", bool(data.is_admin))
            object.__setattr__(data, "is_active", bool(data.is_active))
        elif isinstance(data, dict):
            if "is_admin" in data:
                data["is_admin"] = bool(data["is_admin"])
            if "is_active" in data:
                data["is_active"] = bool(data["is_active"])
        return data
