from __future__ import annotations

import time
import uuid

from sqlalchemy import BigInteger, Column, Double, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from server.database import Base


def _uuid() -> str:
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
    type = Column(String(32), nullable=False)
    input = Column(Text)
    output = Column(Text)
    duration_ms = Column(BigInteger)
    created_at = Column(Double, default=time.time)

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
    status = Column(Enum("pending", "active", "rejected"), default="pending")
    source_session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    created_at = Column(Double, default=time.time)
    activated_at = Column(Double)

    project = relationship("Project", back_populates="memories")

    __table_args__ = (
        Index("ix_memories_project_status", "project_id", "status"),
    )
