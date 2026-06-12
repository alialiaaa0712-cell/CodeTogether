from __future__ import annotations

import time
import uuid

from sqlalchemy import BigInteger, Column, Double, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from server.database import Base


def _uuid() -> str:
    """生成主键使用的 UUID 字符串。

    参数:
        无。

    返回值:
        新生成的 UUID 字符串。
    """
    return str(uuid.uuid4())


class Project(Base):
    """项目表：多个 Agent 会话归属于同一项目。"""
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    repo_url = Column(String(512))
    created_at = Column(Double, default=time.time)

    sessions = relationship("Session", back_populates="project")
    memories = relationship("Memory", back_populates="project")


class Session(Base):
    """Agent 会话表：记录每次 Claude Code Agent 的运行。"""
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    parent_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    status = Column(Enum("active", "stopped"), default="active")
    cwd = Column(String(512))
    model = Column(String(128))
    notes = Column(Text)
    user_label = Column(String(128), nullable=True)  # 请求方的 API Key label，用于前端区分是哪台机器的会话
    started_at = Column(Double, default=time.time)
    ended_at = Column(Double)

    project = relationship("Project", back_populates="sessions")
    events = relationship("Event", back_populates="session")
    messages = relationship("Message", back_populates="session")
    parent = relationship(
        "Session",
        remote_side=[id],
        foreign_keys=[parent_id],
        back_populates="children",
    )
    children = relationship(
        "Session",
        foreign_keys=[parent_id],
        back_populates="parent",
        overlaps="parent",
    )


class Event(Base):
    """工具调用事件表：每次 hook 上报一条记录。"""
    __tablename__ = "events"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    tool_name = Column(String(128))
    tool_use_id = Column(String(64), nullable=True)
    type = Column(String(32), nullable=False)
    input = Column(Text)
    output = Column(Text)
    duration_ms = Column(BigInteger)
    created_at = Column(Double, default=time.time)
    parent_session_id = Column(String(36), nullable=True)

    session = relationship("Session", back_populates="events")

    __table_args__ = (
        Index("ix_events_session_id", "session_id"),
    )


class Message(Base):
    """聊天消息表：手机发给 Agent 的消息及 Agent 的回复。"""
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    content = Column(Text, nullable=False)
    role = Column(Enum("user", "assistant"), nullable=False, default="user")
    status = Column(Enum("pending", "delivered"), default="pending")
    source_uuid = Column(String(64), nullable=True, unique=True)
    created_at = Column(Double, default=time.time)

    session = relationship("Session", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_session_status", "session_id", "status"),
    )


class Memory(Base):
    """知识条目表：Agent 运行后提炼的项目知识。"""
    __tablename__ = "memories"

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    title = Column(String(512), nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(String(512))
    status = Column(Enum("pending", "active", "rejected", "review"), default="pending")
    tier = Column(Enum("short", "long"), default="short", nullable=False)
    updated_at = Column(Double, default=time.time)
    source_session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    created_at = Column(Double, default=time.time)
    activated_at = Column(Double)
    score_total = Column(Integer, nullable=False, default=0)
    feedback_count = Column(Integer, nullable=False, default=0)
    last_feedback_at = Column(Double)
    review_score = Column(Integer)
    review_reason = Column(String(255))

    project = relationship("Project", back_populates="memories")
    feedback_logs = relationship("MemoryFeedbackLog", back_populates="memory")
    search_exposures = relationship("MemorySearchExposure", back_populates="memory")

    __table_args__ = (
        Index("ix_memories_project_status", "project_id", "status"),
    )


class MemoryFeedbackLog(Base):
    """记忆反馈日志表：记录每次显式反馈，为后续反馈闭环保留审计数据。"""
    __tablename__ = "memory_feedback_logs"

    id = Column(String(36), primary_key=True, default=_uuid)
    memory_id = Column(String(36), ForeignKey("memories.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    feedback = Column(String(32), nullable=False)
    score_delta = Column(Integer, nullable=False, default=0)
    reason = Column(Text)
    created_at = Column(Double, default=time.time, nullable=False)

    memory = relationship("Memory", back_populates="feedback_logs")

    __table_args__ = (
        Index("ix_memory_feedback_logs_memory_created", "memory_id", "created_at"),
    )


class MemorySearchExposure(Base):
    """记忆搜索曝光表：记录显式搜索结果曝光，供后续反馈与去重链路使用。"""
    __tablename__ = "memory_search_exposures"

    id = Column(String(36), primary_key=True, default=_uuid)
    memory_id = Column(String(36), ForeignKey("memories.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    query = Column(String(512), nullable=False)
    exposed_at = Column(Double, default=time.time, nullable=False)

    memory = relationship("Memory", back_populates="search_exposures")

    __table_args__ = (
        Index("ix_memory_search_exposures_exposed_at", "exposed_at"),
        Index("ix_memory_search_exposures_memory_session", "memory_id", "session_id"),
    )


class ApiKey(Base):
    """API Key 表：存储团队成员认证凭证的哈希值。"""
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, default=_uuid)
    key_hash = Column(String(64), nullable=False, unique=True)
    label = Column(String(128), nullable=False)
    # SQLite 将 Boolean 存为 0/1，为跨数据库兼容直接用 Integer
    is_admin = Column(Integer, nullable=False, default=0)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(Double, default=time.time)
