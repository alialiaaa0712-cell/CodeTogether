# CodeTogether 服务器 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 CodeTogether 的 FastAPI + MySQL 服务器，提供 Agent 事件接收、WebSocket 广播、聊天消息中继、项目记忆存储与检索、知识提炼任务队列共五个核心模块。

**Architecture:** 在 WatchingYou 服务器的 WebSocket 广播模式和 hook 中继机制基础上重写，将存储层从 SQLite 换成 MySQL（SQLAlchemy ORM），新增 memory 模块（Claude API 异步提炼）和 chat 模块（手机 → Agent 消息中继）。各模块通过 FastAPI router 隔离，共用一个数据库连接池和 WebSocket 连接管理器。

**Tech Stack:** Python 3.9+, FastAPI, uvicorn, SQLAlchemy 2.x, PyMySQL, anthropic SDK, pytest, pytest-asyncio, httpx

---

## 文件结构

```
CodeTogether/
├── server/
│   ├── __init__.py
│   ├── main.py          # FastAPI app，注册所有 router，挂载静态文件
│   ├── database.py      # SQLAlchemy engine、SessionLocal、Base
│   ├── models.py        # SQLAlchemy ORM 模型（所有表）
│   ├── schemas.py       # Pydantic 请求/响应 schema
│   ├── ws_manager.py    # WebSocket 连接池（直接复用 WatchingYou）
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── agents.py    # /agents 路由（会话状态、父子关系）
│   │   ├── events.py    # /events 路由（工具调用事件接收、广播）
│   │   ├── chat.py      # /chat 路由（手机消息存储、hook 轮询取走）
│   │   └── memory.py    # /memory 路由（知识条目 CRUD、检索）
│   └── services/
│       ├── __init__.py
│       └── extractor.py # Claude API 知识提炼服务
├── tests/
│   ├── conftest.py      # pytest fixtures（测试数据库、client）
│   ├── test_agents.py
│   ├── test_events.py
│   ├── test_chat.py
│   └── test_memory.py
├── requirements.txt
└── .env.example
```

---

## Task 1: 项目初始化与数据库连接

**Files:**
- Create: `server/__init__.py`
- Create: `server/database.py`
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `tests/conftest.py`

- [ ] **步骤 1：创建 requirements.txt**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.36
pymysql==1.1.1
anthropic==0.40.0
python-dotenv==1.0.1
httpx==0.27.2
pytest==8.3.3
pytest-asyncio==0.24.0
```

- [ ] **步骤 2：创建 .env.example**

```
DATABASE_URL=mysql+pymysql://user:password@localhost:3306/codetogether
ANTHROPIC_API_KEY=sk-ant-xxx
SERVER_PORT=7878
```

- [ ] **步骤 3：写 database.py 的失败测试**

```python
# tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from server.database import Base, get_db
from server.main import app
from fastapi.testclient import TestClient

TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return eng

@pytest.fixture
def db(engine):
    TestingSessionLocal = sessionmaker(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def client(engine):
    TestingSessionLocal = sessionmaker(bind=engine)
    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)
```

- [ ] **步骤 4：运行测试，确认失败（模块不存在）**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
pytest tests/conftest.py -v 2>&1 | head -20
```

预期：`ModuleNotFoundError: No module named 'server'`

- [ ] **步骤 5：实现 database.py**

```python
# server/database.py
from __future__ import annotations

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:root@localhost:3306/codetogether")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 依赖注入：提供数据库会话，请求结束后自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **步骤 6：创建 server/__init__.py（空文件）**

```python
# server/__init__.py
```

- [ ] **步骤 7：创建占位 main.py（让 conftest 可以导入）**

```python
# server/main.py
from fastapi import FastAPI
app = FastAPI(title="CodeTogether")
```

- [ ] **步骤 8：运行测试，确认通过**

```bash
pytest tests/conftest.py -v
```

预期：收集到 fixtures，无报错

- [ ] **步骤 9：提交**

```bash
git add server/ tests/ requirements.txt .env.example
git commit -m "feat: 初始化 CodeTogether 服务器项目结构"
```

---

## Task 2: ORM 数据模型

**Files:**
- Create: `server/models.py`

- [ ] **步骤 1：写模型导入测试**

```python
# tests/test_models.py
from server.models import Project, Session, Event, Message, Memory

def test_models_importable():
    """确认所有 ORM 模型可导入，表结构定义无误。"""
    assert Project.__tablename__ == "projects"
    assert Session.__tablename__ == "sessions"
    assert Event.__tablename__ == "events"
    assert Message.__tablename__ == "messages"
    assert Memory.__tablename__ == "memories"
```

- [ ] **步骤 2：运行测试，确认失败**

```bash
pytest tests/test_models.py -v
```

预期：`ImportError: cannot import name 'Project'`

- [ ] **步骤 3：实现 models.py（前半部分）**

```python
# server/models.py
from __future__ import annotations

import time
import uuid
from typing import Optional

from sqlalchemy import (
    BigInteger, Column, Enum, Float, ForeignKey,
    Index, String, Text, text
)
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
    created_at = Column(Float, default=time.time)

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
    started_at = Column(Float, default=time.time)
    ended_at = Column(Float)

    project = relationship("Project", back_populates="sessions")
    events = relationship("Event", back_populates="session")
    messages = relationship("Message", back_populates="session")
```

- [ ] **步骤 4：实现 models.py（后半部分）**

```python
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
    created_at = Column(Float, default=time.time)

    session = relationship("Session", back_populates="events")

    __table_args__ = (
        Index("ix_events_session_id", "session_id"),
    )


class Message(Base):
    """聊天消息表：手机发给 Agent 的消息，hook 轮询取走。"""
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(Enum("pending", "delivered"), default="pending")
    created_at = Column(Float, default=time.time)

    session = relationship("Session", back_populates="messages")


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
    created_at = Column(Float, default=time.time)
    activated_at = Column(Float)

    project = relationship("Project", back_populates="memories")

    __table_args__ = (
        Index("ix_memories_project_status", "project_id", "status"),
    )
```

- [ ] **步骤 5：运行测试，确认通过**

```bash
pytest tests/test_models.py -v
```

预期：`PASSED`

- [ ] **步骤 6：提交**

```bash
git add server/models.py tests/test_models.py
git commit -m "feat: 添加 SQLAlchemy ORM 数据模型"
```

---

## Task 3: Pydantic Schemas

**Files:**
- Create: `server/schemas.py`

- [ ] **步骤 1：写 schema 测试**

```python
# tests/test_schemas.py
from server.schemas import (
    SessionCreate, SessionOut,
    EventCreate, EventOut,
    MessageCreate, MessageOut,
    MemoryCreate, MemoryOut, MemoryUpdate,
)

def test_event_create_schema():
    e = EventCreate(session_id="s1", type="pre_tool", tool_name="Bash")
    assert e.session_id == "s1"

def test_memory_update_schema():
    u = MemoryUpdate(status="active")
    assert u.status == "active"
```

- [ ] **步骤 2：运行测试，确认失败**

```bash
pytest tests/test_schemas.py -v
```

预期：`ImportError`

- [ ] **步骤 3：实现 schemas.py**

```python
# server/schemas.py
from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel


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

    class Config:
        from_attributes = True


class EventCreate(BaseModel):
    session_id: str
    type: str
    tool_name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    output: Optional[str] = None
    duration_ms: Optional[int] = None


class EventOut(BaseModel):
    id: str
    session_id: str
    type: str
    tool_name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    output: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: float

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    session_id: str
    content: str


class MessageOut(BaseModel):
    id: str
    session_id: str
    content: str
    status: str
    created_at: float

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


class MemoryUpdate(BaseModel):
    status: str  # "active" | "rejected"
```

- [ ] **步骤 4：运行测试，确认通过**

```bash
pytest tests/test_schemas.py -v
```

- [ ] **步骤 5：提交**

```bash
git add server/schemas.py tests/test_schemas.py
git commit -m "feat: 添加 Pydantic request/response schemas"
```

---

## Task 4: WebSocket 管理器（复用）

**Files:**
- Create: `server/ws_manager.py`

直接从 WatchingYou 复制，无需修改。

- [ ] **步骤 1：复制 ws_manager.py**

```bash
cp /Users/qinepan/Desktop/test/WatchingYou/server/ws_manager.py \
   /Users/qinepan/Desktop/search/CodeTogether/server/ws_manager.py
```

- [ ] **步骤 2：写导入测试**

```python
# tests/test_ws_manager.py
from server.ws_manager import ConnectionManager

def test_connection_manager_init():
    manager = ConnectionManager()
    assert manager.active_connections == []
```

- [ ] **步骤 3：运行测试，确认通过**

```bash
pytest tests/test_ws_manager.py -v
```

- [ ] **步骤 4：提交**

```bash
git add server/ws_manager.py tests/test_ws_manager.py
git commit -m "feat: 复用 WatchingYou WebSocket 连接管理器"
```

---

## Task 5: agents 路由

**Files:**
- Create: `server/routers/__init__.py`
- Create: `server/routers/agents.py`
- Create: `tests/test_agents.py`

- [ ] **步骤 1：写失败测试**

```python
# tests/test_agents.py
import json

def test_create_and_list_session(client):
    """上报新会话后，GET /agents 应返回该会话。"""
    resp = client.post("/agents", json={"id": "sess-001", "cwd": "/home/user/project"})
    assert resp.status_code == 200

    resp = client.get("/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert any(a["id"] == "sess-001" for a in agents)

def test_update_session_status(client):
    """Stop 事件应将会话状态更新为 stopped。"""
    client.post("/agents", json={"id": "sess-002"})
    resp = client.patch("/agents/sess-002/status", json={"status": "stopped"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"

def test_update_parent(client):
    """手动设置父会话关系。"""
    client.post("/agents", json={"id": "parent-001"})
    client.post("/agents", json={"id": "child-001"})
    resp = client.patch("/agents/child-001/parent", json={"parent_id": "parent-001"})
    assert resp.status_code == 200
    assert resp.json()["parent_id"] == "parent-001"
```

- [ ] **步骤 2：运行测试，确认失败**

```bash
pytest tests/test_agents.py -v
```

预期：`404 Not Found`（路由未注册）

- [ ] **步骤 3：实现 routers/agents.py**

```python
# server/routers/agents.py
from __future__ import annotations

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


class ModelUpdate(BaseModel):
    model: str


class NotesUpdate(BaseModel):
    notes: str


@router.post("", response_model=SessionOut)
def create_session(body: SessionCreate, db: DBSession = Depends(get_db)):
    """PreToolUse hook 首次上报时创建会话记录。"""
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
    """返回所有会话列表。"""
    return db.query(SessionModel).all()


@router.patch("/{session_id}/status", response_model=SessionOut)
def update_status(session_id: str, body: StatusUpdate, db: DBSession = Depends(get_db)):
    """Stop hook 调用，将会话标记为 stopped。"""
    import time
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
    """手动设置或清除父会话关系。"""
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.parent_id = body.parent_id
    db.commit()
    db.refresh(session)
    return session


@router.patch("/{session_id}/model", response_model=SessionOut)
def update_model(session_id: str, body: ModelUpdate, db: DBSession = Depends(get_db)):
    """SessionStart hook 上报模型名称。"""
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.model = body.model
    db.commit()
    db.refresh(session)
    return session


@router.patch("/{session_id}/notes", response_model=SessionOut)
def update_notes(session_id: str, body: NotesUpdate, db: DBSession = Depends(get_db)):
    """用户在 Dashboard 添加备注。"""
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session.notes = body.notes
    db.commit()
    db.refresh(session)
    return session
```

- [ ] **步骤 4：更新 main.py 注册 agents router**

```python
# server/main.py
from fastapi import FastAPI
from server.routers import agents

app = FastAPI(title="CodeTogether")
app.include_router(agents.router)
```

- [ ] **步骤 5：创建 routers/__init__.py（空文件）**

```python
# server/routers/__init__.py
```

- [ ] **步骤 6：运行测试，确认通过**

```bash
pytest tests/test_agents.py -v
```

- [ ] **步骤 7：提交**

```bash
git add server/routers/ server/main.py tests/test_agents.py
git commit -m "feat: 实现 agents 路由（会话管理）"
```

---

## Task 6: events 路由

**Files:**
- Create: `server/routers/events.py`
- Create: `tests/test_events.py`

- [ ] **步骤 1：写失败测试**

```python
# tests/test_events.py
import json

def test_post_and_list_event(client):
    """上报事件后，GET /events 应返回该事件。"""
    client.post("/agents", json={"id": "sess-evt-001"})
    resp = client.post("/events", json={
        "session_id": "sess-evt-001",
        "type": "pre_tool",
        "tool_name": "Bash",
        "input": {"command": "ls"}
    })
    assert resp.status_code == 200
    event_id = resp.json()["id"]

    resp = client.get("/events?session_id=sess-evt-001")
    assert resp.status_code == 200
    ids = [e["id"] for e in resp.json()]
    assert event_id in ids

def test_event_requires_existing_session(client):
    """上报不存在会话的事件时，自动创建会话。"""
    resp = client.post("/events", json={
        "session_id": "auto-created-sess",
        "type": "pre_tool",
        "tool_name": "Read"
    })
    assert resp.status_code == 200
```

- [ ] **步骤 2：运行测试，确认失败**

```bash
pytest tests/test_events.py -v
```

- [ ] **步骤 3：实现 routers/events.py**

```python
# server/routers/events.py
from __future__ import annotations

import json
from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import Event as EventModel, Session as SessionModel
from server.schemas import EventCreate, EventOut

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventOut)
def receive_event(body: EventCreate, db: DBSession = Depends(get_db)):
    """接收 hook 上报的工具调用事件，会话不存在时自动创建。"""
    if not db.get(SessionModel, body.session_id):
        db.add(SessionModel(id=body.session_id))
        db.commit()

    input_str = json.dumps(body.input, ensure_ascii=False) if body.input else None
    event = EventModel(
        session_id=body.session_id,
        type=body.type,
        tool_name=body.tool_name,
        input=input_str,
        output=body.output,
        duration_ms=body.duration_ms,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("", response_model=List[EventOut])
def list_events(session_id: Optional[str] = None, db: DBSession = Depends(get_db)):
    """返回事件列表，可按 session_id 过滤，最多返回 500 条。"""
    q = db.query(EventModel).order_by(EventModel.created_at.desc())
    if session_id:
        q = q.filter(EventModel.session_id == session_id)
    return q.limit(500).all()
```

- [ ] **步骤 4：在 main.py 注册 events router**

```python
# server/main.py
from fastapi import FastAPI
from server.routers import agents, events

app = FastAPI(title="CodeTogether")
app.include_router(agents.router)
app.include_router(events.router)
```

- [ ] **步骤 5：运行测试，确认通过**

```bash
pytest tests/test_events.py -v
```

- [ ] **步骤 6：提交**

```bash
git add server/routers/events.py server/main.py tests/test_events.py
git commit -m "feat: 实现 events 路由（工具调用事件接收）"
```

---

## Task 7: chat 路由（手机 → Agent 消息中继）

**Files:**
- Create: `server/routers/chat.py`
- Create: `tests/test_chat.py`

- [ ] **步骤 1：写失败测试**

```python
# tests/test_chat.py

def test_send_and_poll_message(client):
    """手机发消息后，hook 轮询应取到该消息并标记为 delivered。"""
    client.post("/agents", json={"id": "sess-chat-001"})

    resp = client.post("/chat", json={"session_id": "sess-chat-001", "content": "请检查一下测试状态"})
    assert resp.status_code == 200
    msg_id = resp.json()["id"]
    assert resp.json()["status"] == "pending"

    # hook 轮询取走消息
    resp = client.get("/chat/sess-chat-001/poll")
    assert resp.status_code == 200
    messages = resp.json()
    assert any(m["id"] == msg_id for m in messages)
    assert all(m["status"] == "delivered" for m in messages)

def test_poll_returns_empty_after_consumed(client):
    """消息取走后，再次轮询应返回空列表。"""
    client.post("/agents", json={"id": "sess-chat-002"})
    client.post("/chat", json={"session_id": "sess-chat-002", "content": "hello"})
    client.get("/chat/sess-chat-002/poll")  # 取走

    resp = client.get("/chat/sess-chat-002/poll")
    assert resp.json() == []
```

- [ ] **步骤 2：运行测试，确认失败**

```bash
pytest tests/test_chat.py -v
```

- [ ] **步骤 3：实现 routers/chat.py**

```python
# server/routers/chat.py
from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import Message as MessageModel
from server.schemas import MessageCreate, MessageOut

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=MessageOut)
def send_message(body: MessageCreate, db: DBSession = Depends(get_db)):
    """手机端发送消息，初始状态为 pending。"""
    msg = MessageModel(session_id=body.session_id, content=body.content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


@router.get("/{session_id}/poll", response_model=List[MessageOut])
def poll_messages(session_id: str, db: DBSession = Depends(get_db)):
    """PreToolUse hook 调用：取走该会话所有 pending 消息，标记为 delivered。"""
    messages = (
        db.query(MessageModel)
        .filter(MessageModel.session_id == session_id, MessageModel.status == "pending")
        .all()
    )
    for msg in messages:
        msg.status = "delivered"
    db.commit()
    return messages


@router.get("/{session_id}/history", response_model=List[MessageOut])
def message_history(session_id: str, db: DBSession = Depends(get_db)):
    """手机端查看该会话的历史消息。"""
    return (
        db.query(MessageModel)
        .filter(MessageModel.session_id == session_id)
        .order_by(MessageModel.created_at.desc())
        .limit(100)
        .all()
    )
```

- [ ] **步骤 4：在 main.py 注册 chat router**

```python
# server/main.py
from fastapi import FastAPI
from server.routers import agents, events, chat

app = FastAPI(title="CodeTogether")
app.include_router(agents.router)
app.include_router(events.router)
app.include_router(chat.router)
```

- [ ] **步骤 5：运行测试，确认通过**

```bash
pytest tests/test_chat.py -v
```

- [ ] **步骤 6：提交**

```bash
git add server/routers/chat.py server/main.py tests/test_chat.py
git commit -m "feat: 实现 chat 路由（手机→Agent 消息中继）"
```

---

## Task 8: memory 路由（知识条目 CRUD + 检索）

**Files:**
- Create: `server/routers/memory.py`
- Create: `tests/test_memory.py`

- [ ] **步骤 1：写失败测试**

```python
# tests/test_memory.py

def test_create_memory(client):
    """创建知识条目，默认状态为 pending。"""
    resp = client.post("/memory", json={
        "title": "数据库连接池配置",
        "content": "使用 SQLAlchemy pool_pre_ping=True 防止连接超时断开",
        "tags": "database,sqlalchemy,config"
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

def test_activate_memory(client):
    """审核通过后，状态应变为 active。"""
    resp = client.post("/memory", json={"title": "测试知识", "content": "内容"})
    mem_id = resp.json()["id"]

    resp = client.patch(f"/memory/{mem_id}", json={"status": "active"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"

def test_search_memory(client):
    """全文搜索应返回包含关键词的 active 条目。"""
    client.post("/memory", json={"title": "FastAPI 路由注册", "content": "使用 include_router 注册子路由", "tags": "fastapi"})
    mem_resp = client.post("/memory", json={"title": "FastAPI 路由注册", "content": "使用 include_router 注册子路由", "tags": "fastapi"})
    client.patch(f"/memory/{mem_resp.json()['id']}", json={"status": "active"})

    resp = client.get("/memory/search?q=include_router")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) >= 1
    assert all(r["status"] == "active" for r in results)
```

- [ ] **步骤 2：运行测试，确认失败**

```bash
pytest tests/test_memory.py -v
```

- [ ] **步骤 3：实现 routers/memory.py**

```python
# server/routers/memory.py
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
    """创建知识条目，初始状态为 pending，等待人工审核。"""
    memory = MemoryModel(**body.model_dump())
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


@router.get("", response_model=List[MemoryOut])
def list_memories(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    db: DBSession = Depends(get_db)
):
    """列出知识条目，支持按项目和状态过滤。"""
    q = db.query(MemoryModel)
    if project_id:
        q = q.filter(MemoryModel.project_id == project_id)
    if status:
        q = q.filter(MemoryModel.status == status)
    return q.order_by(MemoryModel.created_at.desc()).limit(200).all()


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_memory(memory_id: str, body: MemoryUpdate, db: DBSession = Depends(get_db)):
    """人工审核：将 pending 条目激活或拒绝。"""
    memory = db.get(MemoryModel, memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="memory not found")
    memory.status = body.status
    if body.status == "active":
        memory.activated_at = time.time()
    db.commit()
    db.refresh(memory)
    return memory


@router.get("/search", response_model=List[MemoryOut])
def search_memories(
    q: str,
    project_id: Optional[str] = None,
    db: DBSession = Depends(get_db)
):
    """
    全文搜索 active 知识条目。
    SQLite 测试环境用 LIKE 模糊匹配，生产 MySQL 可升级为 FULLTEXT。
    最多返回 3 条，总字数由调用方控制。
    """
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
```

- [ ] **步骤 4：在 main.py 注册 memory router**

```python
# server/main.py
from fastapi import FastAPI
from server.routers import agents, events, chat, memory

app = FastAPI(title="CodeTogether")
app.include_router(agents.router)
app.include_router(events.router)
app.include_router(chat.router)
app.include_router(memory.router)
```

- [ ] **步骤 5：运行测试，确认通过**

```bash
pytest tests/test_memory.py -v
```

- [ ] **步骤 6：提交**

```bash
git add server/routers/memory.py server/main.py tests/test_memory.py
git commit -m "feat: 实现 memory 路由（知识条目 CRUD + 全文检索）"
```

---

## Task 9: 知识提炼服务（Claude API）

**Files:**
- Create: `server/services/__init__.py`
- Create: `server/services/extractor.py`
- Create: `tests/test_extractor.py`

- [ ] **步骤 1：写失败测试**

```python
# tests/test_extractor.py
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from server.services.extractor import extract_memories


@pytest.mark.asyncio
async def test_extract_memories_returns_list():
    """Claude API 返回有效 JSON 时，应解析为知识条目列表。"""
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='[{"title":"测试配置","content":"使用 pytest-asyncio","tags":"test,pytest"}]')]

    with patch("server.services.extractor.anthropic.Anthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create.return_value = fake_response
        result = await extract_memories("session summary text", project_id="proj-1")

    assert isinstance(result, list)
    assert result[0]["title"] == "测试配置"


@pytest.mark.asyncio
async def test_extract_memories_handles_invalid_json():
    """Claude API 返回非 JSON 时，应返回空列表而不抛出异常。"""
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text="无法解析")]

    with patch("server.services.extractor.anthropic.Anthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create.return_value = fake_response
        result = await extract_memories("summary", project_id=None)

    assert result == []
```

- [ ] **步骤 2：运行测试，确认失败**

```bash
pytest tests/test_extractor.py -v
```

- [ ] **步骤 3：实现 services/extractor.py**

```python
# server/services/extractor.py
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import anthropic

logger = logging.getLogger(__name__)

_PROMPT = """你是一个知识提炼助手。以下是一段 Claude Code Agent 的会话摘要。
请从中提炼出对未来 Agent 有价值的项目知识，以 JSON 数组返回，每条格式为：
{{"title": "...", "content": "...", "tags": "逗号分隔的标签"}}

只返回 JSON 数组，不要有任何解释文字。如果没有值得记录的知识，返回空数组 []。

会话摘要：
{summary}"""


async def extract_memories(
    summary: str,
    project_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """调用 Claude API 从会话摘要中提炼知识条目。

    参数：
        summary: Agent 会话的文字摘要
        project_id: 归属项目 ID，透传到返回结果

    返回值：
        知识条目字典列表，每条含 title、content、tags、project_id
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": _PROMPT.format(summary=summary)}],
        )
        raw = resp.content[0].text.strip()
        items = json.loads(raw)
        for item in items:
            item["project_id"] = project_id
        return items
    except Exception as e:
        logger.warning("知识提炼失败: %s", e)
        return []
```

- [ ] **步骤 4：创建 services/__init__.py**

```python
# server/services/__init__.py
```

- [ ] **步骤 5：运行测试，确认通过**

```bash
pytest tests/test_extractor.py -v
```

- [ ] **步骤 6：在 agents router 的 Stop 端点中触发提炼**

在 `server/routers/agents.py` 的 `update_status` 函数中，当 `status == "stopped"` 时，后台触发提炼：

```python
# 在 update_status 函数末尾，stopped 分支内追加：
import asyncio
from server.services.extractor import extract_memories
from server.models import Memory as MemoryModel

if body.status == "stopped":
    session.ended_at = time.time()
    # 取最近 20 条事件摘要作为提炼输入
    from server.models import Event as EventModel
    recent_events = (
        db.query(EventModel)
        .filter(EventModel.session_id == session_id)
        .order_by(EventModel.created_at.desc())
        .limit(20)
        .all()
    )
    summary_lines = [f"{e.tool_name}: {(e.output or '')[:200]}" for e in recent_events]
    summary = "\n".join(summary_lines)

    async def _extract_and_save():
        items = await extract_memories(summary, project_id=session.project_id)
        save_db = SessionLocal()
        try:
            for item in items:
                save_db.add(MemoryModel(
                    project_id=item.get("project_id"),
                    title=item["title"],
                    content=item["content"],
                    tags=item.get("tags"),
                    source_session_id=session_id,
                ))
            save_db.commit()
        finally:
            save_db.close()

    asyncio.create_task(_extract_and_save())
```

在文件顶部追加导入：

```python
from server.database import SessionLocal
```

- [ ] **步骤 7：运行全量测试，确认通过**

```bash
pytest tests/ -v
```

- [ ] **步骤 8：提交**

```bash
git add server/services/ server/routers/agents.py tests/test_extractor.py
git commit -m "feat: 实现 Claude API 知识提炼服务，会话结束时异步触发"
```

---

## Task 10: WebSocket 广播集成 + 完整 main.py

**Files:**
- Modify: `server/main.py`

- [ ] **步骤 1：实现完整 main.py**

```python
# server/main.py
from __future__ import annotations

import logging
import os

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from server.database import Base, engine
from server.routers import agents, chat, events, memory
from server.ws_manager import ConnectionManager

logging.basicConfig(level=logging.INFO)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="CodeTogether")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()
app.state.ws_manager = manager

app.include_router(agents.router)
app.include_router(events.router)
app.include_router(chat.router)
app.include_router(memory.router)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """处理 WebSocket 连接，维持连接直到客户端断开。"""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/")
def root():
    return {"status": "ok", "service": "CodeTogether"}


if __name__ == "__main__":
    port = int(os.getenv("SERVER_PORT", "7878"))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

- [ ] **步骤 2：更新 events router，上报后广播 WebSocket**

在 `server/routers/events.py` 的 `receive_event` 函数末尾追加广播：

```python
from fastapi import APIRouter, Depends, Request
# 修改函数签名，加入 request 参数
@router.post("", response_model=EventOut)
def receive_event(body: EventCreate, request: Request, db: DBSession = Depends(get_db)):
    # ... 原有逻辑 ...
    # 末尾追加：
    import asyncio
    manager = request.app.state.ws_manager
    asyncio.create_task(manager.broadcast({"type": "event", "data": {
        "id": event.id,
        "session_id": event.session_id,
        "type": event.type,
        "tool_name": event.tool_name,
        "created_at": event.created_at,
    }}))
    return event
```

- [ ] **步骤 3：运行全量测试**

```bash
pytest tests/ -v
```

- [ ] **步骤 4：手动启动服务器验证**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
DATABASE_URL="sqlite:///./test_dev.db" python -m server.main
```

在另一个终端验证：

```bash
curl http://localhost:7878/
# 预期：{"status":"ok","service":"CodeTogether"}

curl http://localhost:7878/agents
# 预期：[]
```

- [ ] **步骤 5：提交**

```bash
git add server/main.py server/routers/events.py
git commit -m "feat: 完成服务器集成，WebSocket 广播事件，启动表自动创建"
```

---

## 自检清单

运行完所有任务后执行：

```bash
pytest tests/ -v --tb=short
```

预期全部通过。确认以下端点可正常响应：

- `POST /agents` — 创建会话
- `GET /agents` — 列出所有会话
- `POST /events` — 上报事件
- `GET /events?session_id=X` — 查询事件
- `POST /chat` — 发送消息
- `GET /chat/{id}/poll` — hook 轮询取走消息
- `POST /memory` — 创建知识条目
- `GET /memory/search?q=X` — 检索知识
- `PATCH /memory/{id}` — 审核激活
- `WS /ws` — WebSocket 连接
