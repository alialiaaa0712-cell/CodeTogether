# Agent 主动搜索与反馈积分闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 CodeTogether 记忆系统从 `pre_tool` 自动搜索注入 + 命中次数驱动，全面切换为 Agent 显式搜索、显式反馈、累计积分驱动的短期记忆闭环，并清空旧记忆数据。

**Architecture:** 服务端以 `POST /memory/search` 和 `POST /memory/{memory_id}/feedback` 作为唯一闭环入口：搜索只返回结果并记录本次曝光，反馈才更新 `score_total`、`feedback_count` 与状态流转。数据层新增反馈日志与搜索曝光表来约束“只能对已曝光记忆评分”，同时彻底移除旧的 7 天命中窗口字段、自动命中统计和 `pre_tool` 自动注入逻辑；移动端管理页改为展示积分与反馈指标，长期记忆仍保持人工晋升。

**Tech Stack:** FastAPI · SQLAlchemy · MySQL 5.7 / SQLite · pytest · Mobile Web · Claude Code Hooks

---

## 文件结构

| 文件 | 操作 | 说明 |
|------|------|------|
| `server/models.py` | Modify | 将 `Memory` 从 hit-based 改为 score-based；新增 `MemoryFeedbackLog`、`MemorySearchExposure` |
| `server/schemas.py` | Modify | 新增 `MemorySearchRequest`、`MemoryFeedbackRequest`；`MemoryOut` 改为积分字段 |
| `server/main.py` | Modify | 启动时执行记忆系统一次性迁移：清空旧 `memories`、删除旧列、补新列/新表 |
| `server/routers/memory.py` | Rewrite | 将 `GET /memory/search` 改为 `POST /memory/search`；新增反馈接口；保留人工治理 PATCH/DELETE |
| `server/routers/agents.py` | Modify | 提炼入口继续产出 `pending + short` 记忆，但默认走新积分字段 |
| `server/services/housekeeping.py` | Modify | 删除短期记忆时间恶化逻辑，改为清理过期搜索曝光记录 |
| `hooks/_common.py` | Modify | 新增显式 `memory_search()` / `memory_feedback()` helper，删除 `flag_memory_for_review()` |
| `hooks/pre_tool.py` | Modify | 移除自动搜记忆与自动打印记忆内容，仅保留事件上报、消息同步、pending 消息拉取 |
| `mobile/index.html` | Modify | 保持现有分区结构，更新 review / active 视图所需文案入口 |
| `mobile/app.js` | Modify | 记忆列表主指标改为积分/反馈次数/最近反馈；review 区改为“升为长期 / 删除” |
| `mobile/style.css` | Modify | 将命中文案样式改为积分指标样式，保留 review 高亮 |
| `tests/test_memory.py` | Rewrite | 重写为显式搜索 + 显式反馈闭环测试 |
| `tests/test_hooks.py` | Modify | 删除 pre_tool 自动搜记忆断言，新增 helper 请求体断言 |
| `tests/test_mobile.py` | Modify | 替换“7天命中”断言为“累计积分 / 反馈次数 / 最近反馈”断言 |
| `tests/test_housekeeping.py` | Rewrite | 改为验证曝光记录清理，不再验证命中窗口重置 |
| `tests/test_agents.py` | Modify | 验证提炼出的新记忆默认分数字段 |
| `tests/test_extractor.py` | Modify | 验证提炼逻辑仍只生成候选短期记忆，不依赖旧命中语义 |

---

### Task 1: 重建记忆数据模型与迁移脚手架

**Files:**
- Modify: `server/models.py`
- Modify: `server/schemas.py`
- Modify: `server/main.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1: 先写失败测试，锁定新字段与旧字段移除**

在 `tests/test_memory.py` 追加：

```python
def test_create_memory_returns_score_fields(client):
    """验证新记忆默认返回积分字段，而不再暴露旧命中字段。"""
    resp = client.post("/memory", json={
        "title": "数据库约束",
        "content": "MySQL 5.7 不能使用 ADD COLUMN IF NOT EXISTS",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["score_total"] == 0
    assert data["feedback_count"] == 0
    assert data["last_feedback_at"] is None
    assert data["review_score"] is None
    assert "hit_count_7d" not in data
    assert "last_hit_at" not in data
    assert "review_hit_count" not in data
```

在同文件再追加：

```python
def test_memory_search_request_requires_post_body(client):
    """验证记忆搜索改为 POST 请求体，不再接受旧 GET 查询参数。"""
    resp = client.get("/memory/search?q=mysql")
    assert resp.status_code in (404, 405)
```

- [ ] **Step 2: 运行失败测试，确认现在仍是旧语义**

Run:

```bash
pytest tests/test_memory.py::test_create_memory_returns_score_fields tests/test_memory.py::test_memory_search_request_requires_post_body -v
```

Expected: FAIL；当前响应仍包含 `hit_count_7d` 等旧字段，且 `GET /memory/search` 仍然可用。

- [ ] **Step 3: 修改模型、Schema 与启动迁移，建立 score-based 数据层**

将 `server/models.py` 中 `Memory` 改为：

```python
class Memory(Base):
    """知识条目表：Agent 运行后提炼的项目知识。"""
    __tablename__ = "memories"

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    title = Column(String(512), nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(String(512))
    status = Column(Enum("pending", "active", "review"), default="pending")
    tier = Column(Enum("short", "long"), default="short", nullable=False)
    source_session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    created_at = Column(Double, default=time.time)
    updated_at = Column(Double, default=time.time)
    activated_at = Column(Double)
    review_reason = Column(String(64))
    score_total = Column(Integer, nullable=False, default=0)
    feedback_count = Column(Integer, nullable=False, default=0)
    last_feedback_at = Column(Double)
    review_score = Column(Integer)

    project = relationship("Project", back_populates="memories")

    __table_args__ = (
        Index("ix_memories_project_status", "project_id", "status"),
    )
```

在同文件新增：

```python
class MemoryFeedbackLog(Base):
    """记忆反馈日志表：记录 Agent 对记忆的显式评分证据链。"""
    __tablename__ = "memory_feedback_logs"

    id = Column(String(36), primary_key=True, default=_uuid)
    memory_id = Column(String(36), ForeignKey("memories.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    score = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(Double, default=time.time)

    __table_args__ = (
        Index("ix_memory_feedback_logs_memory_id", "memory_id"),
    )


class MemorySearchExposure(Base):
    """记忆搜索曝光表：约束只有被当前会话搜索返回过的记忆才能被评分。"""
    __tablename__ = "memory_search_exposures"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    memory_id = Column(String(36), ForeignKey("memories.id"), nullable=False)
    created_at = Column(Double, default=time.time)

    __table_args__ = (
        Index("ix_memory_search_exposures_session_id", "session_id"),
    )
```

将 `server/schemas.py` 中记忆相关 schema 改为：

```python
class MemorySearchRequest(BaseModel):
    query: str
    session_id: str
    limit: int = 3


class MemoryFeedbackRequest(BaseModel):
    session_id: str
    score: Literal[-2, -1, 0, 1, 2]
    reason: str


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
    updated_at: float
    activated_at: Optional[float] = None
    review_reason: Optional[str] = None
    score_total: int
    feedback_count: int
    last_feedback_at: Optional[float] = None
    review_score: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class MemoryUpdate(BaseModel):
    status: Optional[Literal["active"]] = None
    tier: Optional[Literal["long"]] = None
```

在 `server/main.py` 提取一个一次性迁移 helper，并在非测试启动时调用：

```python
def _migrate_memory_tables() -> None:
    """将旧命中制记忆表迁移为积分制结构，并清空不再兼容的旧数据。"""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    memory_cols = [c["name"] for c in insp.get_columns("memories")]
    is_legacy_memory = "hit_count_7d" in memory_cols or "review_hit_count" in memory_cols

    with engine.connect() as conn:
        if is_legacy_memory:
            conn.execute(text("DELETE FROM memories"))
            conn.commit()

        adds = [
            ("score_total", "ALTER TABLE memories ADD COLUMN score_total INT NOT NULL DEFAULT 0"),
            ("feedback_count", "ALTER TABLE memories ADD COLUMN feedback_count INT NOT NULL DEFAULT 0"),
            ("last_feedback_at", "ALTER TABLE memories ADD COLUMN last_feedback_at DOUBLE NULL"),
            ("review_score", "ALTER TABLE memories ADD COLUMN review_score INT NULL"),
        ]
        for name, ddl in adds:
            if name not in memory_cols:
                conn.execute(text(ddl))
                conn.commit()

        drops = ["hit_count_7d", "last_hit_at", "review_hit_count"]
        memory_cols = [c["name"] for c in insp.get_columns("memories")]
        for name in drops:
            if name in memory_cols:
                conn.execute(text(f"ALTER TABLE memories DROP COLUMN {name}"))
                conn.commit()
```

并在 `Base.metadata.create_all(bind=engine)` 后调用：

```python
if not _is_sqlite:
    _migrate_memory_tables()
```

- [ ] **Step 4: 重新运行测试，确认新字段已经替代旧字段**

Run:

```bash
pytest tests/test_memory.py::test_create_memory_returns_score_fields tests/test_memory.py::test_memory_search_request_requires_post_body -v
```

Expected: PASS。

- [ ] **Step 5: 提交这一层基础设施变更**

```bash
git add server/models.py server/schemas.py server/main.py tests/test_memory.py
git commit -m "feat: replace memory hit fields with score-based schema"
```

---

### Task 2: 重写搜索与反馈闭环 API

**Files:**
- Modify: `server/routers/memory.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1: 先写失败测试，锁定搜索不计分、反馈才计分的核心行为**

在 `tests/test_memory.py` 追加：

```python
def test_post_search_returns_active_memories_without_mutating_score(client):
    session = client.post("/agents", json={"id": "sess-search-score", "cwd": "/tmp/search-score"}).json()
    long_mem = client.post("/memory", json={
        "project_id": session["project_id"],
        "title": "长期规则",
        "content": "MySQL 必须使用 pool_pre_ping",
    }).json()
    short_mem = client.post("/memory", json={
        "project_id": session["project_id"],
        "title": "短期规则",
        "content": "数据库 timeout 需要调大",
    }).json()
    client.patch(f"/memory/{long_mem['id']}", json={"status": "active"})
    client.patch(f"/memory/{short_mem['id']}", json={"status": "active"})
    client.patch(f"/memory/{long_mem['id']}", json={"tier": "long"})

    resp = client.post("/memory/search", json={
        "query": "数据库 timeout",
        "session_id": "sess-search-score",
        "limit": 3,
    })

    assert resp.status_code == 200
    results = resp.json()
    assert [item["tier"] for item in results] == ["long", "short"]
    assert all(item["score_total"] == 0 for item in results)
    assert all(item["feedback_count"] == 0 for item in results)
```

继续追加：

```python
def test_feedback_promotes_short_memory_to_review_at_positive_threshold(client, monkeypatch):
    monkeypatch.setattr("server.routers.memory._REVIEW_SCORE_THRESHOLD", 3)
    session = client.post("/agents", json={"id": "sess-feedback-up", "cwd": "/tmp/feedback-up"}).json()
    memory = client.post("/memory", json={
        "project_id": session["project_id"],
        "title": "DDL 规则",
        "content": "MySQL 5.7 不支持该 DDL",
    }).json()
    client.patch(f"/memory/{memory['id']}", json={"status": "active"})
    client.post("/memory/search", json={"query": "DDL", "session_id": "sess-feedback-up", "limit": 3})

    resp = client.post(f"/memory/{memory['id']}/feedback", json={
        "session_id": "sess-feedback-up",
        "score": 2,
        "reason": "第一次确认了兼容性边界",
    })
    assert resp.status_code == 200
    resp = client.post(f"/memory/{memory['id']}/feedback", json={
        "session_id": "sess-feedback-up",
        "score": 1,
        "reason": "再次帮助排除了错误方案",
    })

    assert resp.status_code == 200
    assert resp.json()["status"] == "review"
    assert resp.json()["tier"] == "short"
    assert resp.json()["review_reason"] == "score_threshold"
    assert resp.json()["review_score"] == 3
```

再追加两个边界测试：

```python
def test_feedback_deletes_short_memory_at_negative_threshold(client, monkeypatch):
    monkeypatch.setattr("server.routers.memory._DELETE_SCORE_THRESHOLD", -3)
    session = client.post("/agents", json={"id": "sess-feedback-down", "cwd": "/tmp/feedback-down"}).json()
    memory = client.post("/memory", json={
        "project_id": session["project_id"],
        "title": "无效经验",
        "content": "这个结论后续被证明不成立",
    }).json()
    client.patch(f"/memory/{memory['id']}", json={"status": "active"})
    client.post("/memory/search", json={"query": "结论", "session_id": "sess-feedback-down", "limit": 3})

    resp = client.post(f"/memory/{memory['id']}/feedback", json={
        "session_id": "sess-feedback-down",
        "score": -2,
        "reason": "误导了定位",
    })
    assert resp.status_code == 200

    resp = client.post(f"/memory/{memory['id']}/feedback", json={
        "session_id": "sess-feedback-down",
        "score": -1,
        "reason": "再次验证无用",
    })
    assert resp.status_code == 404
    listed = client.get("/memory?status=active").json()
    assert all(item["id"] != memory["id"] for item in listed)


def test_feedback_rejects_memory_not_exposed_to_session(client):
    session = client.post("/agents", json={"id": "sess-feedback-guard", "cwd": "/tmp/feedback-guard"}).json()
    memory = client.post("/memory", json={
        "project_id": session["project_id"],
        "title": "规则",
        "content": "只有搜索过的记忆才能反馈",
    }).json()
    client.patch(f"/memory/{memory['id']}", json={"status": "active"})

    resp = client.post(f"/memory/{memory['id']}/feedback", json={
        "session_id": "sess-feedback-guard",
        "score": 1,
        "reason": "不应该允许凭空评分",
    })
    assert resp.status_code == 400
```

- [ ] **Step 2: 运行失败测试，确认旧接口与旧行为仍在**

Run:

```bash
pytest tests/test_memory.py::test_post_search_returns_active_memories_without_mutating_score tests/test_memory.py::test_feedback_promotes_short_memory_to_review_at_positive_threshold tests/test_memory.py::test_feedback_deletes_short_memory_at_negative_threshold tests/test_memory.py::test_feedback_rejects_memory_not_exposed_to_session -v
```

Expected: FAIL；当前没有 `POST /memory/search`、没有 feedback 接口，搜索时仍会改命中次数。

- [ ] **Step 3: 改写 `server/routers/memory.py` 为显式搜索 + 显式反馈**

先替换常量：

```python
_REVIEW_SCORE_THRESHOLD = 3
_DELETE_SCORE_THRESHOLD = -3
_EXPOSURE_TTL = 3600
```

补 imports：

```python
from server.models import Memory as MemoryModel
from server.models import MemoryFeedbackLog, MemorySearchExposure
from server.schemas import MemoryCreate, MemoryFeedbackRequest, MemoryOut, MemorySearchRequest, MemoryUpdate
```

加入搜索辅助函数：

```python
def _memory_query(db: DBSession, query: str, project_id: Optional[str], tier: str):
    qr = db.query(MemoryModel).filter(
        MemoryModel.status == "active",
        MemoryModel.tier == tier,
    )
    if project_id:
        qr = qr.filter(MemoryModel.project_id == project_id)
    tokens = [t for t in re.split(r"[\s/\-.,;:]+", query) if len(t) >= 2][:10]
    if not tokens:
        tokens = [query]
    return qr.filter(or_(*[
        or_(
            MemoryModel.title.contains(token),
            MemoryModel.content.contains(token),
            MemoryModel.tags.contains(token),
        )
        for token in tokens
    ]))
```

将搜索接口改为：

```python
@router.post("/search", response_model=List[MemoryOut])
def search_memories(body: MemorySearchRequest, db: DBSession = Depends(get_db)):
    resolved_project_id = _resolve_project_id(db, body.session_id, None)
    limit = max(1, min(body.limit, 10))

    results = _memory_query(db, body.query, resolved_project_id, "long").limit(limit).all()
    remaining = limit - len(results)
    if remaining > 0:
        results.extend(_memory_query(db, body.query, resolved_project_id, "short").limit(remaining).all())

    now = time.time()
    db.query(MemorySearchExposure).filter(
        MemorySearchExposure.session_id == body.session_id,
        MemorySearchExposure.created_at < now - _EXPOSURE_TTL,
    ).delete(synchronize_session=False)
    for memory in results:
        db.add(MemorySearchExposure(session_id=body.session_id, memory_id=memory.id, created_at=now))
    db.commit()
    return results
```

加入反馈辅助函数：

```python
def _was_exposed_to_session(db: DBSession, session_id: str, memory_id: str) -> bool:
    now = time.time()
    return db.query(MemorySearchExposure).filter(
        MemorySearchExposure.session_id == session_id,
        MemorySearchExposure.memory_id == memory_id,
        MemorySearchExposure.created_at >= now - _EXPOSURE_TTL,
    ).first() is not None
```

新增反馈接口：

```python
@router.post("/{memory_id}/feedback", response_model=MemoryOut)
def submit_memory_feedback(memory_id: str, body: MemoryFeedbackRequest, db: DBSession = Depends(get_db)):
    memory = db.get(MemoryModel, memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="memory not found")
    if not _was_exposed_to_session(db, body.session_id, memory_id):
        raise HTTPException(status_code=400, detail="memory must be exposed before feedback")

    now = time.time()
    memory.score_total += body.score
    memory.feedback_count += 1
    memory.last_feedback_at = now
    memory.updated_at = now

    db.add(MemoryFeedbackLog(
        memory_id=memory.id,
        session_id=body.session_id,
        score=body.score,
        reason=body.reason,
        created_at=now,
    ))

    if memory.tier == "short":
        if memory.score_total >= _REVIEW_SCORE_THRESHOLD:
            memory.status = "review"
            memory.review_reason = "score_threshold"
            memory.review_score = memory.score_total
        elif memory.score_total <= _DELETE_SCORE_THRESHOLD:
            db.delete(memory)
            db.commit()
            raise HTTPException(status_code=404, detail="memory deleted after low score")

    db.commit()
    db.refresh(memory)
    return memory
```

同时保留并收紧 PATCH：

```python
if body.status == "active":
    if memory.status != "pending":
        raise HTTPException(status_code=422, detail="仅 pending 记忆可启用")
    memory.status = "active"
elif body.tier == "long":
    if memory.status != "review" or memory.tier != "short":
        raise HTTPException(status_code=422, detail="仅 review/short 记忆可晋升为长期")
    memory.tier = "long"
    memory.status = "active"
else:
    raise HTTPException(status_code=400, detail="仅支持启用短期记忆或将 review 短期记忆晋升为长期")
```

将删除短期记忆分支改为返回 200 与删除结果对象，而不是抛异常；实现方式是先在删除前保存快照：

```python
snapshot = MemoryOut.model_validate(memory)
db.delete(memory)
db.commit()
return snapshot
```

然后把刚才负阈值测试里的第二次反馈断言改为：

```python
assert resp.status_code == 200
assert resp.json()["id"] == memory["id"]
listed = client.get("/memory?status=active").json()
assert all(item["id"] != memory["id"] for item in listed)
```

- [ ] **Step 4: 运行测试，确认闭环成立**

Run:

```bash
pytest tests/test_memory.py -v
```

Expected: PASS；重点确认搜索不加分、feedback 才会改 `score_total`，以及 `review + short -> active + long` 仍然成立。

- [ ] **Step 5: 提交闭环 API 改写**

```bash
git add server/routers/memory.py tests/test_memory.py
git commit -m "feat: add explicit memory search and feedback loop"
```

---

### Task 3: 移除 hook 自动注入并提供显式 helper

**Files:**
- Modify: `hooks/_common.py`
- Modify: `hooks/pre_tool.py`
- Modify: `tests/test_hooks.py`

- [ ] **Step 1: 先写失败测试，锁定 pre_tool 不再自动搜记忆，同时保留显式 helper**

在 `tests/test_hooks.py` 把旧的自动注入断言替换为：

```python
def test_pre_tool_does_not_search_memory_automatically(capsys):
    m = import_pre_tool()
    with mock.patch("hooks._common.post_event"), \
         mock.patch("hooks._common.poll_messages", return_value=[]), \
         mock.patch("hooks._common.memory_search") as mock_search, \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "cwd": "/project",
        })
        m.main()

    mock_search.assert_not_called()
    assert "[CodeTogether 记忆]" not in capsys.readouterr().out
```

再追加 helper 测试：

```python
def test_memory_search_posts_json_body():
    m = import_common()
    payload = [{"id": "1", "title": "规则", "content": "内容", "tier": "long"}]

    def fake_urlopen(req, timeout):
        resp = mock.MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        assert req.method == "POST"
        assert req.full_url.endswith("/memory/search")
        assert json.loads(req.data) == {
            "query": "mysql ddl",
            "session_id": "sess-1",
            "limit": 3,
        }
        return resp

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = m.memory_search("mysql ddl", session_id="sess-1")

    assert result == payload


def test_memory_feedback_posts_json_body():
    m = import_common()
    captured = {}

    def fake_urlopen(req, timeout):
        captured["method"] = req.method
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        resp = mock.MagicMock()
        resp.read.return_value = json.dumps({"id": "mem-1", "score_total": 2}).encode()
        return resp

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = m.memory_feedback("mem-1", session_id="sess-1", score=2, reason="确认了 DDL 边界")

    assert result["score_total"] == 2
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/memory/mem-1/feedback")
    assert captured["body"] == {
        "session_id": "sess-1",
        "score": 2,
        "reason": "确认了 DDL 边界",
    }
```

- [ ] **Step 2: 运行失败测试，确认当前仍是自动注入 + 旧 helper**

Run:

```bash
pytest tests/test_hooks.py::test_pre_tool_does_not_search_memory_automatically tests/test_hooks.py::test_memory_search_posts_json_body tests/test_hooks.py::test_memory_feedback_posts_json_body -v
```

Expected: FAIL；当前 `pre_tool` 仍会调用 `search_memory()`，且 `_common.py` 还没有新 helper。

- [ ] **Step 3: 重写 `_common.py` 与 `pre_tool.py`**

在 `hooks/_common.py` 中新增：

```python
def memory_search(query: str, session_id: str, limit: int = 3) -> list:
    """显式搜索记忆，按 session_id 让服务端自动解析项目范围。"""
    try:
        req = urllib.request.Request(
            f"{SERVER}/memory/search",
            data=json.dumps({
                "query": query,
                "session_id": session_id,
                "limit": limit,
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        return json.loads(resp.read())
    except Exception:
        return []


def memory_feedback(memory_id: str, session_id: str, score: int, reason: str) -> dict | None:
    """显式提交记忆反馈，失败时返回 None。"""
    try:
        req = urllib.request.Request(
            f"{SERVER}/memory/{memory_id}/feedback",
            data=json.dumps({
                "session_id": session_id,
                "score": score,
                "reason": reason,
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        return json.loads(resp.read())
    except Exception:
        return None
```

删除旧函数：

```python
def search_memory(...)

def flag_memory_for_review(...)
```

把 `hooks/pre_tool.py` 主流程改为：

```python
def main():
    """PreToolUse hook 主入口：仅负责上报事件、同步 transcript 与拉取 pending 消息。"""
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return

    session_id = data.get("session_id") or ""
    child_agent_id = data.get("agent_id")
    if child_agent_id:
        agent_session_id = child_agent_id
        parent_session_id = session_id
    else:
        agent_session_id = session_id
        parent_session_id = None

    cwd = data.get("cwd") or ""
    tool_name = data.get("tool_name") or ""

    _common.ensure_session(agent_session_id, cwd=cwd)
    if agent_session_id:
        sync_messages(agent_session_id, cwd)

    _common.post_event({
        "session_id": agent_session_id,
        "type": "pre_tool",
        "tool_name": tool_name,
        "tool_use_id": data.get("tool_use_id"),
        "input": data.get("tool_input"),
        "cwd": cwd,
        "parent_session_id": parent_session_id,
    })

    for msg in _common.poll_messages(agent_session_id):
        print(f"\n[CodeTogether 消息]: {msg['content']}\n", flush=True)
```

- [ ] **Step 4: 运行测试，确认自动注入已移除**

Run:

```bash
pytest tests/test_hooks.py -v
```

Expected: PASS；重点确认 `pre_tool` 不再打印记忆内容，新 helper 使用 `POST` JSON 请求体。

- [ ] **Step 5: 提交 hook 显式化改动**

```bash
git add hooks/_common.py hooks/pre_tool.py tests/test_hooks.py
git commit -m "feat: remove automatic memory injection from hooks"
```

---

### Task 4: 清理提炼与 housekeeping 的旧命中语义

**Files:**
- Modify: `server/routers/agents.py`
- Modify: `server/services/housekeeping.py`
- Modify: `tests/test_agents.py`
- Modify: `tests/test_housekeeping.py`
- Modify: `tests/test_extractor.py`

- [ ] **Step 1: 先写失败测试，锁定提炼默认值与 housekeeping 新职责**

在 `tests/test_agents.py` 追加：

```python
def test_trigger_extraction_saves_pending_short_memories_with_score_defaults(db):
    session = Session(id="sess-extract-score", project_id="proj-1")
    db.add(session)
    db.add(Message(session_id="sess-extract-score", role="assistant", content="MySQL 5.7 不能使用该 DDL", status="delivered"))
    db.commit()

    returned_items = [
        {"project_id": "proj-1", "title": "DDL 约束", "content": "MySQL 5.7 不能使用该 DDL", "tags": "mysql"},
    ]

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    with mock.patch("server.routers.agents.extract_memories", return_value=returned_items), \
         mock.patch("server.routers.agents.SessionLocal", return_value=db), \
         mock.patch("server.routers.agents.threading.Thread", ImmediateThread):
        _trigger_extraction("sess-extract-score", "proj-1")

    saved = db.query(Memory).filter(Memory.source_session_id == "sess-extract-score").one()
    assert saved.status == "pending"
    assert saved.tier == "short"
    assert saved.score_total == 0
    assert saved.feedback_count == 0
```

将 `tests/test_housekeeping.py` 替换为：

```python
import time

from server.models import MemorySearchExposure
from server.services.housekeeping import run_memory_housekeeping


def test_housekeeping_deletes_stale_memory_search_exposures(db):
    db.add(MemorySearchExposure(session_id="sess-1", memory_id="mem-1", created_at=1000.0))
    db.add(MemorySearchExposure(session_id="sess-1", memory_id="mem-2", created_at=1000.0 + 60))
    db.commit()

    with mock.patch("server.services.housekeeping.time.time", return_value=1000.0 + 7200):
        run_memory_housekeeping(db)

    rows = db.query(MemorySearchExposure).all()
    assert rows == []


def test_housekeeping_does_not_change_memory_scores(db):
    memory = MemoryModel(
        title="规则",
        content="短期记忆不再按时间恶化",
        status="active",
        tier="short",
        score_total=2,
        feedback_count=1,
        updated_at=1000.0,
    )
    db.add(memory)
    db.commit()

    with mock.patch("server.services.housekeeping.time.time", return_value=1000.0 + 7200):
        run_memory_housekeeping(db)

    db.refresh(memory)
    assert memory.score_total == 2
    assert memory.feedback_count == 1
    assert memory.status == "active"
```

- [ ] **Step 2: 运行失败测试，确认当前 housekeeping 仍在处理旧 hit 窗口**

Run:

```bash
pytest tests/test_agents.py::test_trigger_extraction_saves_pending_short_memories_with_score_defaults tests/test_housekeeping.py -v
```

Expected: FAIL；当前提炼出的记忆还没有新分数字段，housekeeping 仍操作 `hit_count_7d`。

- [ ] **Step 3: 修改提炼入口与 housekeeping**

在 `server/routers/agents.py` 的 `_trigger_extraction()` 落库处显式初始化新字段：

```python
for item in items[:3]:
    save_db.add(MemoryModel(
        project_id=item.get("project_id"),
        title=item["title"],
        content=item["content"],
        tags=item.get("tags"),
        source_session_id=session_id,
        score_total=0,
        feedback_count=0,
    ))
```

将 `server/services/housekeeping.py` 改为：

```python
from server.models import MemorySearchExposure

_EXPOSURE_TTL = 3600


def run_memory_housekeeping(db: DBSession) -> None:
    """执行记忆轻量维护任务：仅清理过期搜索曝光记录。"""
    now = time.time()
    stale_exposures = (
        db.query(MemorySearchExposure)
        .filter(MemorySearchExposure.created_at < now - _EXPOSURE_TTL)
        .all()
    )
    for row in stale_exposures:
        db.delete(row)
    if stale_exposures:
        logger.info("housekeeping: %d stale memory exposures deleted", len(stale_exposures))
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("housekeeping: 提交失败，已回滚")
```

在 `tests/test_extractor.py` 保留已有过滤测试，并补一个与新语义一致的断言：

```python
def test_extract_memories_returns_candidate_records_only(monkeypatch):
    payload = """[{"title":"DDL 约束","content":"MySQL 5.7 不能使用该 DDL","tags":"mysql"}]"""
    monkeypatch.setattr("server.services.extractor.call_ai_json", lambda prompt: payload)
    result = extract_memories("assistant: MySQL 5.7 不能使用该 DDL", project_id="proj-1")
    assert result == [{
        "project_id": "proj-1",
        "title": "DDL 约束",
        "content": "MySQL 5.7 不能使用该 DDL",
        "tags": "mysql",
    }]
```

- [ ] **Step 4: 运行测试，确认后台链路只保留候选生成与曝光清理**

Run:

```bash
pytest tests/test_agents.py tests/test_housekeeping.py tests/test_extractor.py -v
```

Expected: PASS。

- [ ] **Step 5: 提交后台语义清理**

```bash
git add server/routers/agents.py server/services/housekeeping.py tests/test_agents.py tests/test_housekeeping.py tests/test_extractor.py
git commit -m "refactor: align extraction and housekeeping with score-based memory flow"
```

---

### Task 5: 更新移动端管理页与端到端回归测试

**Files:**
- Modify: `mobile/index.html`
- Modify: `mobile/app.js`
- Modify: `mobile/style.css`
- Modify: `tests/test_mobile.py`

- [ ] **Step 1: 先写失败测试，锁定新文案与新指标**

在 `tests/test_mobile.py` 替换旧“7天命中”断言，并追加：

```python
def test_mobile_memory_script_shows_score_metrics_instead_of_hit_count(client):
    """验证记忆页脚本展示累计积分与反馈次数，而不再展示 7 天命中。"""
    js = client.get("/mobile/app.js").text
    assert "累计积分" in js
    assert "反馈" in js
    assert "last_feedback_at" in js
    assert "review_score" in js
    assert "7天命中" not in js


def test_mobile_memory_script_contains_promote_and_delete_actions(client):
    """验证 review 区保留升为长期与删除动作。"""
    js = client.get("/mobile/app.js").text
    assert "async function promoteMemory(memoryId)" in js
    assert "async function deleteMemory(memoryId)" in js
    assert "记忆已升为长期" in js
    assert "记忆已删除" in js


def test_mobile_memory_html_contains_review_and_active_filters(client):
    """验证记忆页仍有待启用、待晋升、已启用三个分区入口。"""
    html = client.get("/mobile/index.html").text
    assert 'id="memory-filter-pending"' in html
    assert 'id="memory-filter-review"' in html
    assert 'id="memory-filter-active"' in html
```

- [ ] **Step 2: 运行失败测试，确认当前前端仍在展示旧命中字段**

Run:

```bash
pytest tests/test_mobile.py::test_mobile_memory_script_shows_score_metrics_instead_of_hit_count tests/test_mobile.py::test_mobile_memory_script_contains_promote_and_delete_actions tests/test_mobile.py::test_mobile_memory_html_contains_review_and_active_filters -v
```

Expected: FAIL；当前脚本仍包含 `7天命中` 文案。

- [ ] **Step 3: 修改移动端脚本与样式，切到积分视图**

在 `mobile/app.js` 的记忆渲染函数中，将旧文案：

```javascript
const hitHint = ` · 7天命中 ${escapeHtml(memory.hit_count_7d ?? 0)} 次`;
```

替换为：

```javascript
function formatFeedbackTime(timestamp) {
  if (!timestamp) {
    return "暂无反馈";
  }
  return new Date(timestamp * 1000).toLocaleString("zh-CN", {
    hour12: false,
  });
}
```

并在渲染时使用：

```javascript
const scoreText = `累计积分 ${escapeHtml(memory.score_total ?? 0)}`;
const feedbackText = `反馈 ${escapeHtml(memory.feedback_count ?? 0)} 次`;
const reviewText = state.memoryFilter === "review" && memory.review_score != null
  ? ` · 晋升分 ${escapeHtml(memory.review_score)}`
  : "";
const feedbackHint = `最近反馈 ${escapeHtml(formatFeedbackTime(memory.last_feedback_at))}`;
```

拼装成：

```javascript
<div class="memory-meta">${scoreText} · ${feedbackText}${reviewText}</div>
<div class="memory-feedback-hint">${feedbackHint}</div>
```

将 review 区按钮文案改为：

```javascript
<button type="button" onclick="promoteMemory('${memory.id}')">升为长期</button>
<button type="button" class="danger" onclick="deleteMemory('${memory.id}')">删除</button>
```

成功 toast 改为：

```javascript
showToast("记忆已升为长期");
showToast("记忆已删除");
```

在 `mobile/style.css` 新增：

```css
.memory-meta {
  color: #111827;
  font-size: 13px;
  margin-top: 6px;
}

.memory-feedback-hint {
  color: #6b7280;
  font-size: 12px;
  margin-top: 4px;
}
```

并删除旧样式：

```css
.memory-hit-hint {
  color: #6b7280;
  font-size: 12px;
}
```

- [ ] **Step 4: 运行前端相关测试，确认 UI 文案完成切换**

Run:

```bash
pytest tests/test_mobile.py -v
```

Expected: PASS；重点确认不再出现 `7天命中`，且 review / active 分区入口未回归。

- [ ] **Step 5: 提交移动端闭环展示改动**

```bash
git add mobile/index.html mobile/app.js mobile/style.css tests/test_mobile.py
git commit -m "feat: update mobile memory view to score-based metrics"
```

---

## 最终验证

- [ ] 运行后端核心回归：

```bash
pytest tests/test_memory.py tests/test_hooks.py tests/test_agents.py tests/test_housekeeping.py tests/test_extractor.py -v
```

Expected: PASS。

- [ ] 运行移动端相关回归：

```bash
pytest tests/test_mobile.py -v
```

Expected: PASS。

- [ ] 如需手工验证，启动服务：

```bash
python -m server.main
```

然后验证：
1. 访问 `/mobile/index.html`，记忆页显示“累计积分 / 反馈次数 / 最近反馈时间”
2. `POST /memory/search` 不会修改分数
3. `POST /memory/{id}/feedback` 才会推动 `active + short -> review + short`
4. `PATCH /memory/{id}` 只允许 `pending -> active(short)` 和 `review + short -> active + long`
5. `hooks/pre_tool.py` 不再向 Agent 自动打印任何记忆内容

---

## Spec 覆盖自检

- 已覆盖“全面置换”要求：`Task 1` 明确清空旧 `memories` 并删除旧命中列
- 已覆盖“显式搜索 + 显式反馈”：`Task 2` 与 `Task 3`
- 已覆盖“反馈积分驱动 review / 删除”：`Task 2`
- 已覆盖“长期记忆人工晋升”：`Task 2` 与 `Task 5`
- 已覆盖“去掉短期记忆时间恶化”：`Task 4`
- 已覆盖“前端主指标改为积分与反馈”：`Task 5`
- 已覆盖“只能对已曝光记忆反馈”的保护：`Task 1` 的曝光表 + `Task 2` 的校验
- 已覆盖“保留反馈证据链”：`Task 1` 的 `MemoryFeedbackLog`

未实现任何 spec 之外的排序学习、长期记忆自动降级、旧数据迁移兼容逻辑。
