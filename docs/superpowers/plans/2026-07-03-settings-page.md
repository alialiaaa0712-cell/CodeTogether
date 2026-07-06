# Settings Page & Extractor Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增服务端配置存储（server_config 表）、`/config` API、extractor 运行时变量，以及手机端「设置」tab，admin 可在页面配置记忆提取参数。

**Architecture:** 服务端新增 `ServerConfig` 键值对表和 `/config` router，extractor 优先读运行时模块变量（回退环境变量）；手机端新增第三个 tab，通过 `GET /config` + `GET /admin/keys` 判断权限后展示只读或可编辑界面。

**Tech Stack:** FastAPI, SQLAlchemy, Vanilla JS

---

## 文件改动总览

| 文件 | 改动 |
|------|------|
| `server/models.py` | 新增 `ServerConfig` 模型 |
| `server/schemas.py` | 新增 `ConfigItemOut`、`ConfigUpdate` |
| `server/routers/config.py` | 新建：`GET /config`、`PUT /config` |
| `server/main.py` | 注册 config router，启动时加载配置写入 extractor |
| `server/services/extractor.py` | 新增模块级变量，`extract_memories` 优先读运行时变量 |
| `mobile/index.html` | 新增 `#view-settings`，tab-bar 加「设置」 |
| `mobile/style.css` | 设置页样式，退出按钮样式调整 |
| `mobile/app.js` | 设置 tab 逻辑，dom 引用，admin 判断，保存逻辑 |
| `tests/test_config.py` | 新建配置 API 测试 |

---

## CLAUDE.md 要求（子任务必须包含此项）

- 全程使用中文注释
- 函数/方法必须有文档注释（说明用途、参数、返回值）
- 查看代码时不相信注释，自己读代码判断

---

### Task 1：ServerConfig 模型 + schema

**Files:**
- Modify: `server/models.py`
- Modify: `server/schemas.py`
- Test: `tests/test_config.py`

- [ ] **Step 1：写失败测试**

新建 `tests/test_config.py`：

```python
import os
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from server.main import app


def test_server_config_table_exists(engine):
    """server_config 表应在数据库中存在。"""
    from sqlalchemy import inspect
    inspector = inspect(engine)
    assert "server_config" in inspector.get_table_names()


def test_get_config_requires_auth(client_no_auth):
    """无 key 时 GET /config 应返回 401。"""
    resp = client_no_auth.get("/config")
    assert resp.status_code == 401


def test_get_config_returns_three_keys(client):
    """GET /config 应返回 extractor 相关的三个配置项。"""
    resp = client.get("/config")
    assert resp.status_code == 200
    keys = {item["key"] for item in resp.json()}
    assert "extractor_api_key" in keys
    assert "extractor_base_url" in keys
    assert "extractor_model" in keys
```

- [ ] **Step 2：运行测试确认失败**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
pytest tests/test_config.py -v
```

期望：FAIL（`server_config` 表不存在，`/config` 端点不存在）

- [ ] **Step 3：在 server/models.py 末尾追加 ServerConfig 模型**

在 `ApiKey` 类之后追加：

```python
class ServerConfig(Base):
    """服务端运行时配置表，存储记忆提取等可在 Web 端调整的参数。"""
    __tablename__ = "server_config"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=True)
```

- [ ] **Step 4：在 server/schemas.py 末尾追加 Config schema**

```python
class ConfigItemOut(BaseModel):
    """单条配置项输出，api_key 值脱敏处理。"""
    model_config = ConfigDict(from_attributes=True)
    key: str
    value: str


class ConfigUpdate(BaseModel):
    """更新配置请求体，字段均可选，None 表示不更新。"""
    extractor_api_key: Optional[str] = None
    extractor_base_url: Optional[str] = None
    extractor_model: Optional[str] = None
```

- [ ] **Step 5：运行测试确认通过**

```bash
pytest tests/test_config.py::test_server_config_table_exists -v
```

期望：PASS（`/config` 端点测试仍 FAIL，下个 task 处理）

- [ ] **Step 6：提交**

```bash
git add server/models.py server/schemas.py tests/test_config.py
git commit -m "feat: 新增 ServerConfig 模型和 Config schema"
```

---

### Task 2：config router + main.py 集成

**Files:**
- Create: `server/routers/config.py`
- Modify: `server/main.py`

- [ ] **Step 1：新建 server/routers/config.py**

```python
"""服务端运行时配置路由。

GET /config 返回全部配置（所有登录用户可读，api_key 脱敏）。
PUT /config 更新配置（仅 admin key 可操作），更新后实时写入 extractor 运行时变量。
"""
from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import ApiKey, ServerConfig as ServerConfigModel
from server.routers.auth import get_admin_key, get_current_key
from server.schemas import ConfigItemOut, ConfigUpdate

router = APIRouter(prefix="/config", tags=["config"])

_DEFAULT_CONFIG = {
    "extractor_api_key": "",
    "extractor_base_url": "https://oneapi-comate.baidu-int.com/v1",
    "extractor_model": "gpt-5.4",
}


def _mask_api_key(value: str) -> str:
    """
    对 API Key 值进行脱敏，只显示最后 4 位。

    参数:
        value: 原始 API Key 字符串。

    返回值:
        脱敏后的字符串；为空时返回空字符串。
    """
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


def seed_default_config(db: DBSession) -> None:
    """
    若 server_config 表为空，写入三条默认配置记录。

    参数:
        db: 数据库会话。

    返回值:
        无；幂等，重复调用无副作用。
    """
    for key, value in _DEFAULT_CONFIG.items():
        if not db.get(ServerConfigModel, key):
            db.add(ServerConfigModel(key=key, value=value))
    db.commit()


@router.get("", response_model=List[ConfigItemOut])
def get_config(
    db: DBSession = Depends(get_db),
    _key: Optional[ApiKey] = Depends(get_current_key),
):
    """
    返回全部配置项，api_key 值脱敏。

    参数:
        db: 数据库会话。

    返回值:
        ConfigItemOut 列表。
    """
    rows = db.query(ServerConfigModel).all()
    result = []
    for row in rows:
        value = row.value or ""
        if row.key == "extractor_api_key":
            value = _mask_api_key(value)
        result.append(ConfigItemOut(key=row.key, value=value))
    return result


@router.put("")
def update_config(
    body: ConfigUpdate,
    db: DBSession = Depends(get_db),
    _key: ApiKey = Depends(get_admin_key),
):
    """
    更新配置项，更新后实时写入 extractor 运行时变量。仅 admin key 可调用。

    参数:
        body: 包含可选配置字段的请求体。
        db: 数据库会话。

    返回值:
        {"ok": true}
    """
    from server.services import extractor as _extractor

    updates = {
        "extractor_api_key": body.extractor_api_key,
        "extractor_base_url": body.extractor_base_url,
        "extractor_model": body.extractor_model,
    }
    for key, value in updates.items():
        if value is None:
            continue
        row = db.get(ServerConfigModel, key)
        if row:
            row.value = value
        else:
            db.add(ServerConfigModel(key=key, value=value))

    db.commit()

    # 实时更新 extractor 运行时变量
    if body.extractor_api_key is not None:
        _extractor._api_key = body.extractor_api_key
    if body.extractor_base_url is not None:
        _extractor._base_url = body.extractor_base_url
    if body.extractor_model is not None:
        _extractor._model = body.extractor_model

    return {"ok": True}
```

- [ ] **Step 2：在 server/main.py 中注册 config router 并启动时加载配置**

在 `server/main.py` 中：

1. 在 import 区加：
```python
from server.routers import config as config_router
from server.routers.config import seed_default_config
```

2. 在 `_run_startup_migrations` 函数内 `seed_admin_key(db)` 之后加：
```python
seed_default_config(db)
# 从数据库加载配置，写入 extractor 运行时变量
from server.services import extractor as _extractor
from server.models import ServerConfig as ServerConfigModel
rows = db.query(ServerConfigModel).all()
config_map = {r.key: r.value or "" for r in rows}
_extractor._api_key = config_map.get("extractor_api_key", "")
_extractor._base_url = config_map.get("extractor_base_url", "https://oneapi-comate.baidu-int.com/v1")
_extractor._model = config_map.get("extractor_model", "gpt-5.4")
```

3. 在 `app.include_router(auth_router.router)` 之后加：
```python
app.include_router(config_router.router)
```

- [ ] **Step 3：运行测试确认通过**

```bash
pytest tests/test_config.py -v
```

期望：3 个 PASS

- [ ] **Step 4：运行全量测试确认无回归**

```bash
pytest tests/ -q --ignore=tests/test_codetogether.py 2>&1 | tail -5
```

期望：155+ PASSED

- [ ] **Step 5：提交**

```bash
git add server/routers/config.py server/main.py
git commit -m "feat: 新增 /config 路由，启动时加载配置写入 extractor"
```

---

### Task 3：extractor 运行时变量

**Files:**
- Modify: `server/services/extractor.py`

- [ ] **Step 1：在 server/services/extractor.py 顶部新增三个模块变量**

在 `logger = logging.getLogger(__name__)` 之后插入：

```python
# 运行时配置变量，由 config router 写入，优先于环境变量
# 服务启动时从 server_config 表加载（见 server/main.py _run_startup_migrations）
_api_key: str = ""
_base_url: str = ""
_model: str = ""
```

- [ ] **Step 2：修改 extract_memories 函数，优先读运行时变量**

将 `extract_memories` 函数内原有的 client 和 model 创建代码（约第 67-71 行）：

```python
client = OpenAI(
    api_key=os.getenv("CT_EXTRACTOR_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN", ""),
    base_url=os.getenv("CT_EXTRACTOR_BASE_URL", "https://oneapi-comate.baidu-int.com/v1"),
)
model = os.getenv("CT_EXTRACTOR_MODEL", "gpt-5.4")
```

替换为：

```python
api_key = _api_key or os.getenv("CT_EXTRACTOR_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN", "")
base_url = _base_url or os.getenv("CT_EXTRACTOR_BASE_URL", "https://oneapi-comate.baidu-int.com/v1")
model = _model or os.getenv("CT_EXTRACTOR_MODEL", "gpt-5.4")
client = OpenAI(api_key=api_key, base_url=base_url)
```

- [ ] **Step 3：在 tests/test_config.py 末尾追加测试**

```python
def test_extractor_runtime_vars_used():
    """extractor 应优先使用运行时变量而不是环境变量。"""
    from server.services import extractor as _extractor
    from unittest.mock import patch, MagicMock

    _extractor._api_key = "runtime-key"
    _extractor._base_url = "https://runtime.example.com/v1"
    _extractor._model = "runtime-model"

    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop here")

    with patch("server.services.extractor.OpenAI", side_effect=fake_openai):
        try:
            _extractor.extract_memories("test summary")
        except Exception:
            pass

    assert captured.get("api_key") == "runtime-key"
    assert captured.get("base_url") == "https://runtime.example.com/v1"

    # 清理
    _extractor._api_key = ""
    _extractor._base_url = ""
    _extractor._model = ""
```

- [ ] **Step 4：运行测试确认通过**

```bash
pytest tests/test_config.py -v
```

期望：4 个 PASS

- [ ] **Step 5：提交**

```bash
git add server/services/extractor.py tests/test_config.py
git commit -m "feat: extractor 优先读运行时变量，回退环境变量"
```

---

### Task 4：手机端设置页 HTML + 样式

**Files:**
- Modify: `mobile/index.html`
- Modify: `mobile/style.css`

- [ ] **Step 1：修改 mobile/index.html**

**修改 1**：在 `<main class="page-shell">` 内，`</main>` 闭合标签之前，追加设置视图（在记忆视图 `#view-memory` 之后）：

```html
    <!-- 设置页 -->
    <section id="view-settings" class="view">
      <section class="view-section-head compact-head">
        <div>
          <h2>设置</h2>
        </div>
      </section>
      <div class="card settings-card">
        <div id="settings-readonly-hint" class="settings-hint" style="display:none">仅 Admin 可修改配置</div>
        <label class="settings-label" for="settings-api-key">记忆提取 API Key</label>
        <input id="settings-api-key" class="settings-input" type="password" placeholder="留空使用服务端环境变量" autocomplete="off">
        <label class="settings-label" for="settings-base-url">Base URL</label>
        <input id="settings-base-url" class="settings-input" type="text" placeholder="https://...">
        <label class="settings-label" for="settings-model">模型名</label>
        <input id="settings-model" class="settings-input" type="text" placeholder="gpt-5.4">
        <button id="settings-save" class="settings-save" type="button" style="display:none">保存</button>
        <p id="settings-msg" class="settings-msg" style="display:none"></p>
      </div>
    </section>
```

**修改 2**：在 `<nav class="tab-bar">` 中追加第三个 tab 按钮：

```html
  <nav class="tab-bar">
    <button class="tab-btn active" data-tab="agents" type="button">Agent</button>
    <button class="tab-btn" data-tab="memory" type="button">记忆</button>
    <button class="tab-btn" data-tab="settings" type="button">设置</button>
  </nav>
```

**修改 3**：更新 `app.js` 版本号，将 `app.js?v=20260702b` 改为 `app.js?v=20260703a`

- [ ] **Step 2：在 mobile/style.css 末尾追加样式**

```css
/* 设置页 */
.settings-card {
  display: flex;
  flex-direction: column;
  gap: .6rem;
  padding: 1.2rem 1rem;
}

.settings-hint {
  font-size: .85rem;
  color: var(--text-secondary, #888);
  padding: .4rem .6rem;
  background: var(--bg, #f5f5f7);
  border-radius: .4rem;
}

.settings-label {
  font-size: .82rem;
  font-weight: 500;
  color: var(--text-secondary, #666);
}

.settings-input {
  width: 100%;
  padding: .55rem .75rem;
  border: 1px solid var(--border, #ddd);
  border-radius: .5rem;
  font-size: .9rem;
  box-sizing: border-box;
  outline: none;
  background: var(--card-bg, #fff);
}

.settings-input:focus {
  border-color: var(--accent, #007aff);
}

.settings-input:disabled {
  background: var(--bg, #f5f5f7);
  color: var(--text-secondary, #999);
}

.settings-save {
  align-self: flex-end;
  padding: .45rem 1.2rem;
  border: none;
  border-radius: .5rem;
  background: var(--accent, #007aff);
  color: #fff;
  font-size: .9rem;
  cursor: pointer;
}

.settings-save:active { opacity: .85; }

.settings-msg {
  font-size: .82rem;
  text-align: center;
  margin: 0;
}

/* topbar 退出按钮 — 低调文字链接风格 */
.logout-btn {
  background: none;
  border: none;
  padding: .1rem .3rem;
  font-size: .75rem;
  color: var(--text-secondary, #999);
  cursor: pointer;
  opacity: 0.7;
}

.logout-btn:hover { opacity: 1; }
```

注意：新的 `.logout-btn` 样式会覆盖 style.css 中已有的同名规则，**删除旧的 `.logout-btn` 规则块**（搜索并删除旧的那一段）。

- [ ] **Step 3：提交**

```bash
git add mobile/index.html mobile/style.css
git commit -m "feat: 手机端设置页 HTML 和样式"
```

---

### Task 5：手机端设置页 JS 逻辑

**Files:**
- Modify: `mobile/app.js`

完成后 app.js 需具备：
1. `dom` 对象包含 `#view-settings` 及所有设置页元素引用
2. `state.isAdmin` 字段记录当前用户是否为 admin
3. `loadSettings()` 函数：调用 `GET /config` + `GET /admin/keys` 确定权限，填充输入框
4. `switchTab("settings")` 时触发 `loadSettings()`
5. `#settings-save` 点击调用 `PUT /config`
6. `dom.views` 包含 `settings: document.getElementById("view-settings")`

- [ ] **Step 1：在 dom 对象中追加设置页元素引用**

在 `dom` 对象的 `loginError` 行之后追加：

```js
  settingsApiKey: document.getElementById("settings-api-key"),
  settingsBaseUrl: document.getElementById("settings-base-url"),
  settingsModel: document.getElementById("settings-model"),
  settingsSave: document.getElementById("settings-save"),
  settingsMsg: document.getElementById("settings-msg"),
  settingsReadonlyHint: document.getElementById("settings-readonly-hint"),
```

在 `dom.views` 对象中追加：

```js
    settings: document.getElementById("view-settings"),
```

- [ ] **Step 2：在 state 对象中追加 isAdmin 字段**

在 `state` 对象中追加：

```js
  isAdmin: false,
```

- [ ] **Step 3：新增 loadSettings 函数**

在 `connectWebSocket` 函数之前插入：

```js
/**
 * 加载设置页配置，判断 admin 权限后决定是否显示保存按钮。
 *
 * 调用 GET /config 获取配置（api_key 脱敏），再调用 GET /admin/keys 判断是否 admin。
 * 非 admin 时输入框禁用，显示只读提示。
 *
 * 返回值:
 *   无。
 */
async function loadSettings() {
  try {
    const configs = await fetchJson(`${SERVER}/config`);
    const map = Object.fromEntries(configs.map((c) => [c.key, c.value]));
    dom.settingsApiKey.value = map.extractor_api_key || "";
    dom.settingsBaseUrl.value = map.extractor_base_url || "";
    dom.settingsModel.value = map.extractor_model || "";
  } catch (_) {}

  try {
    await fetchJson(`${SERVER}/admin/keys`);
    state.isAdmin = true;
  } catch (_) {
    state.isAdmin = false;
  }

  const readonly = !state.isAdmin;
  dom.settingsApiKey.disabled = readonly;
  dom.settingsBaseUrl.disabled = readonly;
  dom.settingsModel.disabled = readonly;
  dom.settingsSave.style.display = readonly ? "none" : "";
  dom.settingsReadonlyHint.style.display = readonly ? "" : "none";
  dom.settingsMsg.style.display = "none";
}
```

- [ ] **Step 4：修改 switchTab，settings tab 时加载设置**

在 `switchTab` 函数内，找到：

```js
  if (tab === "memory") {
    loadMemories().catch(...);
  }
```

在其之后追加：

```js
  if (tab === "settings") {
    loadSettings().catch((e) => {
      console.error("加载设置失败", e);
    });
  }
```

- [ ] **Step 5：在文件底部 event listener 区绑定保存按钮**

在 `dom.loginSubmit` 事件绑定之后、`init().catch(...)` 之前，插入：

```js
if (dom.settingsSave) {
  dom.settingsSave.addEventListener("click", async () => {
    dom.settingsSave.disabled = true;
    dom.settingsMsg.style.display = "none";
    try {
      await fetchJson(`${SERVER}/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          extractor_api_key: dom.settingsApiKey.value.trim() || null,
          extractor_base_url: dom.settingsBaseUrl.value.trim() || null,
          extractor_model: dom.settingsModel.value.trim() || null,
        }),
      });
      dom.settingsMsg.textContent = "已保存";
      dom.settingsMsg.style.color = "var(--accent, #007aff)";
      dom.settingsMsg.style.display = "";
    } catch (_) {
      dom.settingsMsg.textContent = "保存失败，请重试";
      dom.settingsMsg.style.color = "#e53e3e";
      dom.settingsMsg.style.display = "";
    } finally {
      dom.settingsSave.disabled = false;
    }
  });
}
```

- [ ] **Step 6：运行全量测试确认后端无回归**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
pytest tests/ -q --ignore=tests/test_codetogether.py 2>&1 | tail -5
```

期望：155+ PASSED

- [ ] **Step 7：提交**

```bash
git add mobile/app.js
git commit -m "feat: 手机端设置页 JS 逻辑"
```
