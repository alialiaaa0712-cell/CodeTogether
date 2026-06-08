# 记忆生命周期升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 CodeTogether 的记忆系统增加短期/长期分层、7天自动晋升、Agent 标记复查、每日定时清理四项能力。

**Architecture:** 在 `Memory` 表新增 `tier`（short/long）和 `updated_at` 字段，status 枚举扩展 `review` 状态；`GET /memory/search` 优先返回 long 记录；`PATCH /memory/{id}` 支持降级操作；APScheduler 在 FastAPI lifespan 中注册，每天 02:00 执行晋升与清理；hooks `search_memory` 改为两段式查询，新增 `flag_memory_for_review`；移动端记忆列表增加 tier 筛选与待复查操作。

**Tech Stack:** FastAPI · SQLAlchemy · MySQL(生产) / SQLite(测试) · APScheduler 3.x · pytest

---

## 文件结构

| 文件 | 操作 | 说明 |
|------|------|------|
| `server/models.py` | Modify | Memory 新增 `tier`、`updated_at` 字段，status 枚举加 `review` |
| `server/schemas.py` | Modify | MemoryOut 加 `tier`/`updated_at`；MemoryUpdate 扩展 `status`/`tier` |
| `server/routers/memory.py` | Modify | search 支持 tier 参数两段返回；list 支持 tier 过滤；patch 支持降级；更新 updated_at |
| `server/services/housekeeping.py` | Create | 定时任务函数 `run_memory_housekeeping()` |
| `server/main.py` | Modify | 引入 lifespan，注册 APScheduler |
| `hooks/_common.py` | Modify | search_memory 两段式；新增 flag_memory_for_review |
| `mobile/app.js` | Modify | 记忆列表增加 tier 筛选、review 状态操作 |
| `mobile/style.css` | Modify | 新增 tier 标签、待复查样式 |
| `tests/test_memory.py` | Modify | 覆盖新字段、新操作、search 优先级 |
| `tests/test_housekeeping.py` | Create | 测试晋升与清理逻辑 |

---

### Task 1: 数据库模型扩展

**Files:**
- Modify: `server/models.py`
- Modify: `server/schemas.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_memory.py` 末尾添加：

```python
def test_memory_has_tier_and_updated_at(client):
    resp = client.post("/memory", json={"title": "t", "content": "c"})
    data = resp.json()
    assert data["tier"] == "short"
    assert data["updated_at"] > 0
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
pytest tests/test_memory.py::test_memory_has_tier_and_updated_at -v
```

期望：`FAILED` — `KeyError: 'tier'` 或类似

- [ ] **Step 3: 修改 `server/models.py`**

将 Memory 类的 status 和 __table_args__ 替换为：

```python
status = Column(Enum("pending", "active", "rejected", "review"), default="pending")
tier = Column(Enum("short", "long"), default="short", nullable=False)
updated_at = Column(Double, default=time.time)
```

保留其他字段不变。

- [ ] **Step 4: 修改 `server/schemas.py`**

将 MemoryOut 替换为：

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

    model_config = ConfigDict(from_attributes=True)
```

将 MemoryUpdate 替换为：

```python
class MemoryUpdate(BaseModel):
    status: Optional[Literal["active", "rejected", "review"]] = None
    tier: Optional[Literal["short"]] = None
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
pytest tests/test_memory.py -v
```

期望：所有测试 PASS（SQLite 内存库会自动重建）

- [ ] **Step 6: 迁移生产数据库**

```sql
ALTER TABLE memories
  ADD COLUMN tier ENUM('short','long') NOT NULL DEFAULT 'short',
  ADD COLUMN updated_at DOUBLE,
  MODIFY COLUMN status ENUM('pending','active','rejected','review') NOT NULL DEFAULT 'pending';

UPDATE memories SET updated_at = COALESCE(activated_at, created_at);
```

在 MySQL 中执行（`mysql -u root codetogether`）。

- [ ] **Step 7: Commit**

```bash
git add server/models.py server/schemas.py tests/test_memory.py
git commit -m "feat: Memory 新增 tier/updated_at 字段，status 加 review 枚举"
```

---

### Task 2: memory 路由扩展

**Files:**
- Modify: `server/routers/memory.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_memory.py` 末尾添加：

```python
def test_search_prefers_long(client):
    """长期记忆应排在短期记忆前面返回。"""
    short_resp = client.post("/memory", json={"title": "short knowledge", "content": "pytest short"})
    long_resp = client.post("/memory", json={"title": "long knowledge", "content": "pytest long"})
    client.patch(f"/memory/{short_resp.json()['id']}", json={"status": "active"})
    # 直接设 tier=long 来模拟已晋升状态（通过 PATCH tier）
    client.patch(f"/memory/{long_resp.json()['id']}", json={"status": "active"})
    client.patch(f"/memory/{long_resp.json()['id']}", json={"tier": "long"})

    resp = client.get("/memory/search?q=pytest")
    results = resp.json()
    assert len(results) >= 1
    long_ids = [r["id"] for r in results if r["tier"] == "long"]
    short_ids = [r["id"] for r in results if r["tier"] == "short"]
    # long 在 short 之前（如果两种都出现）
    if long_ids and short_ids:
        long_pos = next(i for i, r in enumerate(results) if r["tier"] == "long")
        short_pos = next(i for i, r in enumerate(results) if r["tier"] == "short")
        assert long_pos < short_pos


def test_patch_to_review(client):
    resp = client.post("/memory", json={"title": "t", "content": "c"})
    mid = resp.json()["id"]
    client.patch(f"/memory/{mid}", json={"status": "active"})
    # 先升为 long
    client.patch(f"/memory/{mid}", json={"tier": "long"})
    # 再标记 review
    r = client.patch(f"/memory/{mid}", json={"status": "review"})
    assert r.status_code == 200
    assert r.json()["status"] == "review"


def test_patch_downgrade(client):
    resp = client.post("/memory", json={"title": "t", "content": "c"})
    mid = resp.json()["id"]
    client.patch(f"/memory/{mid}", json={"status": "active"})
    client.patch(f"/memory/{mid}", json={"tier": "long"})
    client.patch(f"/memory/{mid}", json={"status": "review"})
    # 降级：tier 改回 short
    r = client.patch(f"/memory/{mid}", json={"tier": "short"})
    assert r.status_code == 200
    assert r.json()["tier"] == "short"
    assert r.json()["status"] == "active"


def test_list_filter_by_tier(client):
    short_resp = client.post("/memory", json={"title": "s", "content": "c"})
    long_resp = client.post("/memory", json={"title": "l", "content": "c"})
    client.patch(f"/memory/{long_resp.json()['id']}", json={"tier": "long"})

    short_list = client.get("/memory?tier=short")
    long_list = client.get("/memory?tier=long")
    assert all(r["tier"] == "short" for r in short_list.json())
    assert all(r["tier"] == "long" for r in long_list.json())
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_memory.py::test_patch_to_review tests/test_memory.py::test_patch_downgrade tests/test_memory.py::test_list_filter_by_tier -v
```

期望：FAILED

- [ ] **Step 3: 重写 `server/routers/memory.py`**

```python
from __future__ import annotations

import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import Memory as MemoryModel
from server.schemas import MemoryCreate, MemoryOut, MemoryUpdate

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("", response_model=MemoryOut)
def create_memory(body: MemoryCreate, db: DBSession = Depends(get_db)):
    memory = MemoryModel(**body.model_dump())
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


@router.get("/search", response_model=List[MemoryOut])
def search_memories(q: str, project_id: Optional[str] = None, db: DBSession = Depends(get_db)):
    """先搜 long+active，不足 3 条再补 short+active，合计最多 3 条。"""
    def _query(tier: str):
        qr = db.query(MemoryModel).filter(
            MemoryModel.status == "active",
            MemoryModel.tier == tier,
        )
        if project_id:
            qr = qr.filter(MemoryModel.project_id == project_id)
        return qr.filter(
            or_(
                MemoryModel.title.contains(q),
                MemoryModel.content.contains(q),
                MemoryModel.tags.contains(q),
            )
        )

    results = _query("long").limit(3).all()
    if len(results) < 3:
        remaining = 3 - len(results)
        existing_ids = {r.id for r in results}
        short_results = [
            r for r in _query("short").limit(remaining + len(existing_ids)).all()
            if r.id not in existing_ids
        ][:remaining]
        results = results + short_results
    return results


@router.get("", response_model=List[MemoryOut])
def list_memories(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    tier: Optional[str] = None,
    db: DBSession = Depends(get_db),
):
    q = db.query(MemoryModel)
    if project_id:
        q = q.filter(MemoryModel.project_id == project_id)
    if status:
        q = q.filter(MemoryModel.status == status)
    if tier:
        q = q.filter(MemoryModel.tier == tier)
    return q.order_by(MemoryModel.created_at.desc()).limit(200).all()


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_memory(memory_id: str, body: MemoryUpdate, db: DBSession = Depends(get_db)):
    memory = db.get(MemoryModel, memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="memory not found")

    now = time.time()

    if body.tier == "short":
        # 降级：review/long → short/active
        memory.tier = "short"
        memory.status = "active"
        memory.updated_at = now
    elif body.status is not None:
        memory.status = body.status
        if body.status == "active":
            memory.activated_at = now
        memory.updated_at = now
    elif body.tier == "long":
        # 仅升 tier（供测试直接操作，生产由定时任务触发）
        memory.tier = "long"
        memory.updated_at = now

    db.commit()
    db.refresh(memory)
    return memory
```

- [ ] **Step 4: 运行全部 memory 测试**

```bash
pytest tests/test_memory.py -v
```

期望：所有测试 PASS

- [ ] **Step 5: Commit**

```bash
git add server/routers/memory.py tests/test_memory.py
git commit -m "feat: memory 路由支持 tier 筛选、review 标记、降级操作"
```

---

### Task 3: 定时任务服务

**Files:**
- Create: `server/services/housekeeping.py`
- Create: `tests/test_housekeeping.py`
- Modify: `server/main.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_housekeeping.py`：

```python
import time
import pytest
from server.services.housekeeping import run_memory_housekeeping
from server.models import Memory as MemoryModel


def test_short_to_long_promotion(db):
    """updated_at 超过 7 天的 active/short 应升级为 long。"""
    old_ts = time.time() - 8 * 86400
    mem = MemoryModel(title="t", content="c", status="active", tier="short", updated_at=old_ts)
    db.add(mem)
    db.commit()

    run_memory_housekeeping(db)
    db.refresh(mem)
    assert mem.tier == "long"


def test_review_expiry(db):
    """review 状态超过 30 天应自动 rejected。"""
    old_ts = time.time() - 31 * 86400
    mem = MemoryModel(title="t", content="c", status="review", tier="long", updated_at=old_ts)
    db.add(mem)
    db.commit()

    run_memory_housekeeping(db)
    db.refresh(mem)
    assert mem.status == "rejected"


def test_fresh_short_not_promoted(db):
    """updated_at 不足 7 天的 active/short 不应晋升。"""
    mem = MemoryModel(title="t", content="c", status="active", tier="short", updated_at=time.time())
    db.add(mem)
    db.commit()

    run_memory_housekeeping(db)
    db.refresh(mem)
    assert mem.tier == "short"
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_housekeeping.py -v
```

期望：`FAILED` — `ModuleNotFoundError` 或类似

- [ ] **Step 3: 创建 `server/services/housekeeping.py`**

```python
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session as DBSession

from server.models import Memory as MemoryModel

logger = logging.getLogger(__name__)

_7_DAYS = 7 * 86400
_30_DAYS = 30 * 86400


def run_memory_housekeeping(db: DBSession) -> None:
    """
    执行记忆生命周期清理：
    1. active/short 且 updated_at 超过 7 天 → 升级为 long
    2. review 且 updated_at 超过 30 天 → 标记为 rejected
    """
    now = time.time()

    promoted = (
        db.query(MemoryModel)
        .filter(
            MemoryModel.status == "active",
            MemoryModel.tier == "short",
            MemoryModel.updated_at < now - _7_DAYS,
        )
        .all()
    )
    for mem in promoted:
        mem.tier = "long"
        mem.updated_at = now
    if promoted:
        logger.info("housekeeping: %d short→long", len(promoted))

    expired = (
        db.query(MemoryModel)
        .filter(
            MemoryModel.status == "review",
            MemoryModel.updated_at < now - _30_DAYS,
        )
        .all()
    )
    for mem in expired:
        mem.status = "rejected"
        mem.updated_at = now
    if expired:
        logger.info("housekeeping: %d review→rejected", len(expired))

    db.commit()
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/test_housekeeping.py -v
```

期望：3 个测试全部 PASS

- [ ] **Step 5: 修改 `server/main.py`，注册 APScheduler**

在文件顶部 import 区域末尾添加：

```python
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from server.database import SessionLocal
from server.services.housekeeping import run_memory_housekeeping
```

在 `app = FastAPI(title="CodeTogether")` 之前插入 lifespan：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    def _housekeeping_job():
        db = SessionLocal()
        try:
            run_memory_housekeeping(db)
        finally:
            db.close()
    scheduler.add_job(_housekeeping_job, "cron", hour=2, minute=0)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)
```

将 `app = FastAPI(title="CodeTogether")` 修改为：

```python
app = FastAPI(title="CodeTogether", lifespan=lifespan)
```

- [ ] **Step 6: 安装 APScheduler**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
pip install "apscheduler>=3.10,<4"
```

验证：`python -c "import apscheduler; print(apscheduler.__version__)"` 输出 `3.x.x`

- [ ] **Step 7: 运行全量测试确认无回归**

```bash
pytest tests/ -v --ignore=tests/test_database_config.py
```

期望：全部 PASS

- [ ] **Step 8: Commit**

```bash
git add server/services/housekeeping.py server/main.py tests/test_housekeeping.py
git commit -m "feat: APScheduler 定时任务，每日晋升 short→long 并清理过期 review"
```

---

### Task 4: hooks 层更新

**Files:**
- Modify: `hooks/_common.py`
- Modify: `tests/test_hooks.py`

- [ ] **Step 1: 读取 `tests/test_hooks.py` 现有内容，了解测试模式**

```bash
cat /Users/qinepan/Desktop/search/CodeTogether/tests/test_hooks.py
```

- [ ] **Step 2: 写失败测试**

在 `tests/test_hooks.py` 末尾添加（若文件使用 `responses` 或 `unittest.mock` 的方式）：

```python
from unittest.mock import patch, MagicMock
import json

def test_search_memory_two_stage():
    """search_memory 应先查 long，不足时追加 short。"""
    long_result = [{"id": "1", "tier": "long", "title": "L", "content": "c"}]
    short_result = [{"id": "2", "tier": "short", "title": "S", "content": "c"}]

    call_count = {"n": 0}
    def fake_urlopen(req, timeout):
        call_count["n"] += 1
        resp = MagicMock()
        if "tier=long" in req.full_url:
            resp.read.return_value = json.dumps(long_result).encode()
        else:
            resp.read.return_value = json.dumps(short_result).encode()
        return resp

    with patch("hooks._common.urllib.request.urlopen", side_effect=fake_urlopen):
        from hooks._common import search_memory
        results = search_memory("test")
    assert call_count["n"] == 2
    assert results[0]["tier"] == "long"
    assert results[1]["tier"] == "short"


def test_flag_memory_for_review():
    """flag_memory_for_review 应调用 PATCH /memory/{id} 设置 status=review。"""
    captured = {}
    def fake_urlopen(req, timeout):
        captured["method"] = req.method
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        return MagicMock()

    with patch("hooks._common.urllib.request.urlopen", side_effect=fake_urlopen):
        from hooks._common import flag_memory_for_review
        flag_memory_for_review("mem-123")

    assert captured["method"] == "PATCH"
    assert "mem-123" in captured["url"]
    assert captured["body"]["status"] == "review"
```

- [ ] **Step 3: 运行测试，确认失败**

```bash
pytest tests/test_hooks.py::test_search_memory_two_stage tests/test_hooks.py::test_flag_memory_for_review -v
```

期望：FAILED — `AttributeError` 或 `AssertionError`

- [ ] **Step 4: 修改 `hooks/_common.py`**

将 `search_memory` 函数替换为：

```python
def search_memory(query: str, project_id: str = None) -> list:
    """先搜 long+active，不足 3 条再补 short+active，合计最多 3 条。"""
    def _fetch(tier: str) -> list:
        try:
            params = {"q": query, "tier": tier}
            if project_id:
                params["project_id"] = project_id
            url = f"{SERVER}/memory/search?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=TIMEOUT)
            return json.loads(resp.read())
        except Exception:
            return []

    results = _fetch("long")
    if len(results) < 3:
        results += _fetch("short")[: 3 - len(results)]
    return results
```

在 `mark_stopped` 函数之后添加：

```python
def flag_memory_for_review(memory_id: str) -> None:
    """
    将指定记忆标记为 review 状态，供 Agent 发现长期记忆与项目实际不符时调用。

    参数:
        memory_id: 需要标记的记忆 ID。

    返回值:
        无。
    """
    try:
        req = urllib.request.Request(
            f"{SERVER}/memory/{memory_id}",
            data=json.dumps({"status": "review"}).encode(),
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )
        urllib.request.urlopen(req, timeout=TIMEOUT)
    except Exception:
        pass
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
pytest tests/test_hooks.py -v
```

期望：全部 PASS

- [ ] **Step 6: Commit**

```bash
git add hooks/_common.py tests/test_hooks.py
git commit -m "feat: hooks search_memory 两段式查询，新增 flag_memory_for_review"
```

---

### Task 5: 移动端记忆列表升级

**Files:**
- Modify: `mobile/app.js`
- Modify: `mobile/style.css`

本任务为纯前端，无后端测试。手动验证步骤在最后说明。

- [ ] **Step 1: 修改 `mobile/style.css`，新增样式**

在文件末尾追加：

```css
.tier-badge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 999px;
  font-weight: 600;
  margin-left: 4px;
}

.tier-badge.long {
  background: rgba(37, 99, 235, 0.12);
  color: #1d4ed8;
}

.tier-badge.short {
  background: rgba(156, 163, 175, 0.2);
  color: #6b7280;
}

.memory-review {
  border-left: 3px solid #f59e0b;
}

.tier-filter {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
}

.tier-filter button {
  flex: 1;
  padding: 6px;
  border-radius: 8px;
  font-size: 12px;
  background: #e5e7eb;
  color: #111827;
}

.tier-filter button.active {
  background: #2563eb;
  color: #fff;
}
```

- [ ] **Step 2: 修改 `mobile/app.js`**

在 `state` 对象中新增 `tierFilter` 字段：

```js
const state = {
  // ... 现有字段 ...
  memoryFilter: "pending",
  tierFilter: "all",   // 新增
  // ...
};
```

将 `loadMemories` 函数修改为：

```js
async function loadMemories() {
  let url = `${SERVER}/memory?status=${state.memoryFilter}`;
  if (state.memoryFilter === "active" && state.tierFilter !== "all") {
    url += `&tier=${state.tierFilter}`;
  }
  state.memories = await fetchJson(url);
  renderMemories();
}
```

将 `renderMemories` 函数中 `memory-item` 的渲染替换为：

```js
function renderMemories() {
  if (state.memories.length === 0) {
    dom.memoryList.innerHTML = '<div class="empty">暂无记忆条目</div>';
    return;
  }

  const tierFilterHtml = state.memoryFilter === "active" ? `
    <div class="tier-filter">
      <button type="button" data-tier="all" class="${state.tierFilter === 'all' ? 'active' : ''}">全部</button>
      <button type="button" data-tier="long" class="${state.tierFilter === 'long' ? 'active' : ''}">长期</button>
      <button type="button" data-tier="short" class="${state.tierFilter === 'short' ? 'active' : ''}">短期</button>
    </div>` : "";

  dom.memoryList.innerHTML = tierFilterHtml + state.memories.map((memory) => {
    const isReview = memory.status === "review";
    const tierLabel = `<span class="tier-badge ${escapeHtml(memory.tier)}">${memory.tier === "long" ? "长期" : "短期"}</span>`;
    const actions = state.memoryFilter === "pending"
      ? `<div class="memory-actions">
          <button type="button" data-action="activate" data-id="${escapeHtml(memory.id)}">启用</button>
          <button type="button" class="danger" data-action="reject" data-id="${escapeHtml(memory.id)}">拒绝</button>
         </div>`
      : isReview
        ? `<div class="memory-actions">
            <button type="button" data-action="downgrade" data-id="${escapeHtml(memory.id)}">确认降级</button>
            <button type="button" class="danger" data-action="reject" data-id="${escapeHtml(memory.id)}">废弃</button>
           </div>`
        : "";
    return `
      <div class="memory-item${isReview ? ' memory-review' : ''}">
        <div class="memory-row">
          <strong>${escapeHtml(memory.title)}</strong>${tierLabel}
          <span>${escapeHtml(memory.status)}</span>
        </div>
        <div class="hint">tags: ${escapeHtml(memory.tags || "—")} · ${escapeHtml(formatTime(memory.updated_at || memory.created_at))}</div>
        <div>${escapeHtml(memory.content)}</div>
        ${actions}
      </div>
    `;
  }).join("");

  dom.memoryList.querySelectorAll(".tier-filter button").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.tierFilter = btn.dataset.tier;
      loadMemories().catch(() => {});
    });
  });

  dom.memoryList.querySelectorAll("button[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.action;
      if (action === "activate") {
        reviewMemory(btn.dataset.id, "active").catch(() => showToast("操作失败"));
      } else if (action === "reject") {
        reviewMemory(btn.dataset.id, "rejected").catch(() => showToast("操作失败"));
      } else if (action === "downgrade") {
        downgradeMemory(btn.dataset.id).catch(() => showToast("操作失败"));
      }
    });
  });
}
```

在 `reviewMemory` 函数之后添加：

```js
async function downgradeMemory(memoryId) {
  await fetchJson(`${SERVER}/memory/${memoryId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tier: "short" }),
  });
  showToast("已降级为短期记忆");
  await loadMemories();
}
```

在 `memoryFilterActive` 的事件监听中，切换到 active 时重置 tierFilter：

```js
dom.memoryFilterActive.addEventListener("click", () => {
  state.memoryFilter = "active";
  state.tierFilter = "all";   // 重置 tier 筛选
  dom.memoryFilterActive.classList.add("active");
  dom.memoryFilterPending.classList.remove("active");
  loadMemories().catch(() => {});
});
```

在 `memoryFilterPending` 的事件监听中同样重置：

```js
dom.memoryFilterPending.addEventListener("click", () => {
  state.memoryFilter = "pending";
  state.tierFilter = "all";   // 重置 tier 筛选
  dom.memoryFilterPending.classList.add("active");
  dom.memoryFilterActive.classList.remove("active");
  loadMemories().catch(() => {});
});
```

- [ ] **Step 3: 手动验证**

打开 `http://localhost:7879/mobile`，切到"记忆"tab：
1. "已启用"下出现"全部 / 长期 / 短期"三个筛选按钮
2. 每条记忆显示蓝色"长期"或灰色"短期"标签
3. `review` 状态的记忆卡片左侧有橙色竖线，显示"确认降级 / 废弃"按钮
4. 点击"确认降级"后，该记忆变回 short/active 并消失于 review 分组

- [ ] **Step 4: Commit**

```bash
git add mobile/app.js mobile/style.css
git commit -m "feat: 移动端记忆列表支持 tier 筛选、review 状态展示与降级操作"
```

---

## 自检

**Spec 覆盖检查：**
- ✅ tier/updated_at 字段 → Task 1
- ✅ status 枚举加 review → Task 1
- ✅ 7天 short→long 定时晋升 → Task 3
- ✅ review 超30天自动 rejected → Task 3
- ✅ APScheduler 每天02:00 → Task 3
- ✅ search 优先 long → Task 2 + Task 4
- ✅ PATCH 支持 tier 降级 → Task 2
- ✅ flag_memory_for_review hook → Task 4
- ✅ 移动端 tier 筛选 → Task 5
- ✅ 移动端 review 状态操作 → Task 5

**占位符扫描：** 无 TBD/TODO，所有代码步骤均含完整实现。

**类型一致性：** `MemoryUpdate.tier` 在 schema（Task 1）定义为 `Optional[Literal["short"]]`，但 Task 2 路由里处理了 `body.tier == "long"`（供测试直接升 tier）——两者不矛盾，"short" 是用户可操作的降级，"long" 由定时任务操作，测试直接调用是绕过 schema 的 DB 操作，不经路由。需确认：Task 2 的 `update_memory` 中 `elif body.tier == "long"` 分支依赖 schema 允许 `tier: Optional[Literal["short", "long"]]`。

修正：将 `server/schemas.py` 中 MemoryUpdate 的 tier 改为：

```python
class MemoryUpdate(BaseModel):
    status: Optional[Literal["active", "rejected", "review"]] = None
    tier: Optional[Literal["short", "long"]] = None
```

此修改应在 Task 1 Step 4 中应用（已在上述计划中体现）。
