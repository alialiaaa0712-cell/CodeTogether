# Scale Multi-Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 CodeTogether 升级为支持几十人同时使用的多 worker 架构：Redis 跨进程 WebSocket 广播 + hook 重试 + 数据库连接池调优。

**Architecture:** 新增 `server/broadcast.py` 封装 Redis pub/sub，所有路由中的 `manager.broadcast()` 改为 `broadcast.publish()`；无 Redis 时降级为进程内广播保持向后兼容；hooks 写操作加指数退避重试。

**Tech Stack:** FastAPI, redis[asyncio]==5.0.8, uvicorn multi-worker, Docker Compose

---

## 文件改动总览

| 文件 | 改动 |
|------|------|
| `server/broadcast.py` | 新建：Redis pub/sub 封装，含降级逻辑 |
| `server/main.py` | lifespan 启动订阅协程，注入 broadcast 模块的 manager 引用 |
| `server/routers/agents.py` | `manager.broadcast` → `broadcast.publish`（共 3 处直接调用 + 1 个辅助函数） |
| `server/routers/chat.py` | `manager.broadcast` → `broadcast.publish`（1 处） |
| `server/routers/events.py` | `manager.broadcast` → `broadcast.publish`（共 2 处直接调用 + 1 个辅助函数） |
| `server/database.py` | MySQL 连接池加 `pool_timeout=30, pool_recycle=3600` |
| `hooks/_common.py` | 新增 `_http_with_retry` 内部函数，4 个写操作使用重试 |
| `docker-compose.yml` | 新增 Redis 服务，app 改 2 worker |
| `requirements.txt` | 新增 `redis[asyncio]==5.0.8` |
| `.env.example` | 新增 `REDIS_URL` |
| `tests/test_broadcast.py` | 新建测试 |
| `tests/test_hooks_retry.py` | 新建测试 |

---

## CLAUDE.md 要求（子任务必须包含此项）

- 全程使用中文注释
- 函数/方法必须有文档注释（说明用途、参数、返回值）
- 查看代码时不相信注释，自己读代码判断

---

### Task 1：新建 server/broadcast.py

**Files:**
- Create: `server/broadcast.py`
- Test: `tests/test_broadcast.py`

- [ ] **Step 1：写失败测试**

新建 `tests/test_broadcast.py`：

```python
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
    import importlib
    import server.broadcast as bc

    with patch.dict(os.environ, {}, clear=True):
        # 移除 REDIS_URL
        os.environ.pop("REDIS_URL", None)
        asyncio.get_event_loop().run_until_complete(bc.init(MagicMock()))

    assert bc._redis_client is None
```

- [ ] **Step 2：运行测试确认失败**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
pytest tests/test_broadcast.py -v
```

期望：FAIL（`server.broadcast` 不存在）

- [ ] **Step 3：新建 server/broadcast.py**

```python
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
REDIS_URL: str = os.getenv("REDIS_URL", "")

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
        import redis.asyncio as aioredis
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
```

- [ ] **Step 4：运行测试确认通过**

```bash
pytest tests/test_broadcast.py -v
```

期望：3 个 PASS

- [ ] **Step 5：提交**

```bash
git add server/broadcast.py tests/test_broadcast.py
git commit -m "feat: 新增 broadcast.py，封装 Redis pub/sub 广播适配层"
```

---

### Task 2：router 广播调用迁移

**Files:**
- Modify: `server/routers/agents.py`
- Modify: `server/routers/chat.py`
- Modify: `server/routers/events.py`

共需修改 5 处直接 `manager.broadcast(...)` 调用和 2 个辅助函数（`_broadcast_session_update`）。

- [ ] **Step 1：修改 agents.py 的 _broadcast_session_update**

读取 `server/routers/agents.py`，找到 `_broadcast_session_update` 函数（约第 120 行），替换为：

```python
async def _broadcast_session_update(session: SessionModel) -> None:
    """
    广播最新会话快照给所有连接的手机端。

    参数:
        session: 已完成提交并刷新的会话 ORM 对象。

    返回值:
        无。
    """
    try:
        from server import broadcast
        await broadcast.publish({
            "type": "agent_update",
            "data": SessionOut.model_validate(session).model_dump(),
        })
    except Exception as exc:
        logger.warning("Session WebSocket 广播失败: %s", exc)
```

注意：函数签名去掉了 `request: Request` 参数。

- [ ] **Step 2：更新 agents.py 所有调用 _broadcast_session_update 的地方**

在 `agents.py` 中搜索所有 `await _broadcast_session_update(request, session)` 的调用（约第 182、213、241、273、297 行），改为 `await _broadcast_session_update(session)`（去掉 `request` 参数）。

同时找到直接调用 `manager.broadcast` 的位置（`delete_session` 函数内，约第 319-320 行）：

```python
manager = request.app.state.ws_manager
await manager.broadcast({"type": "agent_deleted", "data": {"id": session_id}})
```

替换为：

```python
from server import broadcast
await broadcast.publish({"type": "agent_deleted", "data": {"id": session_id}})
```

- [ ] **Step 3：修改 chat.py**

找到 `send_message` 函数中（约第 81-88 行）：

```python
try:
    manager = request.app.state.ws_manager
    await manager.broadcast({
        "type": "chat_message",
        "data": {"session_id": msg.session_id, "role": msg.role},
    })
except Exception:
    pass
```

替换为：

```python
try:
    from server import broadcast
    await broadcast.publish({
        "type": "chat_message",
        "data": {"session_id": msg.session_id, "role": msg.role},
    })
except Exception:
    pass
```

- [ ] **Step 4：修改 events.py 的 _broadcast_session_update**

找到 `events.py` 中的 `_broadcast_session_update` 函数（约第 18 行），替换为：

```python
async def _broadcast_session_update(session: SessionModel) -> None:
    """
    在事件导致会话首次出现时同步广播会话快照，避免移动端状态页漏掉新会话。

    参数:
        session: 需要广播的会话 ORM 对象。

    返回值:
        无。
    """
    try:
        from server import broadcast
        await broadcast.publish({
            "type": "agent_update",
            "data": SessionOut.model_validate(session).model_dump(),
        })
    except Exception as exc:
        logging.getLogger(__name__).warning("Session WebSocket 广播失败: %s", exc)
```

函数签名去掉 `request: Request`，更新所有调用（约第 94、96 行）去掉 `request` 参数。

同时找到 `receive_event` 中直接调用 `manager.broadcast` 的位置（约第 99-100 行）：

```python
manager = request.app.state.ws_manager
await manager.broadcast({
    "type": "event",
    "data": ...,
})
```

替换为：

```python
from server import broadcast
await broadcast.publish({
    "type": "event",
    "data": ...,
})
```

- [ ] **Step 5：运行全量测试确认无回归**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
pytest tests/ -q --ignore=tests/test_codetogether.py 2>&1 | tail -10
```

期望：145+ PASSED

- [ ] **Step 6：提交**

```bash
git add server/routers/agents.py server/routers/chat.py server/routers/events.py
git commit -m "feat: router 广播调用迁移至 broadcast.publish"
```

---

### Task 3：main.py 集成 broadcast 模块

**Files:**
- Modify: `server/main.py`

- [ ] **Step 1：修改 main.py**

在 `server/main.py` 中：

1. 在 import 区末尾加：
```python
from server import broadcast as _broadcast
```

2. 在 `lifespan` 函数内，`scheduler.start()` 之后、`yield` 之前，加入订阅协程启动：

```python
import asyncio
subscribe_task = asyncio.create_task(
    _broadcast.subscribe_and_forward(manager)
)
```

3. 在 `yield` 之后（teardown 阶段），取消订阅协程：

```python
subscribe_task.cancel()
try:
    await subscribe_task
except asyncio.CancelledError:
    pass
```

4. 在 `_run_startup_migrations()` 调用之前（约第 176 行）不需要改动，但在非测试路径首次运行时调用 broadcast.init：

实际上 `broadcast.init` 应在 `lifespan` 的最开始调用，因为 `manager` 在 lifespan 之前已创建：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await _broadcast.init(manager)
    subscribe_task = asyncio.create_task(
        _broadcast.subscribe_and_forward(manager)
    )
    scheduler = None
    if not os.getenv("TESTING"):
        # ... 原有 scheduler 代码不变 ...
    yield
    subscribe_task.cancel()
    try:
        await subscribe_task
    except asyncio.CancelledError:
        pass
    if scheduler is not None:
        scheduler.shutdown(wait=False)
```

- [ ] **Step 2：运行测试确认通过**

```bash
pytest tests/ -q --ignore=tests/test_codetogether.py 2>&1 | tail -10
```

期望：145+ PASSED

- [ ] **Step 3：提交**

```bash
git add server/main.py
git commit -m "feat: main.py 集成 broadcast 模块，lifespan 启动 Redis 订阅协程"
```

---

### Task 4：hook 写操作加重试

**Files:**
- Modify: `hooks/_common.py`
- Test: `tests/test_hooks_retry.py`

- [ ] **Step 1：写失败测试**

新建 `tests/test_hooks_retry.py`：

```python
"""测试 hooks/_common.py 中写操作的重试逻辑。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import time
from unittest.mock import patch, MagicMock
import urllib.error


def test_post_event_retries_on_network_error():
    """post_event 在网络错误时应重试最多 3 次。"""
    import hooks._common as _common

    call_count = 0
    def fake_urlopen(req, timeout):
        nonlocal call_count
        call_count += 1
        raise urllib.error.URLError("connection refused")

    with patch("hooks._common.time.sleep"), \
         patch("urllib.request.urlopen", side_effect=fake_urlopen):
        _common.post_event({"session_id": "s1", "type": "test"})

    assert call_count == 3


def test_post_event_no_retry_on_4xx():
    """post_event 收到 4xx 时不应重试。"""
    import hooks._common as _common

    call_count = 0
    mock_resp = MagicMock()
    mock_resp.status = 401

    def fake_urlopen(req, timeout):
        nonlocal call_count
        call_count += 1
        raise urllib.error.HTTPError(
            url="", code=401, msg="Unauthorized", hdrs={}, fp=None
        )

    with patch("hooks._common.time.sleep"), \
         patch("urllib.request.urlopen", side_effect=fake_urlopen):
        _common.post_event({"session_id": "s1", "type": "test"})

    assert call_count == 1


def test_post_event_succeeds_on_second_attempt():
    """post_event 第一次失败、第二次成功时应正常返回。"""
    import hooks._common as _common

    attempts = []
    mock_resp = MagicMock()

    def fake_urlopen(req, timeout):
        attempts.append(1)
        if len(attempts) == 1:
            raise urllib.error.URLError("timeout")
        return mock_resp

    with patch("hooks._common.time.sleep"), \
         patch("urllib.request.urlopen", side_effect=fake_urlopen):
        _common.post_event({"session_id": "s1", "type": "test"})

    assert len(attempts) == 2
```

- [ ] **Step 2：运行测试确认失败**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
pytest tests/test_hooks_retry.py -v
```

期望：FAIL（当前 post_event 无重试，call_count == 1 != 3）

- [ ] **Step 3：修改 hooks/_common.py 新增重试函数**

在文件顶部 import 区末尾加入 `import time`（若已有则跳过），然后在 `_auth_headers` 函数之后插入：

```python
import time

_RETRY_DELAYS = (0.5, 1.0, 2.0)


def _http_request_with_retry(req: "urllib.request.Request") -> None:
    """
    带指数退避重试的 HTTP 请求，专用于写操作（POST/PATCH）。

    网络错误或 5xx 时按 _RETRY_DELAYS 间隔重试；4xx 时立即放弃（不重试）。
    所有重试耗尽后静默跳过，不向上层抛出异常。

    参数:
        req: 已构造好的 urllib.request.Request 对象。

    返回值:
        无。
    """
    for i, delay in enumerate(_RETRY_DELAYS):
        try:
            urllib.request.urlopen(req, timeout=TIMEOUT)
            return
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                return  # 4xx 不重试
            if i < len(_RETRY_DELAYS) - 1:
                time.sleep(delay)
        except Exception:
            if i < len(_RETRY_DELAYS) - 1:
                time.sleep(delay)
```

- [ ] **Step 4：更新 4 个写操作函数使用重试**

将 `post_event`、`ensure_session`、`post_chat_message`、`mark_stopped` 中的：

```python
urllib.request.urlopen(req, timeout=TIMEOUT)
```

替换为：

```python
_http_request_with_retry(req)
```

同时将这 4 个函数的 `except Exception: pass` 保留不变（重试函数内部已静默处理）。

- [ ] **Step 5：运行测试确认通过**

```bash
pytest tests/test_hooks_retry.py -v
pytest tests/ -q --ignore=tests/test_codetogether.py 2>&1 | tail -5
```

期望：全部 PASS

- [ ] **Step 6：提交**

```bash
git add hooks/_common.py tests/test_hooks_retry.py
git commit -m "feat: hook 写操作加指数退避重试（最多 3 次）"
```

---

### Task 5：数据库连接池调优 + Docker 配置更新

**Files:**
- Modify: `server/database.py`
- Modify: `docker-compose.yml`
- Modify: `requirements.txt`
- Modify: `.env.example`

- [ ] **Step 1：修改 server/database.py**

找到 MySQL 分支（`else:` 块），将：

```python
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=20, max_overflow=40)
```

替换为：

```python
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=3600,
)
```

- [ ] **Step 2：修改 requirements.txt**

在末尾追加：

```
redis[asyncio]==5.0.8
```

- [ ] **Step 3：修改 docker-compose.yml**

将整个文件替换为：

```yaml
services:
  app:
    build: .
    restart: unless-stopped
    command: uvicorn server.main:app --host 0.0.0.0 --port 8000 --workers 2
    environment:
      - DATABASE_URL=mysql+pymysql://root:${MYSQL_ROOT_PASSWORD}@db:3306/codetogether
      - ADMIN_KEY=${ADMIN_KEY}
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    ports:
      - "8000:8000"

  db:
    image: mysql:8.0
    restart: unless-stopped
    environment:
      - MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}
      - MYSQL_DATABASE=codetogether
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru --save ""
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  mysql_data:
```

- [ ] **Step 4：修改 .env.example**

在末尾追加：

```
# Redis（多 worker 模式下必填；本地单进程开发可不填）
REDIS_URL=redis://redis:6379/0
```

- [ ] **Step 5：运行全量测试**

```bash
pip install redis[asyncio]==5.0.8 -q
pytest tests/ -q --ignore=tests/test_codetogether.py 2>&1 | tail -5
```

期望：145+ PASSED

- [ ] **Step 6：提交**

```bash
git add server/database.py requirements.txt docker-compose.yml .env.example
git commit -m "feat: 数据库连接池调优，Docker 新增 Redis 服务和多 worker 配置"
```
