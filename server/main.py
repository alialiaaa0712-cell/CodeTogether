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

if not os.getenv("TESTING"):
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
