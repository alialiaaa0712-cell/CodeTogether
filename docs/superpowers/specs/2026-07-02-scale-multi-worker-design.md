# CodeTogether 多 Worker 扩容设计

**日期**：2026-07-02  
**状态**：已确认

---

## 目标

将 CodeTogether 从单进程模式升级为支持几十人同时使用的多 worker 架构，解决三个核心问题：
1. WebSocket 广播跨进程不同步（主要瓶颈）
2. Hook 网络抖动时丢事件
3. 数据库连接池在高并发时耗尽

目标部署环境：阿里云 ECS 2核2GiB，uvicorn 2 个 worker。

---

## 整体架构

```
nginx (443)
    │
    ├─ uvicorn worker 1
    ├─ uvicorn worker 2
    │       │
    │       └─ 收到业务事件 → PUBLISH → Redis channel: ct:broadcast
    │                                         │
    │                    worker 1/2 各自 SUBSCRIBE ←┘
    │                           │
    │                    各自广播给本进程的 WebSocket 连接
    │
    ├─ Redis (无持久化，maxmemory 256mb)
    └─ MySQL (连接池 pool_size=10, max_overflow=20)
```

---

## 第一节：Redis 跨进程 WebSocket 广播

### 新增文件

`server/broadcast.py`：独立模块，封装 Redis publish/subscribe，与 `ws_manager.py` 解耦。

```python
# server/broadcast.py
"""Redis pub/sub 广播适配层。

无 Redis 时自动降级为 in-process 广播，保持向后兼容。
"""
```

提供两个接口：
- `async def publish(message: dict) -> None` — 发布消息到 Redis channel `ct:broadcast`
- `async def subscribe_and_forward(manager: ConnectionManager) -> None` — 订阅 Redis，收到消息后调用 `manager.broadcast()`（只发给本 worker 的连接）

### ConnectionManager 保持不变

`ws_manager.py` 的 `ConnectionManager` 只负责管理本进程内的 WebSocket 连接和广播，不感知 Redis。

### 调用方变更

所有 router 中的 `manager.broadcast(...)` 改为 `await broadcast.publish(...)`。

`broadcast.py` 的 `publish` 函数：
- 有 Redis 连接 → publish 到 Redis channel
- 无 Redis 连接（降级模式）→ 直接调用本进程 `manager.broadcast()`

### lifespan 变更（server/main.py）

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动 Redis 订阅协程
    task = asyncio.create_task(
        broadcast.subscribe_and_forward(manager)
    )
    yield
    task.cancel()
```

### Redis 连接配置

从环境变量 `REDIS_URL`（默认 `redis://localhost:6379/0`）读取。无法连接时打印警告并降级，不报错启动失败。

---

## 第二节：Hook 重试机制

### 改动文件

`hooks/_common.py`：新增 `_http_post_with_retry` 和 `_http_get_with_retry` 内部函数。

### 重试策略

```
最多 3 次
间隔：0.5s → 1s → 2s（指数退避）
触发条件：网络错误（OSError/URLError）或服务端 5xx
不重试：4xx（认证失败、参数错误无需重试）
总超时：单次 2s，3 次总计不超过 5.5s
```

### 应用范围

以下函数改用重试版本：
- `post_event()`
- `ensure_session()`
- `post_chat_message()`
- `mark_stopped()`

以下函数**不加重试**（有实时性要求，失败直接返回默认值更合理）：
- `poll_messages()` — stop hook 轮询，失败返回空列表即可
- `memory_search()` — 查询失败不影响主流程
- `memory_feedback()` — 反馈失败不影响主流程

---

## 第三节：数据库连接池调优

### 改动文件

`server/database.py`：MySQL 分支调整连接池参数。

当前值（已经比较合理）：
```python
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=20, max_overflow=40)
```

调整为（2核2G 服务器更保守）：
```python
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=3600,  # 1小时回收连接，防止 MySQL wait_timeout 断连
)
```

---

## 第四节：Docker 部署变更

### docker-compose.yml

新增 Redis 服务，app 增加 `REDIS_URL` 环境变量和 2 worker 启动命令：

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
    # ... 不变

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

### requirements.txt

新增：
```
redis[asyncio]==5.0.8
```

### .env.example

新增：
```
REDIS_URL=redis://redis:6379/0
```

---

## 兼容性说明

- **本地开发**：不设 `REDIS_URL` 时降级为单进程内广播，行为与改动前完全一致
- **测试**：测试环境不启动 Redis，降级模式保证所有测试继续通过
- **SQLite**：本地 SQLite 连接池参数不变（SQLite 不支持连接池）

---

## 改动范围总结

| 文件 | 改动 |
|------|------|
| `server/broadcast.py` | **新增**：Redis pub/sub 封装，含降级逻辑 |
| `server/main.py` | lifespan 启动订阅协程，import broadcast |
| `server/routers/agents.py` | `manager.broadcast` → `broadcast.publish` |
| `server/routers/chat.py` | 同上 |
| `server/routers/events.py` | 同上 |
| `server/database.py` | MySQL 连接池加 `pool_timeout` 和 `pool_recycle` |
| `hooks/_common.py` | 写操作加重试（3次，指数退避） |
| `docker-compose.yml` | 新增 Redis 服务，app 改 2 worker |
| `requirements.txt` | 新增 `redis[asyncio]==5.0.8` |
| `.env.example` | 新增 `REDIS_URL` |
