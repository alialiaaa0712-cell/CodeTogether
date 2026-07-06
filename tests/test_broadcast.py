import os
os.environ["TESTING"] = "1"

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_publish_without_redis_calls_local_broadcast():
    """无 Redis 时 publish 应直接调用本进程 manager.broadcast。"""
    import server.broadcast as bc

    mock_manager = MagicMock()
    mock_manager.broadcast = AsyncMock()
    bc._manager = mock_manager
    bc._redis_client = None

    msg = {"type": "test", "data": {}}
    asyncio.get_event_loop().run_until_complete(bc.publish(msg))

    mock_manager.broadcast.assert_awaited_once_with(msg)


def test_publish_with_redis_calls_publish():
    """有 Redis 时 publish 应调用 redis.publish 而不是本进程广播。"""
    import server.broadcast as bc

    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock()
    mock_manager = MagicMock()
    mock_manager.broadcast = AsyncMock()
    bc._redis_client = mock_redis
    bc._manager = mock_manager

    msg = {"type": "test", "data": {}}
    asyncio.get_event_loop().run_until_complete(bc.publish(msg))

    mock_redis.publish.assert_awaited_once()
    mock_manager.broadcast.assert_not_awaited()


def test_init_without_redis_url_sets_client_none():
    """REDIS_URL 未设置时，init 应将 _redis_client 置为 None（降级模式）。"""
    import server.broadcast as bc

    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("REDIS_URL", None)
        asyncio.get_event_loop().run_until_complete(bc.init(MagicMock()))

    assert bc._redis_client is None
