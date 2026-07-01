from __future__ import annotations

import json
from typing import List

from fastapi import WebSocket


class ConnectionManager:
    """管理 WebSocket 连接池，支持广播推送。

    维护所有活跃的 WebSocket 连接列表，提供连接、断开和广播功能。
    广播时自动检测并清理已断开的连接。
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """接受新的 WebSocket 连接并加入连接池。

        参数:
            websocket: 待接受的 WebSocket 连接对象

        返回值:
            无
        """
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """从连接池中移除指定的 WebSocket 连接。

        参数:
            websocket: 要移除的 WebSocket 连接对象

        返回值:
            无
        """
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        """广播 JSON 消息给所有连接，自动清理断开的连接。

        将消息序列化为 JSON 字符串后发送给所有活跃连接。
        若某连接发送失败，则将其标记为死连接并在广播结束后统一清理。

        参数:
            message: 要广播的消息字典，将被序列化为 JSON

        返回值:
            无
        """
        data = json.dumps(message, ensure_ascii=False)
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active_connections.remove(ws)
