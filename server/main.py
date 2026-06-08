from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler

from server.database import Base, SessionLocal, engine
from server.routers import agents, chat, events, memory
from server.services.housekeeping import run_memory_housekeeping
from server.ws_manager import ConnectionManager

logging.basicConfig(level=logging.INFO)

if not os.getenv("TESTING"):
    Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理应用生命周期：启动定时任务，退出时关闭。"""
    scheduler = BackgroundScheduler()

    def _housekeeping_job():
        """每日执行记忆清理任务的调度回调。"""
        db = SessionLocal()
        try:
            run_memory_housekeeping(db)
        finally:
            db.close()

    scheduler.add_job(_housekeeping_job, "cron", hour=2, minute=0)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="CodeTogether", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()
app.state.ws_manager = manager

_mobile_dir = Path(__file__).parent.parent / "mobile"
app.mount("/mobile", StaticFiles(directory=str(_mobile_dir), html=True), name="mobile")

app.include_router(agents.router)
app.include_router(events.router)
app.include_router(chat.router)
app.include_router(memory.router)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    处理 WebSocket 连接的建立与断开。

    参数:
        websocket: FastAPI 提供的 WebSocket 连接对象，用于接收客户端消息并维护连接状态。

    返回值:
        无返回值；连接关闭后结束协程。
    """
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
