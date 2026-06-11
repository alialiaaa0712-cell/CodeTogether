# 记忆项目隔离与人工晋升 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 CodeTogether 的记忆系统增加可靠的项目隔离、短期记忆 review 审核流、7 天命中阈值晋升信号，以及从源头减少噪音短期记忆。

**Architecture:** 继续以 `Memory.project_id` 作为项目边界，在服务端统一用 `session_id -> project_id` 解析当前项目，并保留 `cwd` 作为回退。短期记忆命中统计直接保存在 `memories` 表上：`active + short` 在 7 天窗口内命中达到阈值后进入 `review + short`，人工确认后才升为 `active + long`；拒绝则直接删除。提炼链路改为“结论优先 + 服务端规则过滤 + 每个 session 最多 1–3 条”的双层收紧。

**Tech Stack:** FastAPI · SQLAlchemy · MySQL(生产) / SQLite(测试) · APScheduler 3.x · pytest · Mobile Web · 内部 OpenAI-compatible API

---

## 文件结构

| 文件 | 操作 | 说明 |
|------|------|------|
| `server/models.py` | Modify | `Memory` 新增命中与 review 快照字段；必要时保留旧 `rejected` 枚举兼容但不再走业务流转 |
| `server/schemas.py` | Modify | `MemoryOut` 暴露命中字段；`MemoryUpdate` 收紧为启用/晋升用法；必要时新增 `MemoryPromoteRequest` |
| `server/routers/agents.py` | Modify | 创建 session 时尽量落明确 `project_id`；提炼输入改为“结论视角”；限制每个 session 最多落 1–3 条 |
| `server/routers/memory.py` | Modify | 项目范围解析、`/memory/search` 命中统计与 review 触发、`DELETE /memory/{id}`、列表过滤 |
| `server/services/extractor.py` | Modify | 收紧 prompt，新增服务端规则过滤函数，拒绝操作流水/一次性现象/代码常识 |
| `server/services/housekeeping.py` | Modify | 去掉自动 short→long 语义，只保留命中窗口重置等轻量维护 |
| `server/main.py` | Modify | 为 `memories` 新字段补 MySQL 启动迁移；保留/调整 housekeeping 定时任务 |
| `hooks/_common.py` | Modify | `search_memory()` 支持 `session_id` 和 `project_id` 回退；删除仍保留 `flag_memory_for_review()` 兼容 |
| `hooks/pre_tool.py` | Modify | 调用搜索时优先传 `session_id`，仅在服务端缺项目时回退 `cwd` |
| `mobile/index.html` | Modify | 增加项目范围切换和 review 分区入口 |
| `mobile/app.js` | Modify | 默认当前项目范围、review 队列、长期晋升与删除动作、展示命中统计 |
| `mobile/style.css` | Modify | 范围切换、review 卡片、命中信息样式 |
| `tests/test_agents.py` | Modify | session 创建时的项目绑定与提炼入口行为 |
| `tests/test_memory.py` | Modify | 项目隔离、命中统计、review 触发、启用/晋升/删除 |
| `tests/test_hooks.py` | Modify | hook 搜索参数优先级与 URL 生成 |
| `tests/test_mobile.py` | Modify | 默认当前项目、全部项目切换、review UI 操作 |
| `tests/test_housekeeping.py` | Modify | housekeeping 不再自动晋升，只重置过期命中窗口 |
| `tests/test_extractor.py` | Create | 提炼过滤规则与 1–3 条上限 |

---

### Task 1: 建立项目边界与记忆命中字段

**Files:**
- Modify: `server/models.py`
- Modify: `server/schemas.py`
- Modify: `server/routers/agents.py`
- Modify: `server/main.py`
- Modify: `tests/test_agents.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1: 写失败测试，锁定 session 会绑定项目、Memory 会暴露命中字段**

在 `tests/test_agents.py` 追加：

```python
def test_create_session_infers_project_from_cwd(client):
    resp = client.post(
        "/agents",
        json={"id": "sess-proj-1", "cwd": "/Users/qinepan/Desktop/search/CodeTogether"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] is not None
```

在 `tests/test_memory.py` 追加：

```python
def test_memory_defaults_include_hit_tracking_fields(client):
    resp = client.post(
        "/memory",
        json={"project_id": "proj-1", "title": "规则", "content": "某接口必须带 session_id"},
    )
    data = resp.json()
    assert data["hit_count_7d"] == 0
    assert data["last_hit_at"] is None
    assert data["review_reason"] is None
    assert data["review_hit_count"] is None
```

- [ ] **Step 2: 运行失败测试，确认现在没有这些能力**

Run:

```bash
pytest tests/test_agents.py::test_create_session_infers_project_from_cwd tests/test_memory.py::test_memory_defaults_include_hit_tracking_fields -v
```

Expected: FAIL，表现为 `project_id` 为空或响应缺少命中字段。

- [ ] **Step 3: 修改 `server/models.py`，给 Memory 增加命中与 review 快照字段**

将 `Memory` 类扩展为：

```python
class Memory(Base):
    """知识条目表：Agent 运行后提炼的项目知识。"""
    __tablename__ = "memories"

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    title = Column(String(512), nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(String(512))
    status = Column(Enum("pending", "active", "rejected", "review"), default="pending")
    tier = Column(Enum("short", "long"), default="short", nullable=False)
    hit_count_7d = Column(Integer, nullable=False, default=0)
    last_hit_at = Column(Double)
    review_reason = Column(String(64))
    review_hit_count = Column(Integer)
    updated_at = Column(Double, default=time.time)
    source_session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    created_at = Column(Double, default=time.time)
    activated_at = Column(Double)
```

并在 import 中补上 `Integer`：

```python
from sqlalchemy import BigInteger, Column, Double, Enum, ForeignKey, Index, Integer, String, Text
```

- [ ] **Step 4: 修改 `server/schemas.py`，暴露新字段并收紧更新请求**

将 `MemoryOut` 改为：

```python
class MemoryOut(BaseModel):
    id: str
    project_id: Optional[str] = None
    title: str
    content: str
    tags: Optional[str] = None
    status: str
    tier: str
    source_session_id: Optional[str] = None
    created_at: float
    activated_at: Optional[float] = None
    updated_at: float
    hit_count_7d: int
    last_hit_at: Optional[float] = None
    review_reason: Optional[str] = None
    review_hit_count: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
```

将 `MemoryUpdate` 改为：

```python
class MemoryUpdate(BaseModel):
    status: Optional[Literal["active"]] = None
    tier: Optional[Literal["long"]] = None
```
```

并新增一个显式晋升请求体：

```python
class MemoryPromoteRequest(BaseModel):
    tier: Literal["long"] = "long"
    status: Literal["active"] = "active"
```

- [ ] **Step 5: 修改 `server/routers/agents.py`，在创建 session 时尽量绑定项目**

在文件中新增两个 helper：

```python
def _project_name_from_cwd(cwd: Optional[str]) -> Optional[str]:
    if not cwd:
        return None
    return cwd.rstrip("/").split("/")[-1] or None


def _resolve_project_id(db: DBSession, explicit_project_id: Optional[str], cwd: Optional[str]) -> Optional[str]:
    if explicit_project_id:
        return explicit_project_id
    project_name = _project_name_from_cwd(cwd)
    if not project_name:
        return None
    project = db.query(ProjectModel).filter(ProjectModel.name == project_name).first()
    if project:
        return project.id
    project = ProjectModel(name=project_name)
    db.add(project)
    db.flush()
    return project.id
```

并把 `create_session()` 里的建模改为：

```python
resolved_project_id = _resolve_project_id(db, body.project_id, body.cwd)
session = SessionModel(**(body.model_dump() | {"project_id": resolved_project_id}))
```

需要在 imports 中补：

```python
from server.models import Project as ProjectModel
```

- [ ] **Step 6: 修改 `server/main.py`，给 MySQL 生产库补新增列**

在现有 `if not _is_sqlite:` 的迁移段后追加：

```python
_mem_cols = [c["name"] for c in _insp.get_columns("memories")]
_memory_alters = [
    ("hit_count_7d", "ALTER TABLE memories ADD COLUMN hit_count_7d INT NOT NULL DEFAULT 0"),
    ("last_hit_at", "ALTER TABLE memories ADD COLUMN last_hit_at DOUBLE NULL"),
    ("review_reason", "ALTER TABLE memories ADD COLUMN review_reason VARCHAR(64) NULL"),
    ("review_hit_count", "ALTER TABLE memories ADD COLUMN review_hit_count INT NULL"),
]
for col_name, ddl in _memory_alters:
    if col_name not in _mem_cols:
        with engine.connect() as _conn:
            _conn.execute(text(ddl))
            _conn.commit()
```

- [ ] **Step 7: 运行测试，确认字段与项目绑定已就绪**

Run:

```bash
pytest tests/test_agents.py::test_create_session_infers_project_from_cwd tests/test_memory.py::test_memory_defaults_include_hit_tracking_fields -v
```

Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add server/models.py server/schemas.py server/routers/agents.py server/main.py tests/test_agents.py tests/test_memory.py
git commit -m "feat: add project-scoped memory metadata"
```

---

### Task 2: 实现 memory API 的项目隔离、命中统计与 review 触发

**Files:**
- Modify: `server/routers/memory.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1: 写失败测试，覆盖项目隔离、7 天命中和 review 触发**

在 `tests/test_memory.py` 追加：

```python
def test_search_memory_filters_by_session_project(client):
    client.post("/agents", json={"id": "sess-a", "cwd": "/tmp/project-a"})
    client.post("/agents", json={"id": "sess-b", "cwd": "/tmp/project-b"})

    mem_a = client.post("/memory", json={
        "project_id": client.get("/agents").json()[0]["project_id"],
        "title": "A 规则",
        "content": "project A 必须走路径 A",
    }).json()
    mem_b = client.post("/memory", json={
        "project_id": client.get("/agents").json()[1]["project_id"],
        "title": "B 规则",
        "content": "project B 必须走路径 B",
    }).json()
    client.patch(f"/memory/{mem_a['id']}", json={"status": "active"})
    client.patch(f"/memory/{mem_b['id']}", json={"status": "active"})

    resp = client.get("/memory/search?q=必须&session_id=sess-a")
    ids = [item["id"] for item in resp.json()]
    assert mem_a["id"] in ids
    assert mem_b["id"] not in ids


def test_short_memory_hit_count_rolls_and_enters_review(client, monkeypatch):
    client.post("/agents", json={"id": "sess-hit", "cwd": "/tmp/project-hit"})
    project_id = client.get("/agents").json()[0]["project_id"]
    memory = client.post("/memory", json={
        "project_id": project_id,
        "title": "约束",
        "content": "这个接口必须带 token",
    }).json()
    client.patch(f"/memory/{memory['id']}", json={"status": "active"})

    monkeypatch.setattr("server.routers.memory._REVIEW_HIT_THRESHOLD", 2)
    first = client.get("/memory/search?q=必须&session_id=sess-hit").json()[0]
    assert first["hit_count_7d"] == 1
    assert first["status"] == "active"

    second = client.get("/memory/search?q=必须&session_id=sess-hit").json()[0]
    assert second["hit_count_7d"] == 2
    assert second["status"] == "review"
    assert second["review_reason"] == "hit_threshold"
    assert second["review_hit_count"] == 2


def test_delete_memory_removes_pending_or_review_item(client):
    memory = client.post("/memory", json={"title": "待删", "content": "不要保留"}).json()
    resp = client.delete(f"/memory/{memory['id']}")
    assert resp.status_code == 204
    assert client.get("/memory?status=pending").json() == []
```

- [ ] **Step 2: 运行测试，确认现在还没有这些行为**

Run:

```bash
pytest tests/test_memory.py::test_search_memory_filters_by_session_project tests/test_memory.py::test_short_memory_hit_count_rolls_and_enters_review tests/test_memory.py::test_delete_memory_removes_pending_or_review_item -v
```

Expected: FAIL。

- [ ] **Step 3: 在 `server/routers/memory.py` 中加入项目解析与命中统计 helper**

在文件顶部新增：

```python
_REVIEW_HIT_THRESHOLD = 3
_7_DAYS = 7 * 86400


def _resolve_project_id(db: DBSession, session_id: Optional[str], fallback_project_id: Optional[str]) -> Optional[str]:
    if session_id:
        session = db.get(SessionModel, session_id)
        if session and session.project_id:
            return session.project_id
    return fallback_project_id


def _bump_short_memory_hit(memory: MemoryModel, now: float) -> None:
    if memory.last_hit_at is None or now - memory.last_hit_at > _7_DAYS:
        memory.hit_count_7d = 1
    else:
        memory.hit_count_7d += 1
    memory.last_hit_at = now
    memory.updated_at = now
    if memory.hit_count_7d >= _REVIEW_HIT_THRESHOLD and memory.status == "active" and memory.tier == "short":
        memory.status = "review"
        memory.review_reason = "hit_threshold"
        memory.review_hit_count = memory.hit_count_7d
```

需要补 import：

```python
from server.models import Memory as MemoryModel, Session as SessionModel
```

- [ ] **Step 4: 修改 `GET /memory/search`，优先按 session 项目过滤并更新短期命中**

把 search 签名改成：

```python
@router.get("/search", response_model=List[MemoryOut])
def search_memories(
    q: str,
    project_id: Optional[str] = None,
    session_id: Optional[str] = None,
    db: DBSession = Depends(get_db),
):
```

解析项目时用：

```python
resolved_project_id = _resolve_project_id(db, session_id, project_id)
```

在 `_query()` 中继续限制：

```python
if resolved_project_id:
    qr = qr.filter(MemoryModel.project_id == resolved_project_id)
```

返回前更新命中：

```python
now = time.time()
changed = False
for memory in results:
    if memory.status == "active" and memory.tier == "short":
        _bump_short_memory_hit(memory, now)
        changed = True
if changed:
    db.commit()
    for memory in results:
        db.refresh(memory)
```

- [ ] **Step 5: 修改 `PATCH /memory/{id}` 与新增 `DELETE /memory/{id}`**

将 `update_memory()` 收紧为两种合法路径：

```python
if body.status == "active":
    if memory.status != "pending":
        raise HTTPException(status_code=422, detail="仅 pending 记忆可启用")
    memory.status = "active"
    memory.activated_at = now
    memory.updated_at = now
elif body.tier == "long":
    if memory.status != "review" or memory.tier != "short":
        raise HTTPException(status_code=422, detail="仅 review/short 记忆可晋升为长期")
    memory.tier = "long"
    memory.status = "active"
    memory.updated_at = now
else:
    raise HTTPException(status_code=400, detail="仅支持启用短期记忆或将 review 短期记忆晋升为长期")
```

新增删除路由：

```python
@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: str, db: DBSession = Depends(get_db)):
    memory = db.get(MemoryModel, memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="memory not found")
    db.delete(memory)
    db.commit()
```

- [ ] **Step 6: 运行测试，确认项目隔离、命中统计与删除路径正确**

Run:

```bash
pytest tests/test_memory.py::test_search_memory_filters_by_session_project tests/test_memory.py::test_short_memory_hit_count_rolls_and_enters_review tests/test_memory.py::test_delete_memory_removes_pending_or_review_item -v
```

Expected: PASS。

- [ ] **Step 7: 扩展回归测试，覆盖 7 天窗口重置和 review 晋升**

在 `tests/test_memory.py` 追加：

```python
def test_short_memory_hit_window_resets_after_7_days(client, monkeypatch):
    client.post("/agents", json={"id": "sess-reset", "cwd": "/tmp/project-reset"})
    project_id = client.get("/agents").json()[0]["project_id"]
    memory = client.post("/memory", json={
        "project_id": project_id,
        "title": "边界",
        "content": "某命令不能跨项目执行",
    }).json()
    client.patch(f"/memory/{memory['id']}", json={"status": "active"})

    from server.database import SessionLocal
    db = SessionLocal()
    try:
        row = db.get(MemoryModel, memory["id"])
        row.hit_count_7d = 5
        row.last_hit_at = 1000.0
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr("server.routers.memory.time.time", lambda: 1000.0 + 8 * 86400)
    data = client.get("/memory/search?q=不能&session_id=sess-reset").json()[0]
    assert data["hit_count_7d"] == 1


def test_promote_review_short_to_active_long(client, monkeypatch):
    client.post("/agents", json={"id": "sess-promote", "cwd": "/tmp/project-promote"})
    project_id = client.get("/agents").json()[0]["project_id"]
    memory = client.post("/memory", json={
        "project_id": project_id,
        "title": "规则",
        "content": "插件只能在主项目中加载",
    }).json()
    client.patch(f"/memory/{memory['id']}", json={"status": "active"})

    monkeypatch.setattr("server.routers.memory._REVIEW_HIT_THRESHOLD", 1)
    client.get("/memory/search?q=只能&session_id=sess-promote")

    resp = client.patch(f"/memory/{memory['id']}", json={"tier": "long"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
    assert resp.json()["tier"] == "long"
```

Run:

```bash
pytest tests/test_memory.py -v
```

Expected: memory 相关测试全部 PASS。

- [ ] **Step 8: Commit**

```bash
git add server/routers/memory.py tests/test_memory.py
git commit -m "feat: scope memory search by project and add review promotion"
```

---

### Task 3: 更新 housekeeping，使其不再自动晋升长期记忆

**Files:**
- Modify: `server/services/housekeeping.py`
- Modify: `server/main.py`
- Modify: `tests/test_housekeeping.py`

- [ ] **Step 1: 写失败测试，锁定 housekeeping 不再把 short 自动升 long**

将 `tests/test_housekeeping.py` 改成以下核心断言：

```python
def test_housekeeping_resets_stale_short_hit_window(db_session):
    memory = MemoryModel(
        title="规则",
        content="必须携带 token",
        status="active",
        tier="short",
        hit_count_7d=4,
        last_hit_at=1000.0,
        updated_at=1000.0,
    )
    db_session.add(memory)
    db_session.commit()

    with mock.patch("server.services.housekeeping.time.time", return_value=1000.0 + 8 * 86400):
        run_memory_housekeeping(db_session)

    db_session.refresh(memory)
    assert memory.tier == "short"
    assert memory.hit_count_7d == 0


def test_housekeeping_does_not_promote_short_to_long(db_session):
    memory = MemoryModel(
        title="边界",
        content="不能跨项目注入",
        status="active",
        tier="short",
        updated_at=1000.0,
    )
    db_session.add(memory)
    db_session.commit()

    with mock.patch("server.services.housekeeping.time.time", return_value=1000.0 + 30 * 86400):
        run_memory_housekeeping(db_session)

    db_session.refresh(memory)
    assert memory.tier == "short"
```

- [ ] **Step 2: 运行测试，确认当前逻辑仍会自动 short→long**

Run:

```bash
pytest tests/test_housekeeping.py -v
```

Expected: FAIL，尤其是 `tier == "short"` 断言失败。

- [ ] **Step 3: 修改 `server/services/housekeeping.py`，只做轻量命中窗口维护**

将函数改为：

```python
_7_DAYS = 7 * 86400


def run_memory_housekeeping(db: DBSession) -> None:
    now = time.time()

    stale_short = (
        db.query(MemoryModel)
        .filter(
            MemoryModel.status == "active",
            MemoryModel.tier == "short",
            MemoryModel.last_hit_at.isnot(None),
            MemoryModel.last_hit_at < now - _7_DAYS,
            MemoryModel.hit_count_7d > 0,
        )
        .all()
    )
    for mem in stale_short:
        mem.hit_count_7d = 0
        mem.review_reason = None
        mem.review_hit_count = None

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("housekeeping: 提交失败，已回滚")
```

不要再保留任何 `mem.tier = "long"` 逻辑。

- [ ] **Step 4: 运行测试，确认 housekeeping 只重置窗口，不再自动晋升**

Run:

```bash
pytest tests/test_housekeeping.py -v
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add server/services/housekeeping.py tests/test_housekeeping.py
git commit -m "refactor: stop auto-promoting short memories"
```

---

### Task 4: 收紧 hook 搜索参数与提炼准入规则

**Files:**
- Modify: `hooks/_common.py`
- Modify: `hooks/pre_tool.py`
- Modify: `server/services/extractor.py`
- Modify: `server/routers/agents.py`
- Modify: `tests/test_hooks.py`
- Create: `tests/test_extractor.py`

- [ ] **Step 1: 写失败测试，锁定 hook 优先传 session_id 且提炼过滤噪音**

在 `tests/test_hooks.py` 追加：

```python
def test_search_memory_includes_session_id_and_project_fallback():
    m = import_common()
    with mock.patch("urllib.request.urlopen") as mock_open:
        response = mock.MagicMock()
        response.read.return_value = json.dumps([]).encode()
        mock_open.return_value = response
        m.search_memory("pytest", project_id="proj-1", session_id="sess-1")
    req = mock_open.call_args[0][0]
    assert "session_id=sess-1" in req.full_url
    assert "project_id=proj-1" in req.full_url
```

创建 `tests/test_extractor.py`：

```python
from server.services.extractor import _filter_memory_candidates


def test_filter_memory_candidates_keeps_project_constraints():
    items = [{"title": "约束", "content": "MySQL 5.7 不能使用 ADD COLUMN IF NOT EXISTS", "tags": "mysql"}]
    result = _filter_memory_candidates(items)
    assert len(result) == 1


def test_filter_memory_candidates_drops_operational_chatter():
    items = [
        {"title": "操作", "content": "运行了 pytest tests/test_hooks.py 并通过", "tags": "test"},
        {"title": "常识", "content": "server/main.py 是 FastAPI 入口文件", "tags": "code"},
    ]
    result = _filter_memory_candidates(items)
    assert result == []
```

- [ ] **Step 2: 运行测试，确认当前 hook 和 extractor 还没有这些约束**

Run:

```bash
pytest tests/test_hooks.py::test_search_memory_includes_session_id_and_project_fallback tests/test_extractor.py -v
```

Expected: FAIL。

- [ ] **Step 3: 修改 `hooks/_common.py` 与 `hooks/pre_tool.py`，让搜索优先用 session 项目**

把 `hooks/_common.py` 中的函数签名改为：

```python
def search_memory(query: str, project_id: str = None, session_id: str = None) -> list:
    try:
        params = {"q": query}
        if project_id:
            params["project_id"] = project_id
        if session_id:
            params["session_id"] = session_id
        url = f"{SERVER}/memory/search?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method="GET")
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        return json.loads(resp.read())
    except Exception:
        return []
```

并把 `hooks/pre_tool.py` 中的搜索调用改为：

```python
project_id = _project_id_from_cwd(cwd)
query = _query_from_input(tool_name, data.get("tool_input") or {})
for mem in _common.search_memory(query, project_id=project_id, session_id=agent_session_id):
    print(f"\n[CodeTogether 记忆]: {mem['title']} — {mem['content']}\n", flush=True)
```

- [ ] **Step 4: 修改 `server/services/extractor.py`，增加规则化 prompt 与服务端过滤**

将 prompt 改为更强约束版本：

```python
_PROMPT = """你是一个知识提炼助手。请只提炼值得未来 Agent 反复复用的项目规则、约束、坑点、边界。
禁止输出：
1. 操作流水（运行了什么命令、改了哪些文件、测试通过了）
2. 一次性现象（偶发日志、临时报错、没有普遍性的现场现象）
3. 代码常识（从代码一眼能看出的结构、显然事实）
如果没有符合条件的内容，返回空数组 []。
每个 session 最多返回 3 条。
格式：[{"title": "...", "content": "...", "tags": "逗号分隔标签"}]。

会话摘要：
{summary}"""
```

新增过滤 helper：

```python
_ALLOWED_MARKERS = ("必须", "不能", "不要", "需要", "仅在", "会导致", "应当")
_FORBIDDEN_MARKERS = ("运行了", "修改了", "测试通过", "查看了", "读取了", "Bash", "Read", "Edit", "pytest")


def _filter_memory_candidates(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for item in items:
        content = (item.get("content") or "").strip()
        if len(content) < 20 or len(content) > 200:
            continue
        if any(marker in content for marker in _FORBIDDEN_MARKERS):
            continue
        if not any(marker in content for marker in _ALLOWED_MARKERS):
            continue
        filtered.append(item)
        if len(filtered) == 3:
            break
    return filtered
```

并在 `extract_memories()` 中接入：

```python
items = json.loads(raw)
items = _filter_memory_candidates(items)
for item in items:
    item["project_id"] = project_id
return items
```

- [ ] **Step 5: 修改 `server/routers/agents.py`，让提炼输入从“流水”偏向“结论”**

把 `_trigger_extraction()` 中的 summary 生成替换为：

```python
recent_messages = (
    save_db.query(MessageModel)
    .filter(MessageModel.session_id == session_id)
    .order_by(MessageModel.created_at.desc())
    .limit(12)
    .all()
)
recent_messages = list(reversed(recent_messages))
summary_lines = [
    f"{m.role}: {m.content[:200]}"
    for m in recent_messages
    if m.content and m.content.strip()
]
if not summary_lines:
    recent_events = (
        save_db.query(EventModel)
        .filter(EventModel.session_id == session_id)
        .order_by(EventModel.created_at.asc())
        .limit(10)
        .all()
    )
    summary_lines = [
        f"{e.tool_name} input={str(e.input or '')[:80]} output={str(e.output or '')[:120]}"
        for e in recent_events
    ]
summary = "\n".join(summary_lines)
```

并在写库前再做 1–3 条上限保护：

```python
for item in items[:3]:
    save_db.add(MemoryModel(...))
```

别忘了新增 import：

```python
from server.models import Event as EventModel, Memory as MemoryModel, Message as MessageModel
```

- [ ] **Step 6: 运行测试，确认 hook 参数与提炼过滤通过**

Run:

```bash
pytest tests/test_hooks.py::test_search_memory_includes_session_id_and_project_fallback tests/test_extractor.py -v
```

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add hooks/_common.py hooks/pre_tool.py server/services/extractor.py server/routers/agents.py tests/test_hooks.py tests/test_extractor.py
git commit -m "feat: tighten memory extraction and session-scoped lookup"
```

---

### Task 5: 更新移动端记忆页，默认当前项目并加入 review 队列

**Files:**
- Modify: `mobile/index.html`
- Modify: `mobile/app.js`
- Modify: `mobile/style.css`
- Modify: `tests/test_mobile.py`

- [ ] **Step 1: 写失败测试，锁定默认当前项目范围与 review 操作**

在 `tests/test_mobile.py` 追加：

```python
def test_mobile_memory_html_contains_scope_toggle(client):
    html = client.get("/mobile/index.html").text
    assert 'id="memory-scope-current"' in html
    assert 'id="memory-scope-all"' in html
    assert 'id="memory-filter-review"' in html


def test_mobile_memory_script_defaults_to_current_project_scope(client):
    js = client.get("/mobile/app.js").text
    assert "memoryScope: \"current\"" in js
    assert "function getCurrentMemoryProjectId()" in js
    assert 'url += `&project_id=${encodeURIComponent(projectId)}`' in js


def test_mobile_memory_script_uses_delete_for_reject(client):
    js = client.get("/mobile/app.js").text
    assert "async function deleteMemory(memoryId)" in js
    assert 'fetchJson(`${SERVER}/memory/${memoryId}`, { method: "DELETE" })' in js
```

- [ ] **Step 2: 运行测试，确认 UI 还没有这些控件和逻辑**

Run:

```bash
pytest tests/test_mobile.py::test_mobile_memory_html_contains_scope_toggle tests/test_mobile.py::test_mobile_memory_script_defaults_to_current_project_scope tests/test_mobile.py::test_mobile_memory_script_uses_delete_for_reject -v
```

Expected: FAIL。

- [ ] **Step 3: 修改 `mobile/index.html`，增加范围切换和 review tab**

在记忆区控件中加入：

```html
<div class="memory-scope-switch">
  <button id="memory-scope-current" class="active" type="button">当前项目</button>
  <button id="memory-scope-all" type="button">全部项目</button>
</div>
<div class="memory-filter-row">
  <button id="memory-filter-pending" class="active" type="button">待启用</button>
  <button id="memory-filter-review" type="button">待晋升</button>
  <button id="memory-filter-active" type="button">已启用</button>
</div>
```

- [ ] **Step 4: 修改 `mobile/app.js`，默认当前项目范围并新增删除/晋升动作**

在 state 中加入：

```javascript
memoryScope: "current",
```

在 `dom` 中加入：

```javascript
memoryFilterReview: document.getElementById("memory-filter-review"),
memoryScopeCurrent: document.getElementById("memory-scope-current"),
memoryScopeAll: document.getElementById("memory-scope-all"),
```

新增 helper：

```javascript
function getCurrentMemoryProjectId() {
  if (state.selectedSessionId) {
    const session = state.sessions.find((s) => s.id === state.selectedSessionId);
    if (session?.project_id) return session.project_id;
  }
  const latest = [...state.sessions]
    .sort((a, b) => (b.started_at || 0) - (a.started_at || 0))
    .find((s) => s.project_id);
  return latest?.project_id || null;
}
```

把 `loadMemories()` 改为：

```javascript
async function loadMemories() {
  let url = `${SERVER}/memory?status=${state.memoryFilter}`;
  if (state.memoryScope === "current") {
    const projectId = getCurrentMemoryProjectId();
    if (projectId) {
      url += `&project_id=${encodeURIComponent(projectId)}`;
    }
  }
  if (state.memoryFilter === "active" && state.tierFilter !== "all") {
    url += `&tier=${encodeURIComponent(state.tierFilter)}`;
  }
  state.memories = await fetchJson(url);
  renderMemories();
}
```

新增删除函数：

```javascript
async function deleteMemory(memoryId) {
  await fetchJson(`${SERVER}/memory/${memoryId}`, { method: "DELETE" });
  showToast("记忆已删除");
  await loadMemories();
}
```

在 `renderMemories()` 中，把 review 操作改成：

```javascript
const actions = state.memoryFilter === "pending"
  ? `<div class="memory-actions">
      <button type="button" data-action="activate" data-id="${escapeHtml(memory.id)}">启用</button>
      <button type="button" class="danger" data-action="delete" data-id="${escapeHtml(memory.id)}">删除</button>
     </div>`
  : isReview
    ? `<div class="memory-actions">
        <button type="button" data-action="promote" data-id="${escapeHtml(memory.id)}">升为长期</button>
        <button type="button" class="danger" data-action="delete" data-id="${escapeHtml(memory.id)}">删除</button>
       </div>`
    : "";
```

显示命中信息：

```javascript
const hitHint = memory.hit_count_7d ? ` · 7天命中 ${memory.hit_count_7d} 次` : "";
```

并在事件绑定里增加：

```javascript
if (action === "activate") {
  reviewMemory(btn.dataset.id, "active").catch(() => showToast("操作失败"));
} else if (action === "promote") {
  promoteMemory(btn.dataset.id).catch(() => showToast("操作失败"));
} else if (action === "delete") {
  deleteMemory(btn.dataset.id).catch(() => showToast("操作失败"));
}
```

新增：

```javascript
async function promoteMemory(memoryId) {
  await fetchJson(`${SERVER}/memory/${memoryId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tier: "long" }),
  });
  showToast("已升为长期记忆");
  await loadMemories();
}
```

- [ ] **Step 5: 修改 `mobile/style.css`，补 review 与 scope 样式**

追加样式：

```css
.memory-scope-switch {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.memory-scope-switch button.active,
.memory-filter-row button.active {
  background: #2563eb;
  color: #fff;
}

.memory-review {
  border-left: 3px solid #2563eb;
}

.memory-hit-hint {
  color: #6b7280;
  font-size: 12px;
}
```

- [ ] **Step 6: 运行前端相关测试，确认默认范围和 review 交互已接通**

Run:

```bash
pytest tests/test_mobile.py::test_mobile_memory_html_contains_scope_toggle tests/test_mobile.py::test_mobile_memory_script_defaults_to_current_project_scope tests/test_mobile.py::test_mobile_memory_script_uses_delete_for_reject -v
```

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add mobile/index.html mobile/app.js mobile/style.css tests/test_mobile.py
git commit -m "feat: add project-scoped memory review UI"
```

---

### Task 6: 运行整体验证并收尾

**Files:**
- Modify: `tests/test_memory.py`
- Modify: `tests/test_hooks.py`
- Modify: `tests/test_mobile.py`
- Modify: `tests/test_housekeeping.py`
- Create: `tests/test_extractor.py`

- [ ] **Step 1: 运行记忆服务端测试**

Run:

```bash
pytest tests/test_memory.py tests/test_agents.py tests/test_housekeeping.py tests/test_extractor.py -v
```

Expected: PASS；若失败，只修本次改动引入的问题，不顺手清理无关旧测试。

- [ ] **Step 2: 运行 hook 测试**

Run:

```bash
pytest tests/test_hooks.py -v
```

Expected: PASS，重点确认 `search_memory()` URL 拼接与 `pre_tool` 注入逻辑未回归。

- [ ] **Step 3: 运行移动端测试**

Run:

```bash
pytest tests/test_mobile.py -v
```

Expected: 若存在本次无关的旧断言失败，先单独跑本次新增用例并在结果中说明；本次新增的 memory scope/review 用例必须 PASS。

- [ ] **Step 4: 手动检查计划覆盖 spec**

对照 `docs/superpowers/specs/2026-06-11-memory-project-scope-and-review-design.md` 检查：

```text
- 默认当前项目、可切全部项目
- short 只记录规则/约束/坑点/边界
- 命中阈值 -> review
- 人工确认 -> long
- 拒绝即删除
- 不再自动 short->long
- 每个 session 最多 1–3 条
```

若缺任何一点，返回相应任务补齐，不要直接宣布完成。

- [ ] **Step 5: Commit**

```bash
git add tests/test_memory.py tests/test_hooks.py tests/test_mobile.py tests/test_housekeeping.py tests/test_extractor.py
git commit -m "test: cover scoped memory review workflow"
```
