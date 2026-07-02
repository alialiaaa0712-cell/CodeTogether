"""Redis pub/sub 广播适配层。

有 Redis 时将消息 PUBLISH 到 ct:broadcast channel，各 worker 的订阅协程收到后
各自广播给本进程的 WebSocket 连接。无 Redis 时降级为进程内直接广播。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from server.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

CHANNEL = "ct:broadcast"

_redis_client = None
_manager: Optional["ConnectionManager"] = None


async def init(manager: "ConnectionManager") -> None:
    """
    初始化广播模块：连接 Redis（若配置了 REDIS_URL），注入本进程 WebSocket 管理器。

    参数:
        manager: 本进程的 ConnectionManager 实例。

    返回值:
        无；Redis 连接失败时打印警告并降级为进程内广播。
    """
    global _redis_client, _manager
    _manager = manager

    url = os.getenv("REDIS_URL", "")
    if not url:
        # 显式置 None，确保 init 重新调用时不残留旧客户端
        _redis_client = None
        logger.info("REDIS_URL 未配置，使用进程内广播（单 worker 模式）")
        return

    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(url, decode_responses=True)
        await _redis_client.ping()
        logger.info("Redis 连接成功：%s", url)
    except Exception as exc:
        logger.warning("Redis 连接失败，降级为进程内广播：%s", exc)
        _redis_client = None


async def publish(message: dict) -> None:
    """
    广播消息给所有 worker 的 WebSocket 连接。

    有 Redis 时 PUBLISH 到 ct:broadcast channel，由各 worker 的订阅协程转发；
    无 Redis 时直接调用本进程 ConnectionManager.broadcast()。

    参数:
        message: 要广播的消息字典，格式为 {"type": ..., "data": ...}。

    返回值:
        无；失败时静默跳过，不影响主业务流程。
    """
    if _redis_client is not None:
        try:
            await _redis_client.publish(CHANNEL, json.dumps(message, ensure_ascii=False))
        except Exception as exc:
            logger.warning("Redis publish 失败，降级为进程内广播：%s", exc)
            if _manager:
                await _manager.broadcast(message)
    elif _manager is not None:
        await _manager.broadcast(message)


async def subscribe_and_forward(manager: "ConnectionManager") -> None:
    """
    订阅 Redis ct:broadcast channel，将收到的消息广播给本进程所有 WebSocket 连接。

    此函数应作为后台协程在 lifespan 中启动；无 Redis 时立即返回。

    参数:
        manager: 本进程的 ConnectionManager 实例。

    返回值:
        无；协程被取消时正常退出。
    """
    if _redis_client is None:
        return

    try:
        pubsub = _redis_client.pubsub()
        await pubsub.subscribe(CHANNEL)
        async for raw in pubsub.listen():
            if raw["type"] != "message":
                continue
            try:
                msg = json.loads(raw["data"])
                await manager.broadcast(msg)
            except Exception as exc:
                logger.warning("广播消息解析失败：%s", exc)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.warning("Redis 订阅协程异常退出：%s", exc)
