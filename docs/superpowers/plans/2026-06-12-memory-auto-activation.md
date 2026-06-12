# 短期记忆自动启用与项目归属修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让自动提炼出的短期记忆直接启用，并确保新老自动记忆都尽量写入对应 session 所属项目。

**Architecture:** 保持现有“session 停止后后台提炼”的结构不变，只收敛自动提炼落库逻辑与启动期数据修复逻辑。新数据在 `server/routers/agents.py` 中直接写为 `active + short` 并补齐项目归属；旧数据在 `server/main.py` 启动阶段按 `source_session_id -> session -> project/cwd` 做一次幂等回填。

**Tech Stack:** FastAPI、SQLAlchemy、pytest、MySQL/SQLite 兼容迁移

---

## 文件结构

- Modify: `server/routers/agents.py`
  - 负责 session 停止后的后台记忆提炼。
  - 在这里补齐 session 的项目归属，并把自动提炼出的记忆直接保存为 `active + short`。
- Modify: `server/main.py`
  - 负责启动期数据库迁移。
  - 在这里增加一次性历史记忆修复逻辑，处理已有 `pending + short` 自动记忆。
- Modify: `tests/test_agents.py`
  - 覆盖自动提炼默认状态、项目归属补齐、最多落 3 条等行为。
- Modify: `tests/test_main.py`
  - 覆盖启动修复逻辑对历史 `pending + short` 记忆的启用与 `project_id` 回填。

### Task 1: 锁定自动提炼的新行为

**Files:**
- Modify: `tests/test_agents.py:109-183`
- Modify: `server/routers/agents.py:27-75`
- Modify: `server/routers/agents.py:279-322`

- [ ] **Step 1: 写失败测试，定义“自动提炼直接启用”行为**

```python
def test_trigger_extraction_saves_active_short_memories_with_activation_time(db):
    session = Session(id="sess-extract-score", project_id="proj-1")
    db.add(session)
    db.add(Message(
        session_id="sess-extract-score",
        role="assistant",
        content="MySQL 5.7 不能使用该 DDL，否则会导致迁移失败",
        status="delivered",
    ))
    db.commit()

    returned_items = [{
        "project_id": "proj-1",
        "title": "DDL 约束",
        "content": "MySQL 5.7 不能使用该 DDL，否则会导致迁移失败",
        "tags": "mysql",
    }]

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    with mock.patch("server.routers.agents.extract_memories", return_value=returned_items), \
         mock.patch("server.routers.agents.SessionLocal", return_value=db), \
         mock.patch("server.routers.agents.threading.Thread", ImmediateThread):
        _trigger_extraction("sess-extract-score", "proj-1")

    saved = db.query(Memory).filter(Memory.source_session_id == "sess-extract-score").one()
    assert saved.status == "active"
    assert saved.tier == "short"
    assert saved.activated_at is not None
    assert saved.project_id == "proj-1"
    assert saved.score_total == 0
    assert saved.feedback_count == 0
```

- [ ] **Step 2: 运行单测，确认当前实现失败**

Run: `pytest tests/test_agents.py::test_trigger_extraction_saves_active_short_memories_with_activation_time -v`

Expected: FAIL，断言 `saved.status == "active"` 失败，当前值仍是 `pending`。

- [ ] **Step 3: 写失败测试，定义“session 缺 project_id 时按 cwd 补项目”行为**

```python
def test_trigger_extraction_backfills_project_from_session_cwd(db):
    session = Session(
        id="sess-extract-cwd",
        project_id=None,
        cwd="/tmp/demo/CodeTogether",
    )
    db.add(session)
    db.add(Message(
        session_id="sess-extract-cwd",
        role="assistant",
        content="后续必须携带 access token，否则会导致接口失败",
        status="delivered",
    ))
    db.commit()

    returned_items = [{
        "project_id": None,
        "title": "鉴权约束",
        "content": "后续必须携带 access token，否则会导致接口失败",
        "tags": "auth",
    }]

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    with mock.patch("server.routers.agents.extract_memories", return_value=returned_items), \
         mock.patch("server.routers.agents.SessionLocal", return_value=db), \
         mock.patch("server.routers.agents.threading.Thread", ImmediateThread):
        _trigger_extraction("sess-extract-cwd", None)

    db.expire_all()
    saved = db.query(Memory).filter(Memory.source_session_id == "sess-extract-cwd").one()
    refreshed_session = db.get(Session, "sess-extract-cwd")

    assert refreshed_session.project_id is not None
    assert saved.project_id == refreshed_session.project_id
```

- [ ] **Step 4: 运行单测，确认当前实现失败**

Run: `pytest tests/test_agents.py::test_trigger_extraction_backfills_project_from_session_cwd -v`

Expected: FAIL，断言 `refreshed_session.project_id is not None` 或 `saved.project_id == refreshed_session.project_id` 失败。

- [ ] **Step 5: 在 `server/routers/agents.py` 提炼出按 cwd 解析项目的共享辅助函数**

```python
def _ensure_project_for_cwd(cwd: Optional[str], db: DBSession) -> Optional[str]:
    normalized_cwd = _normalize_project_cwd(cwd or "")
    if not normalized_cwd:
        return None

    project_name = PurePath(normalized_cwd).name.strip()
    if not project_name:
        return None

    existing_project = db.query(ProjectModel).filter(ProjectModel.repo_url == normalized_cwd).first()
    if existing_project:
        return existing_project.id

    project = ProjectModel(name=project_name, repo_url=normalized_cwd)
    db.add(project)
    db.flush()
    return project.id


def _ensure_project_for_session(body: SessionCreate, db: DBSession) -> Optional[str]:
    if body.project_id:
        return body.project_id
    return _ensure_project_for_cwd(body.cwd, db)
```

- [ ] **Step 6: 在后台提炼逻辑里补齐 session 项目归属并直接启用短期记忆**

```python
session = save_db.get(SessionModel, session_id)
resolved_project_id = project_id
if session and not resolved_project_id:
    resolved_project_id = session.project_id
if session and not resolved_project_id:
    resolved_project_id = _ensure_project_for_cwd(session.cwd, save_db)
    if resolved_project_id and not session.project_id:
        session.project_id = resolved_project_id

items = extract_memories(summary, project_id=resolved_project_id)
now = time.time()
for item in items[:3]:
    save_db.add(MemoryModel(
        project_id=resolved_project_id,
        title=item["title"],
        content=item["content"],
        tags=item.get("tags"),
        source_session_id=session_id,
        status="active",
        tier="short",
        activated_at=now,
        updated_at=now,
    ))
```

- [ ] **Step 7: 运行 Task 1 的两个测试，确认都转绿**

Run: `pytest tests/test_agents.py::test_trigger_extraction_saves_active_short_memories_with_activation_time tests/test_agents.py::test_trigger_extraction_backfills_project_from_session_cwd -v`

Expected: PASS

- [ ] **Step 8: 运行现有提炼相关测试，确认没有破坏既有约束**

Run: `pytest tests/test_agents.py::test_trigger_extraction_prefers_messages_and_limits_saved_memories -v`

Expected: PASS

### Task 2: 增加启动期历史记忆修复

**Files:**
- Modify: `tests/test_main.py:1-49`
- Modify: `server/main.py:47-102`

- [ ] **Step 1: 写失败测试，定义“历史 pending 短期记忆直接启用并补 project_id”行为**

```python
def test_activate_short_pending_memories_backfills_project_id(monkeypatch, tmp_path):
    import server.main as main

    db_path = tmp_path / "repair-memories.db"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255), repo_url VARCHAR(512), created_at DOUBLE)"))
        conn.execute(text("CREATE TABLE sessions (id VARCHAR(36) PRIMARY KEY, project_id VARCHAR(36) NULL, parent_id VARCHAR(36) NULL, status VARCHAR(32), cwd VARCHAR(512), model VARCHAR(128), notes TEXT, started_at DOUBLE, ended_at DOUBLE NULL)"))
        conn.execute(text("CREATE TABLE memories (id VARCHAR(36) PRIMARY KEY, project_id VARCHAR(36) NULL, title VARCHAR(512) NOT NULL, content TEXT NOT NULL, tags VARCHAR(512) NULL, status VARCHAR(32) NULL, tier VARCHAR(32) NOT NULL, updated_at DOUBLE NULL, source_session_id VARCHAR(36) NULL, created_at DOUBLE NULL, activated_at DOUBLE NULL, score_total INT NOT NULL DEFAULT 0, feedback_count INT NOT NULL DEFAULT 0, last_feedback_at DOUBLE NULL, review_score INT NULL, review_reason VARCHAR(255) NULL)"))
        conn.execute(text("INSERT INTO sessions (id, project_id, status, cwd, started_at) VALUES ('sess-1', NULL, 'stopped', '/tmp/demo/CodeTogether', 1)"))
        conn.execute(text("INSERT INTO memories (id, project_id, title, content, status, tier, source_session_id, created_at, updated_at, score_total, feedback_count) VALUES ('mem-1', NULL, '规则', '这里不能跳过 access token，否则会导致失败', 'pending', 'short', 'sess-1', 1, 1, 0, 0)"))

    monkeypatch.setattr(main, "engine", engine)

    main._activate_short_pending_memories()

    with engine.connect() as conn:
        memory_row = conn.execute(text("SELECT status, tier, project_id, activated_at FROM memories WHERE id='mem-1'")) .fetchone()
        session_row = conn.execute(text("SELECT project_id FROM sessions WHERE id='sess-1'")) .fetchone()

    assert memory_row[0] == "active"
    assert memory_row[1] == "short"
    assert memory_row[2] is not None
    assert memory_row[2] == session_row[0]
    assert memory_row[3] is not None
```

- [ ] **Step 2: 运行单测，确认当前实现失败**

Run: `pytest tests/test_main.py::test_activate_short_pending_memories_backfills_project_id -v`

Expected: FAIL，`server.main` 中还没有 `_activate_short_pending_memories`。

- [ ] **Step 3: 在 `server/main.py` 增加幂等的历史修复函数**

```python
def _activate_short_pending_memories() -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(MemoryModel)
            .filter(
                MemoryModel.status == "pending",
                MemoryModel.tier == "short",
                MemoryModel.source_session_id.isnot(None),
            )
            .all()
        )
        now = time.time()
        for memory in rows:
            session = db.get(SessionModel, memory.source_session_id)
            resolved_project_id = memory.project_id
            if session and not resolved_project_id:
                resolved_project_id = session.project_id
            if session and not resolved_project_id:
                resolved_project_id = agents._ensure_project_for_cwd(session.cwd, db)
                if resolved_project_id and not session.project_id:
                    session.project_id = resolved_project_id
            memory.status = "active"
            memory.project_id = resolved_project_id
            if not memory.activated_at:
                memory.activated_at = now
            memory.updated_at = now
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

- [ ] **Step 4: 在启动迁移入口中调用历史修复函数**

```python
def _run_startup_migrations() -> None:
    Base.metadata.create_all(bind=engine)
    if not _is_sqlite:
        _ensure_event_columns()
        _migrate_memories_to_score_fields()
    _activate_short_pending_memories()
```

- [ ] **Step 5: 运行新增测试，确认历史修复逻辑通过**

Run: `pytest tests/test_main.py::test_activate_short_pending_memories_backfills_project_id -v`

Expected: PASS

- [ ] **Step 6: 补一条幂等测试，防止重复启动污染数据**

```python
def test_activate_short_pending_memories_is_idempotent(monkeypatch, tmp_path):
    import server.main as main

    db_path = tmp_path / "repair-memories-idempotent.db"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255), repo_url VARCHAR(512), created_at DOUBLE)"))
        conn.execute(text("CREATE TABLE sessions (id VARCHAR(36) PRIMARY KEY, project_id VARCHAR(36) NULL, parent_id VARCHAR(36) NULL, status VARCHAR(32), cwd VARCHAR(512), model VARCHAR(128), notes TEXT, started_at DOUBLE, ended_at DOUBLE NULL)"))
        conn.execute(text("CREATE TABLE memories (id VARCHAR(36) PRIMARY KEY, project_id VARCHAR(36) NULL, title VARCHAR(512) NOT NULL, content TEXT NOT NULL, tags VARCHAR(512) NULL, status VARCHAR(32) NULL, tier VARCHAR(32) NOT NULL, updated_at DOUBLE NULL, source_session_id VARCHAR(36) NULL, created_at DOUBLE NULL, activated_at DOUBLE NULL, score_total INT NOT NULL DEFAULT 0, feedback_count INT NOT NULL DEFAULT 0, last_feedback_at DOUBLE NULL, review_score INT NULL, review_reason VARCHAR(255) NULL)"))
        conn.execute(text("INSERT INTO sessions (id, project_id, status, cwd, started_at) VALUES ('sess-1', 'proj-1', 'stopped', '/tmp/demo/CodeTogether', 1)"))
        conn.execute(text("INSERT INTO memories (id, project_id, title, content, status, tier, source_session_id, created_at, updated_at, activated_at, score_total, feedback_count) VALUES ('mem-1', 'proj-1', '规则', '这里不能跳过 access token，否则会导致失败', 'active', 'short', 'sess-1', 1, 1, 2, 0, 0)"))

    monkeypatch.setattr(main, "engine", engine)

    main._activate_short_pending_memories()
    main._activate_short_pending_memories()

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT COUNT(*) FROM memories WHERE id='mem-1'")) .fetchone()
        status = conn.execute(text("SELECT status FROM memories WHERE id='mem-1'")) .fetchone()

    assert rows[0] == 1
    assert status[0] == "active"
```

- [ ] **Step 7: 运行两条 `tests/test_main.py`，确认修复逻辑完整可用**

Run: `pytest tests/test_main.py::test_activate_short_pending_memories_backfills_project_id tests/test_main.py::test_activate_short_pending_memories_is_idempotent -v`

Expected: PASS

### Task 3: 跑回归并检查当前项目视图契约

**Files:**
- Modify: `tests/test_agents.py:109-183`
- Modify: `tests/test_main.py:1-49`
- Verify: `mobile/app.js:499-522`

- [ ] **Step 1: 运行记忆/提炼相关测试集合**

Run: `pytest tests/test_agents.py tests/test_main.py tests/test_memory.py -v`

Expected: PASS

- [ ] **Step 2: 若有失败，做最小修正并重新运行相关用例**

```python
# 只修失败断言对应的最小实现，不调整无关接口语义；
# 尤其不要把 POST /memory 的默认 pending 行为一起改掉。
```

Run: `pytest tests/test_agents.py tests/test_main.py tests/test_memory.py -v`
Expected: PASS

- [ ] **Step 3: 用脚本核对当前项目下的历史脏数据已被修复**

Run:
```bash
python - <<'PY'
from sqlalchemy import text
from server.database import engine
repo = '/Users/qinepan/Desktop/search/CodeTogether'
with engine.connect() as conn:
    pid = conn.execute(text("select id from projects where repo_url=:repo"), {"repo": repo}).scalar()
    rows = conn.execute(text("select id, status, tier, project_id from memories where source_session_id is not null order by created_at desc limit 20")).fetchall()
    print('project_id=', pid)
    for row in rows:
        print(tuple(row))
PY
```

Expected: 新生成和已回填的自动记忆显示为 `active + short`，且本项目 session 对应记录的 `project_id` 不再为空。

- [ ] **Step 4: 记录验证结论，准备交付**

```text
- 自动提炼新记忆直接启用
- 当前项目下能查到对应自动记忆
- 历史 pending 短期记忆已启用并尽量补齐项目归属
```
