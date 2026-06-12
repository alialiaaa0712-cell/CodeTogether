# CodeTogether 团队级部署实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 CodeTogether 添加 API Key 认证、git remote 自动匹配项目、Docker 云端部署支持，使多名团队成员的 Agent 可以接入同一个共享服务器。

**Architecture:** 新增 `ApiKey` 数据表和 `server/routers/auth.py`，通过 FastAPI 依赖注入在所有写端点添加认证；`POST /agents` 接收 `repo_url` 字段，服务端自动匹配或创建 Project；hooks 在每次请求中附加 `Authorization` 头和 `repo_url`；Docker Compose 将服务和 MySQL 打包，支持一键云端部署。

**Tech Stack:** FastAPI, SQLAlchemy, PyMySQL, Docker, docker-compose, nginx

---

## 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `server/models.py` | 新增 `ApiKey` 模型；`Session` 新增 `user_label` 字段 |
| 修改 | `server/schemas.py` | 新增 `ApiKeyOut`、`ApiKeyCreate`；`SessionCreate` 加 `repo_url` |
| 新增 | `server/routers/auth.py` | `get_current_key` 依赖、`/admin/keys` 端点 |
| 修改 | `server/routers/agents.py` | `POST /agents` 接收 `repo_url`，用 git remote 匹配/创建 Project；`_ensure_project_for_cwd` 优先按 `repo_url` 匹配 |
| 修改 | `server/routers/events.py` | 添加 `Depends(get_current_key)` |
| 修改 | `server/routers/chat.py` | 添加 `Depends(get_current_key)` |
| 修改 | `server/routers/memory.py` | 添加 `Depends(get_current_key)` |
| 修改 | `server/main.py` | 注册 auth router；startup 时从 `ADMIN_KEY` 环境变量写入首个 admin key |
| 修改 | `hooks/_common.py` | 所有请求头加 `Authorization: Bearer <CODETOGETHER_API_KEY>`；`ensure_session` 传 `repo_url` |
| 修改 | `hooks/pre_tool.py` | `ensure_session` 调用传入 `repo_url`（从 `git remote` 读取）|
| 修改 | `hooks/stop.py` | `ensure_session` 调用传入 `repo_url` |
| 新增 | `Dockerfile` | 镜像构建 |
| 新增 | `docker-compose.yml` | app + db 两个服务 |
| 新增 | `nginx.conf` | 反向代理配置 |
| 修改 | `.env.example` | 增加 `CODETOGETHER_API_KEY`、`ADMIN_KEY`、`MYSQL_ROOT_PASSWORD` |
| 修改 | `tests/conftest.py` | 提供 `auth_headers` fixture，绕过认证 |
| 修改 | `tests/test_agents.py` | 所有请求加 `auth_headers`；补充 `repo_url` 匹配测试 |

---

## Task 1：ApiKey 数据模型

**Files:**
- Modify: `server/models.py`
- Modify: `server/schemas.py`

- [ ] **Step 1：在 `server/models.py` 末尾新增 `ApiKey` 模型，同时在 `Session` 添加 `user_label` 字段**

```python
# server/models.py 中 Session 类内新增字段（在 notes 字段后）
user_label = Column(String(128), nullable=True)
```

```python
# server/models.py 末尾新增
class ApiKey(Base):
    """API Key 表：存储团队成员认证凭证的哈希值。"""
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, default=_uuid)
    key_hash = Column(String(64), nullable=False, unique=True)
    label = Column(String(128), nullable=False)
    is_admin = Column(Integer, nullable=False, default=0)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(Double, default=time.time)
```

- [ ] **Step 2：在 `server/schemas.py` 新增 Key 相关 schema，并在 `SessionCreate` 加 `repo_url`**

在 `SessionCreate` 类中新增：
```python
repo_url: Optional[str] = None
```

在 `SessionOut` 类中新增：
```python
user_label: Optional[str] = None
```

在文件末尾新增：
```python
class ApiKeyCreate(BaseModel):
    label: str
    is_admin: bool = False


class ApiKeyOut(BaseModel):
    id: str
    label: str
    is_admin: bool
    is_active: bool
    created_at: float

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def coerce_bools(cls, data: Any) -> Any:
        """SQLite 将 BOOL 存为 0/1 整数，统一转为 Python bool。"""
        if hasattr(data, "is_admin"):
            object.__setattr__(data, "is_admin", bool(data.is_admin))
            object.__setattr__(data, "is_active", bool(data.is_active))
        return data
```

- [ ] **Step 3：运行测试确保现有测试不受影响**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
python -m pytest tests/ -x -q 2>&1 | tail -20
```

预期：所有测试通过（schema 字段新增不破坏旧路径）

- [ ] **Step 4：提交**

```bash
git add server/models.py server/schemas.py
git commit -m "feat: ApiKey 数据模型和 Schema"
```

---

## Task 2：认证依赖和 /admin/keys 端点

**Files:**
- Create: `server/routers/auth.py`
- Modify: `server/main.py`

- [ ] **Step 1：编写认证路由的失败测试**

在 `tests/test_agents.py` 开头找到 import 部分后，新建 `tests/test_auth.py`：

```python
import os
os.environ["TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient
from server.main import app


@pytest.fixture
def client_no_auth(engine):
    from sqlalchemy.orm import sessionmaker
    from server.database import get_db
    TestingSessionLocal = sessionmaker(bind=engine)
    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_post_events_requires_auth(client_no_auth):
    """无 key 时写事件应返回 401。"""
    resp = client_no_auth.post("/events", json={
        "session_id": "s1", "type": "pre_tool"
    })
    assert resp.status_code == 401


def test_admin_create_key(client_no_auth):
    """admin key 可创建新 key。"""
    import os
    admin_key = os.environ.get("ADMIN_KEY", "ct-testadminkey00000000000000000000000000000000000000000000000000000")
    resp = client_no_auth.post(
        "/admin/keys",
        json={"label": "alice"},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "key" in data
    assert data["key"].startswith("ct-")


def test_non_admin_cannot_create_key(client_no_auth):
    """普通 key 调用 /admin/keys 应返回 403。"""
    import os, hashlib
    from server.database import get_db
    from server.models import ApiKey

    plain = "ct-regularkey000000000000000000000000000000000000000000000000000000"
    key_hash = hashlib.sha256(plain.encode()).hexdigest()

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    db.add(ApiKey(key_hash=key_hash, label="regular", is_admin=0, is_active=1))
    db.commit()

    resp = client_no_auth.post(
        "/admin/keys",
        json={"label": "bob"},
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert resp.status_code == 403
```

- [ ] **Step 2：运行测试，确认失败**

```bash
python -m pytest tests/test_auth.py -x -q 2>&1 | tail -20
```

预期：FAIL（`/events` 目前无认证，返回 422 而非 401；`/admin/keys` 不存在）

- [ ] **Step 3：创建 `server/routers/auth.py`**

```python
from __future__ import annotations

import hashlib
import os
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session as DBSession
from typing import List

from server.database import get_db
from server.models import ApiKey
from server.schemas import ApiKeyCreate, ApiKeyOut

router = APIRouter(prefix="/admin", tags=["admin"])

_bearer = HTTPBearer(auto_error=False)

_EXEMPT_PATHS = {"/", "/ws"}
_EXEMPT_PREFIXES = ("/mobile",)


def _hash_key(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


def _generate_key() -> str:
    return "ct-" + secrets.token_hex(32)


def get_current_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: DBSession = Depends(get_db),
) -> ApiKey:
    """
    验证请求的 Bearer Token，返回对应的 ApiKey 记录。

    参数:
        request: 当前请求对象。
        credentials: HTTP Bearer 凭证。
        db: 数据库会话。

    返回值:
        通过验证的 ApiKey ORM 对象。
    """
    path = request.url.path
    if path in _EXEMPT_PATHS or any(path.startswith(p) for p in _EXEMPT_PREFIXES):
        return None  # type: ignore

    if not credentials:
        raise HTTPException(status_code=401, detail="missing api key")

    key_hash = _hash_key(credentials.credentials)
    api_key = db.query(ApiKey).filter(
        ApiKey.key_hash == key_hash,
        ApiKey.is_active == 1,
    ).first()
    if not api_key:
        raise HTTPException(status_code=401, detail="invalid api key")
    return api_key


def get_admin_key(key: ApiKey = Depends(get_current_key)) -> ApiKey:
    """
    确保当前 key 拥有 admin 权限。

    参数:
        key: 已验证的 ApiKey 对象。

    返回值:
        ApiKey 对象（is_admin=True）。
    """
    if not key or not key.is_admin:
        raise HTTPException(status_code=403, detail="admin key required")
    return key


@router.post("/keys")
def create_key(
    body: ApiKeyCreate,
    db: DBSession = Depends(get_db),
    _: ApiKey = Depends(get_admin_key),
):
    """
    创建新 API Key，返回明文（仅此一次）。

    参数:
        body: 包含 label 和 is_admin 的请求体。
        db: 数据库会话。

    返回值:
        含 key（明文）和 id 的字典。
    """
    plain = _generate_key()
    api_key = ApiKey(
        key_hash=_hash_key(plain),
        label=body.label,
        is_admin=int(body.is_admin),
        is_active=1,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return {"id": api_key.id, "key": plain, "label": api_key.label}


@router.get("/keys", response_model=List[ApiKeyOut])
def list_keys(
    db: DBSession = Depends(get_db),
    _: ApiKey = Depends(get_admin_key),
):
    """列出所有 API Key（不含明文）。"""
    return db.query(ApiKey).all()


@router.delete("/keys/{key_id}", status_code=204)
def delete_key(
    key_id: str,
    db: DBSession = Depends(get_db),
    _: ApiKey = Depends(get_admin_key),
):
    """禁用指定 API Key。"""
    api_key = db.get(ApiKey, key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="key not found")
    api_key.is_active = 0
    db.commit()


def seed_admin_key(db: DBSession) -> None:
    """
    若 `ADMIN_KEY` 环境变量存在且 api_keys 表为空，写入首个 admin key。

    参数:
        db: 数据库会话。

    返回值:
        无。
    """
    plain = os.getenv("ADMIN_KEY")
    if not plain:
        return
    if db.query(ApiKey).count() > 0:
        return
    db.add(ApiKey(
        key_hash=_hash_key(plain),
        label="admin",
        is_admin=1,
        is_active=1,
    ))
    db.commit()
```

- [ ] **Step 4：在 `server/main.py` 注册 auth router，并在 startup 中调用 `seed_admin_key`**

在 `server/main.py` 的 import 区追加：
```python
from server.routers import auth as auth_router
from server.routers.auth import seed_admin_key
```

在 `_run_startup_migrations()` 函数末尾（`_activate_short_pending_memories()` 调用之后）追加：
```python
    db = SessionLocal()
    try:
        seed_admin_key(db)
    finally:
        db.close()
```

在 `app.include_router(memory.router)` 后追加：
```python
app.include_router(auth_router.router)
```

- [ ] **Step 5：运行认证测试，确认通过**

```bash
ADMIN_KEY="ct-testadminkey00000000000000000000000000000000000000000000000000000" \
python -m pytest tests/test_auth.py -x -q 2>&1 | tail -20
```

预期：3 个测试全部 PASS

- [ ] **Step 6：提交**

```bash
git add server/routers/auth.py server/main.py tests/test_auth.py
git commit -m "feat: API Key 认证系统和 /admin/keys 端点"
```

---

## Task 3：为所有写端点添加认证

**Files:**
- Modify: `server/routers/events.py`
- Modify: `server/routers/chat.py`
- Modify: `server/routers/memory.py`
- Modify: `server/routers/agents.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1：更新 `tests/conftest.py`，提供 `auth_headers` fixture**

在 `conftest.py` 末尾追加：
```python
import hashlib
from server.models import ApiKey as ApiKeyModel

TEST_API_KEY = "ct-testkey000000000000000000000000000000000000000000000000000000000"

@pytest.fixture(autouse=True)
def seed_test_api_key(db):
    """每个测试自动写入测试 key，确保认证通过。"""
    key_hash = hashlib.sha256(TEST_API_KEY.encode()).hexdigest()
    existing = db.query(ApiKeyModel).filter(ApiKeyModel.key_hash == key_hash).first()
    if not existing:
        db.add(ApiKeyModel(key_hash=key_hash, label="test", is_admin=1, is_active=1))
        db.commit()

@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {TEST_API_KEY}"}
```

- [ ] **Step 2：在 `server/routers/events.py` 的写端点添加认证**

在 `events.py` import 区追加：
```python
from server.routers.auth import get_current_key
from server.models import ApiKey
```

在 `POST /events` 的函数签名中追加依赖：
```python
async def create_event(..., _key: ApiKey = Depends(get_current_key)):
```

- [ ] **Step 3：在 `server/routers/chat.py` 的写端点添加认证**

在 `chat.py` import 区追加：
```python
from server.routers.auth import get_current_key
from server.models import ApiKey
```

在 `POST /chat` 和 `POST /chat/{session_id}/poll` 函数签名中追加：
```python
_key: ApiKey = Depends(get_current_key)
```

- [ ] **Step 4：在 `server/routers/memory.py` 的写端点添加认证**

在 `memory.py` import 区追加：
```python
from server.routers.auth import get_current_key
from server.models import ApiKey
```

在 `POST /memory`、`PATCH /memory/{id}`、`POST /memory/search`、`POST /memory/{id}/feedback` 函数签名中追加：
```python
_key: ApiKey = Depends(get_current_key)
```

- [ ] **Step 5：在 `server/routers/agents.py` 的写端点添加认证，并传入 `user_label`**

在 `agents.py` import 区追加：
```python
from server.routers.auth import get_current_key
from server.models import ApiKey
```

在 `POST /agents`、`PATCH /{session_id}/status`、`PATCH /{session_id}/parent`、`PATCH /{session_id}/model`、`PATCH /{session_id}/notes`、`DELETE /{session_id}` 函数签名中追加：
```python
_key: ApiKey = Depends(get_current_key)
```

在 `create_session` 内创建 `SessionModel` 时，传入 `user_label`：
```python
session = SessionModel(**session_payload, project_id=project_id, user_label=_key.label if _key else None)
```

- [ ] **Step 6：更新现有测试，为所有请求加上 `auth_headers`**

在各测试文件（`test_agents.py`, `test_events.py`, `test_chat.py`, `test_memory.py`, `test_codetogether.py`）中，找到直接调用 `client.post/patch/delete` 的地方，加上：
```python
headers=auth_headers
```

或者利用 `conftest.py` 的 `auth_headers` fixture 注入：
```python
def test_xxx(client, auth_headers):
    client.post("/agents", json={...}, headers=auth_headers)
```

- [ ] **Step 7：运行全部测试**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -30
```

预期：全部通过

- [ ] **Step 8：提交**

```bash
git add server/routers/events.py server/routers/chat.py server/routers/memory.py \
        server/routers/agents.py tests/conftest.py tests/
git commit -m "feat: 为所有写端点添加 API Key 认证"
```

---

## Task 4：git remote 自动匹配项目

**Files:**
- Modify: `server/routers/agents.py`
- Modify: `server/schemas.py`（已在 Task 1 中加了 `repo_url`）

- [ ] **Step 1：编写 repo_url 匹配的失败测试**

在 `tests/test_agents.py` 末尾追加：
```python
def test_create_session_with_repo_url_creates_project(client, db, auth_headers):
    """传入 repo_url 时，服务端应自动创建对应 Project 并绑定 Session。"""
    resp = client.post("/agents", json={
        "id": "sess-repo-1",
        "cwd": "/home/alice/my-repo",
        "repo_url": "https://github.com/team/my-repo.git",
    }, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] is not None

    # 再次创建同 repo_url 的 session，应复用同一个 project
    resp2 = client.post("/agents", json={
        "id": "sess-repo-2",
        "cwd": "/home/bob/my-repo",
        "repo_url": "https://github.com/team/my-repo.git",
    }, headers=auth_headers)
    assert resp2.status_code == 200
    assert resp2.json()["project_id"] == data["project_id"]
```

- [ ] **Step 2：运行，确认失败**

```bash
python -m pytest tests/test_agents.py::test_create_session_with_repo_url_creates_project -x -q 2>&1 | tail -10
```

预期：FAIL（`repo_url` 字段尚未在服务端处理）

- [ ] **Step 3：修改 `server/routers/agents.py` 的 `_ensure_project_for_session`，优先按 `repo_url` 匹配**

将 `_ensure_project_for_session` 替换为：
```python
def _ensure_project_for_session(body: SessionCreate, db: DBSession) -> Optional[str]:
    """
    为会话解析 project_id：优先按 repo_url 精确匹配，无则按 cwd 回退。

    参数:
        body: 创建会话请求体。
        db: 数据库会话。

    返回值:
        project_id 字符串，或 None。
    """
    if body.project_id:
        return body.project_id
    if body.repo_url:
        return _ensure_project_for_repo_url(body.repo_url, db)
    return _ensure_project_for_cwd(body.cwd, db)
```

在 `_ensure_project_for_cwd` 函数前新增：
```python
def _ensure_project_for_repo_url(repo_url: str, db: DBSession) -> Optional[str]:
    """
    按 git remote URL 精确匹配项目，未命中时自动创建。

    参数:
        repo_url: git remote origin URL，作为全局唯一项目键。
        db: 数据库会话。

    返回值:
        project_id 字符串。
    """
    repo_url = repo_url.strip()
    existing = db.query(ProjectModel).filter(ProjectModel.repo_url == repo_url).first()
    if existing:
        return existing.id
    name = PurePath(repo_url.rstrip("/").rstrip(".git")).name or repo_url
    project = ProjectModel(name=name, repo_url=repo_url)
    db.add(project)
    db.flush()
    return project.id
```

- [ ] **Step 4：运行测试，确认通过**

```bash
python -m pytest tests/test_agents.py -x -q 2>&1 | tail -10
```

预期：全部通过

- [ ] **Step 5：提交**

```bash
git add server/routers/agents.py
git commit -m "feat: 按 git remote URL 自动匹配/创建 Project"
```

---

## Task 5：hooks 支持认证和 repo_url

**Files:**
- Modify: `hooks/_common.py`
- Modify: `hooks/pre_tool.py`
- Modify: `hooks/stop.py`

- [ ] **Step 1：修改 `hooks/_common.py`，所有请求附带 Authorization 头**

在文件顶部 `SERVER` 定义后追加：
```python
API_KEY = os.environ.get("CODETOGETHER_API_KEY", "")

def _auth_headers() -> dict:
    """返回带 Authorization 的请求头，无 key 时返回空字典。"""
    if API_KEY:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    return {"Content-Type": "application/json"}
```

将所有 `headers={"Content-Type": "application/json"}` 替换为 `headers=_auth_headers()`。

涉及以下函数：`post_event`、`poll_messages`（GET 请求只需加 auth header）、`memory_search`、`memory_feedback`、`ensure_session`、`post_chat_message`、`mark_stopped`。

`poll_messages` 是 GET 请求，修改为：
```python
req = urllib.request.Request(
    f"{SERVER}/chat/{session_id}/poll",
    headers={"Authorization": f"Bearer {API_KEY}"} if API_KEY else {},
    method="GET",
)
```

- [ ] **Step 2：在 `hooks/_common.py` 的 `ensure_session` 添加 `repo_url` 参数**

将函数签名改为：
```python
def ensure_session(session_id: str, cwd: str = None, repo_url: str = None) -> None:
```

在 `payload` 构建处追加：
```python
if repo_url:
    payload["repo_url"] = repo_url
```

- [ ] **Step 3：添加 `get_repo_url` 工具函数**

在 `_common.py` 末尾追加：
```python
def get_repo_url(cwd: str) -> str:
    """
    获取指定目录的 git remote origin URL。

    参数:
        cwd: 工作目录路径。

    返回值:
        remote URL 字符串；失败时返回空字符串。
    """
    import subprocess
    if not cwd:
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=2,
        )
        return result.stdout.strip()
    except Exception:
        return ""
```

- [ ] **Step 4：修改 `hooks/pre_tool.py`，传入 `repo_url`**

将 `_common.ensure_session(agent_session_id, cwd=cwd)` 替换为：
```python
repo_url = _common.get_repo_url(cwd)
_common.ensure_session(agent_session_id, cwd=cwd, repo_url=repo_url)
```

- [ ] **Step 5：修改 `hooks/stop.py`，传入 `repo_url`**

在 `stop.py` 中找到 `ensure_session` 调用（在 `sync_messages` 或 `main` 函数内），修改为：
```python
repo_url = _common.get_repo_url(cwd)
_common.ensure_session(session_id, cwd=cwd, repo_url=repo_url)
```

- [ ] **Step 6：运行全部测试**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -20
```

预期：全部通过（hooks 的变更无需单独集成测试，现有测试已覆盖 `ensure_session` 接口）

- [ ] **Step 7：提交**

```bash
git add hooks/_common.py hooks/pre_tool.py hooks/stop.py
git commit -m "feat: hooks 携带 API Key 认证头和 repo_url"
```

---

## Task 6：Docker 化和云端部署配置

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `nginx.conf`
- Modify: `.env.example`

- [ ] **Step 1：创建 `Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2：创建 `docker-compose.yml`**

```yaml
services:
  app:
    build: .
    restart: unless-stopped
    environment:
      - DATABASE_URL=mysql+pymysql://root:${MYSQL_ROOT_PASSWORD}@db:3306/codetogether
      - ADMIN_KEY=${ADMIN_KEY}
    depends_on:
      db:
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

volumes:
  mysql_data:
```

- [ ] **Step 3：创建 `nginx.conf`**

```nginx
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

- [ ] **Step 4：更新 `.env.example`**

```bash
# 数据库
DATABASE_URL=mysql+pymysql://root:yourpassword@localhost:3306/codetogether
MYSQL_ROOT_PASSWORD=yourpassword

# 服务器
SERVER_PORT=7878

# 团队部署（云端服务器）
ADMIN_KEY=ct-your-admin-key-here

# 开发机（每位团队成员配置）
CODETOGETHER_SERVER=https://your-server.com
CODETOGETHER_API_KEY=ct-your-personal-key-here
```

- [ ] **Step 5：验证 Docker Compose 语法**

```bash
docker compose config --quiet 2>&1 | head -5
```

预期：无错误输出

- [ ] **Step 6：运行全部测试确认没有回归**

```bash
python -m pytest tests/ -q 2>&1 | tail -10
```

预期：全部通过

- [ ] **Step 7：提交**

```bash
git add Dockerfile docker-compose.yml nginx.conf .env.example
git commit -m "feat: Docker 化和云端部署配置"
```

---

## Task 7：数据库迁移兼容（现有 MySQL 实例）

**Files:**
- Modify: `server/main.py`

- [ ] **Step 1：在 `_ensure_event_columns` 之后添加 `_ensure_auth_columns` 迁移函数**

在 `server/main.py` 中 `_ensure_event_columns` 函数之后插入：
```python
def _ensure_auth_columns() -> None:
    """
    补齐 sessions 表的 user_label 列；对旧实例做兼容迁移。

    参数:
        无。

    返回值:
        无。
    """
    inspector = inspect(engine)
    session_cols = {c["name"] for c in inspector.get_columns("sessions")}
    if "user_label" not in session_cols:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE sessions ADD COLUMN user_label VARCHAR(128)"))
            conn.commit()
```

- [ ] **Step 2：在 `_run_startup_migrations` 中调用该函数**

在 `_run_startup_migrations` 中 `_ensure_event_columns()` 调用后追加：
```python
    _ensure_auth_columns()
```

- [ ] **Step 3：运行全部测试**

```bash
python -m pytest tests/ -q 2>&1 | tail -10
```

预期：全部通过

- [ ] **Step 4：提交**

```bash
git add server/main.py
git commit -m "feat: 迁移 sessions 表添加 user_label 列"
```

---

## 部署流程（文档性步骤，无代码）

完成以上所有 Task 后，部署步骤：

1. 在云服务器上安装 Docker + Docker Compose
2. 克隆仓库，复制 `.env.example` 为 `.env`，填写 `MYSQL_ROOT_PASSWORD` 和 `ADMIN_KEY`
3. `docker compose up -d`
4. 用 `ADMIN_KEY` 调用 `POST /admin/keys` 为每位成员生成 key
5. 每位成员在开发机 `~/.claude/.env` 中配置 `CODETOGETHER_SERVER` 和 `CODETOGETHER_API_KEY`
6. nginx + certbot 配置 HTTPS（参考 `nginx.conf`）
