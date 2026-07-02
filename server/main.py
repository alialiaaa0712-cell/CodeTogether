from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, sessionmaker

from server.database import Base, SessionLocal, engine, _is_sqlite, get_db
from server.models import ApiKey as ApiKeyModel
from server.models import Memory as MemoryModel
from server.models import Message as MessageModel
from server.models import Session as SessionModel
from server.routers import agents, chat, events, memory, auth as auth_router
from server.routers.auth import get_current_key, seed_admin_key, _hash_key
from server.services.housekeeping import run_memory_housekeeping
from server.ws_manager import ConnectionManager

logging.basicConfig(level=logging.INFO)


def _ensure_event_columns() -> None:
    """补齐 events 表的兼容列，保证旧库可以被当前服务读取。

    参数:
        无。

    返回值:
        无；缺失列时直接执行一次迁移。
    """
    inspector = inspect(engine)
    event_cols = {column["name"] for column in inspector.get_columns("events")}
    if "parent_session_id" not in event_cols:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE events ADD COLUMN parent_session_id VARCHAR(36)"))
            conn.commit()
    if "tool_use_id" not in event_cols:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE events ADD COLUMN tool_use_id VARCHAR(64)"))
            conn.commit()


def _ensure_auth_columns() -> None:
    """
    补齐 sessions 表的 user_label 列；对旧实例做兼容迁移。

    参数:
        无。

    返回值:
        无；若检测到列缺失，执行一次 ALTER TABLE。
    """
    inspector = inspect(engine)
    session_cols = {c["name"] for c in inspector.get_columns("sessions")}
    if "user_label" not in session_cols:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE sessions ADD COLUMN user_label VARCHAR(128)"))
            conn.commit()


def _migrate_memories_to_score_fields() -> None:
    """为旧 hit-based memories 表执行一次性迁移。

    参数:
        无。

    返回值:
        无；若检测到旧 hit 结构，会先清空 `memories` 表，再补齐新 score 字段并删除旧列。
    """
    legacy_hit_columns = {"hit_count_7d", "last_hit_at", "review_hit_count"}
    score_columns = {
        "score_total": "ALTER TABLE memories ADD COLUMN score_total INT NOT NULL DEFAULT 0",
        "feedback_count": "ALTER TABLE memories ADD COLUMN feedback_count INT NOT NULL DEFAULT 0",
        "last_feedback_at": "ALTER TABLE memories ADD COLUMN last_feedback_at DOUBLE NULL",
        "review_score": "ALTER TABLE memories ADD COLUMN review_score INT NULL",
        "review_reason": "ALTER TABLE memories ADD COLUMN review_reason VARCHAR(255) NULL",
    }

    with engine.connect() as conn:
        inspector = inspect(engine)
        memory_cols = {column["name"] for column in inspector.get_columns("memories")}

        if legacy_hit_columns & memory_cols:
            conn.execute(text("DELETE FROM memories"))
            conn.commit()

        for column_name, ddl in score_columns.items():
            if column_name not in memory_cols:
                conn.execute(text(ddl))
                conn.commit()
                memory_cols.add(column_name)

        inspector = inspect(engine)
        memory_cols = {column["name"] for column in inspector.get_columns("memories")}
        for column_name in legacy_hit_columns:
            if column_name in memory_cols:
                conn.execute(text(f"ALTER TABLE memories DROP COLUMN {column_name}"))
                conn.commit()


def _activate_short_pending_memories() -> None:
    """将历史自动提炼的短期 pending 记忆直接启用，并尽量补齐项目归属。

    参数:
        无。

    返回值:
        无；重复执行时仅处理仍为 pending/short 的记录，保持幂等。
    """
    db = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        memories = (
            db.query(MemoryModel)
            .filter(
                MemoryModel.status == "pending",
                MemoryModel.tier == "short",
                MemoryModel.source_session_id.isnot(None),
            )
            .all()
        )
        now = time.time()
        for memory_row in memories:
            session = db.get(SessionModel, memory_row.source_session_id)
            resolved_project_id = memory_row.project_id
            if session and not resolved_project_id:
                resolved_project_id = session.project_id
            if session and not resolved_project_id:
                resolved_project_id = agents._ensure_project_for_cwd(session.cwd, db)
                if resolved_project_id and not session.project_id:
                    session.project_id = resolved_project_id

            memory_row.status = "active"
            memory_row.project_id = resolved_project_id
            if not memory_row.activated_at:
                memory_row.activated_at = now
            memory_row.updated_at = now
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _run_startup_migrations() -> None:
    """在非测试启动路径执行轻量迁移，兼容历史数据库结构。

    参数:
        无。

    返回值:
        无；按需补齐兼容列、记忆评分列，并修复历史短期记忆状态。
    """
    Base.metadata.create_all(bind=engine)
    if not _is_sqlite:
        _ensure_event_columns()
        _ensure_auth_columns()
        _migrate_memories_to_score_fields()
    _activate_short_pending_memories()
    db = SessionLocal()
    try:
        seed_admin_key(db)
    finally:
        db.close()


if not os.getenv("TESTING"):
    _run_startup_migrations()

manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理应用生命周期：初始化广播模块，启动定时任务，退出时清理。

    参数:
        app: FastAPI 应用实例。

    返回值:
        无；使用 async generator 协议，yield 前为启动阶段，yield 后为关闭阶段。
    """
    from server import broadcast

    # 初始化广播模块：连接 Redis（若配置了 REDIS_URL），注入本进程 WebSocket 管理器
    await broadcast.init(manager)
    # 启动 Redis 订阅协程，将 channel 消息广播给本进程所有 WebSocket 连接
    subscribe_task = asyncio.create_task(broadcast.subscribe_and_forward(manager))

    scheduler = None
    if not os.getenv("TESTING"):
        scheduler = BackgroundScheduler()
        def _housekeeping_job():
            db = SessionLocal()
            try:
                run_memory_housekeeping(db)
            finally:
                db.close()
        scheduler.add_job(_housekeeping_job, "cron", hour=2, minute=0)

        def _expire_pending_messages():
            import time
            db = SessionLocal()
            try:
                cutoff = time.time() - 300  # 5分钟
                msgs = db.query(MessageModel).filter(
                    MessageModel.status == "pending",
                    MessageModel.created_at < cutoff,
                ).all()
                for m in msgs:
                    m.status = "delivered"
                if msgs:
                    db.commit()
            finally:
                db.close()
        scheduler.add_job(_expire_pending_messages, "interval", minutes=1)
        scheduler.start()
    yield
    # 取消订阅协程，等待其干净退出
    subscribe_task.cancel()
    try:
        await subscribe_task
    except asyncio.CancelledError:
        pass
    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(title="CodeTogether", lifespan=lifespan)

app.state.ws_manager = manager

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_mobile_dir = Path(__file__).parent.parent / "mobile"
app.mount("/mobile", StaticFiles(directory=str(_mobile_dir), html=True), name="mobile")

app.include_router(agents.router)
app.include_router(events.router)
app.include_router(chat.router)
app.include_router(memory.router)
app.include_router(auth_router.router)


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    api_key: str = "",
    db: Session = Depends(get_db),
):
    """
    处理 WebSocket 连接。若服务端存在活跃 ApiKey 记录，则要求 api_key query param 有效。
    本地无认证场景（api_keys 表为空）时直接放行，保持向后兼容。

    参数:
        websocket: FastAPI WebSocket 连接对象。
        api_key: query string 中的明文 API Key，可为空。
        db: 数据库会话，通过 get_db 依赖注入，测试时可被 override。

    返回值:
        无；认证失败时以 code=4001 关闭连接。
    """
    has_any_key = db.query(ApiKeyModel).filter(ApiKeyModel.is_active == 1).first() is not None
    if has_any_key:
        if not api_key:
            await websocket.accept()
            await websocket.close(code=4001)
            return
        key_hash = _hash_key(api_key)
        valid = db.query(ApiKeyModel).filter(
            ApiKeyModel.key_hash == key_hash,
            ApiKeyModel.is_active == 1,
        ).first()
        if not valid:
            await websocket.accept()
            await websocket.close(code=4001)
            return
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/")
def root():
    """
    返回服务健康检查信息。

    参数:
        无。

    返回值:
        包含服务状态与服务名称的字典。
    """
    return {"status": "ok", "service": "CodeTogether"}


if __name__ == "__main__":
    port = int(os.getenv("SERVER_PORT", "7878"))
    uvicorn.run(app, host="0.0.0.0", port=port)
