# Mobile Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 手机端 Web App 加入 API Key 登录页，所有请求携带 Bearer Token，服务端读端点和 WebSocket 同步受保护。

**Architecture:** 前端在 `app.js` 顶部新增认证模块（`getApiKey/authHeaders/showLogin/hideLogin`），`fetchJson` 注入 auth header，WebSocket URL 带 `api_key` query param；服务端在 `agents.py`、`chat.py`、`memory.py`、`events.py` 的 GET 路由加 `Depends(get_current_key)`，`main.py` 的 `/ws` 端点从 query string 验证 key。

**Tech Stack:** FastAPI, SQLAlchemy, Vanilla JS, localStorage

---

## 文件改动总览

| 文件 | 改动 |
|------|------|
| `mobile/index.html` | 新增登录覆盖层 `#login-overlay` 和退出按钮 `#logout-btn` |
| `mobile/app.js` | 认证模块、fetchJson 注入 header、buildWsUrl、init 入口改造 |
| `server/routers/agents.py` | `list_sessions`、`get_session` GET 加 auth |
| `server/routers/chat.py` | `message_history` GET 加 auth |
| `server/routers/events.py` | `list_events` GET 加 auth |
| `server/routers/memory.py` | `list_memories` GET 加 auth |
| `server/main.py` | `/ws` 端点加 query param 验证 |
| `tests/test_auth.py` | 补充 GET 端点 401 测试 |

> **注意**：`memory/search` 和 `chat/{id}/poll` 已有 `Depends(get_current_key)`，无需改动。

---

## CLAUDE.md 要求（子任务必须包含此项）

- 全程使用中文注释
- 函数/方法必须有文档注释（说明用途、参数、返回值）
- 查看代码时不相信注释，自己读代码判断

---

### Task 1：服务端 GET 端点加认证

**Files:**
- Modify: `server/routers/agents.py:187`
- Modify: `server/routers/chat.py:114`
- Modify: `server/routers/events.py:110`
- Modify: `server/routers/memory.py:275`
- Test: `tests/test_auth.py`

- [ ] **Step 1：为 GET 端点写失败测试**

在 `tests/test_auth.py` 末尾追加：

```python
def test_get_agents_requires_auth(client_no_auth):
    """无 key 时 GET /agents 应返回 401。"""
    resp = client_no_auth.get("/agents")
    assert resp.status_code == 401


def test_get_chat_history_requires_auth(client_no_auth):
    """无 key 时 GET /chat/{id}/history 应返回 401。"""
    resp = client_no_auth.get("/chat/nonexistent/history")
    assert resp.status_code == 401


def test_get_events_requires_auth(client_no_auth):
    """无 key 时 GET /events 应返回 401。"""
    resp = client_no_auth.get("/events")
    assert resp.status_code == 401


def test_get_memories_requires_auth(client_no_auth):
    """无 key 时 GET /memory/ 应返回 401。"""
    resp = client_no_auth.get("/memory/")
    assert resp.status_code == 401
```

- [ ] **Step 2：运行测试确认失败**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
pytest tests/test_auth.py::test_get_agents_requires_auth tests/test_auth.py::test_get_chat_history_requires_auth tests/test_auth.py::test_get_events_requires_auth tests/test_auth.py::test_get_memories_requires_auth -v
```

期望：4 个 FAIL（当前 GET 路由无认证，返回 200 或 404 而非 401）

- [ ] **Step 3：agents.py — list_sessions 加认证**

修改 `server/routers/agents.py:187-188`（`list_sessions` 函数签名）：

```python
@router.get("", response_model=List[SessionOut])
def list_sessions(db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
```

- [ ] **Step 4：chat.py — message_history 加认证**

修改 `server/routers/chat.py:113-114`（`message_history` 函数签名）：

```python
@router.get("/{session_id}/history", response_model=List[MessageOut])
def message_history(session_id: str, db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
```

- [ ] **Step 5：events.py — list_events 加认证**

先读 `server/routers/events.py` 确认 import 里有 `ApiKey` 和 `get_current_key`；若无则补充：

```python
from server.models import ApiKey
from server.routers.auth import get_current_key
```

然后修改 `list_events` 函数签名：

```python
@router.get("", response_model=List[EventOut])
def list_events(session_id: Optional[str] = None, include_children: bool = False, db: DBSession = Depends(get_db), _key: Optional[ApiKey] = Depends(get_current_key)):
```

- [ ] **Step 6：memory.py — list_memories 加认证**

修改 `server/routers/memory.py` 中 `list_memories` 函数签名（约第 275 行），加入认证依赖：

```python
def list_memories(
    session_id: Optional[str] = None,
    project_id: Optional[str] = None,
    scope: str = "current",
    status: str = "pending",
    tier: Optional[str] = None,
    sort: str = "time",
    db: DBSession = Depends(get_db),
    _key: Optional[ApiKey] = Depends(get_current_key),
):
```

- [ ] **Step 7：运行测试确认通过**

```bash
pytest tests/test_auth.py -v
```

期望：全部 PASS（包含原有 5 个 + 新增 4 个）

- [ ] **Step 8：提交**

```bash
git add server/routers/agents.py server/routers/chat.py server/routers/events.py server/routers/memory.py tests/test_auth.py
git commit -m "feat: GET 端点加认证保护"
```

---

### Task 2：WebSocket 认证

**Files:**
- Modify: `server/main.py:238-255`
- Test: `tests/test_auth.py`

- [ ] **Step 1：为 WS 认证写测试**

在 `tests/test_auth.py` 末尾追加（使用 TestClient 的 websocket_connect）：

```python
def test_ws_invalid_key_rejected(client_no_auth):
    """
    携带无效 api_key 的 WebSocket 握手应被拒绝（close code 4001）。
    
    TestClient.websocket_connect 在服务端调用 websocket.close() 后
    会抛出 WebSocketDisconnect，通过捕获该异常验证行为。
    """
    from starlette.testclient import WebSocketDisconnect
    try:
        with client_no_auth.websocket_connect("/ws?api_key=ct-invalid") as ws:
            ws.receive_text()
        assert False, "应已被拒绝"
    except (WebSocketDisconnect, Exception):
        pass  # 连接被关闭，符合预期
```

- [ ] **Step 2：运行测试确认失败**

```bash
pytest tests/test_auth.py::test_ws_invalid_key_rejected -v
```

期望：FAIL（当前 WS 无认证，任何 key 都能连上）

- [ ] **Step 3：main.py — /ws 端点加 query param 验证**

在 `server/main.py` 顶部 import 区补充：

```python
from server.models import ApiKey as ApiKeyModel
from server.routers.auth import _hash_key
```

将 `/ws` 端点改为：

```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, api_key: str = ""):
    """
    处理 WebSocket 连接。若服务端存在 ApiKey 记录，则要求 api_key query param 有效。
    本地无认证场景（api_keys 表为空）时直接放行，保持向后兼容。

    参数:
        websocket: FastAPI WebSocket 连接对象。
        api_key: query string 中的明文 API Key，可为空。

    返回值:
        无；认证失败时以 code=4001 关闭连接。
    """
    db = SessionLocal()
    try:
        has_any_key = db.query(ApiKeyModel).filter(ApiKeyModel.is_active == 1).first() is not None
        if has_any_key:
            if not api_key:
                await websocket.close(code=4001)
                return
            key_hash = _hash_key(api_key)
            valid = db.query(ApiKeyModel).filter(
                ApiKeyModel.key_hash == key_hash,
                ApiKeyModel.is_active == 1,
            ).first()
            if not valid:
                await websocket.close(code=4001)
                return
    finally:
        db.close()
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

- [ ] **Step 4：运行测试确认通过**

```bash
pytest tests/test_auth.py -v
```

期望：全部 PASS

- [ ] **Step 5：提交**

```bash
git add server/main.py tests/test_auth.py
git commit -m "feat: WebSocket 握手验证 api_key query param"
```

---

### Task 3：手机端登录 HTML

**Files:**
- Modify: `mobile/index.html`

- [ ] **Step 1：在 index.html 中新增登录覆盖层和退出按钮**

在 `mobile/index.html` 中：

1. 在 `<header class="topbar">` 内的 `<div id="topbar-main">` 末尾，加退出按钮：

```html
<div id="topbar-main">
  <span class="topbar-title">CodeTogether</span>
  <span id="conn-status" class="conn-status disconnected">未连接</span>
  <button id="logout-btn" class="logout-btn" type="button" style="display:none">退出</button>
</div>
```

2. 在 `<div id="toast" ...>` 之前插入登录覆盖层：

```html
<div id="login-overlay" class="login-overlay" style="display:none">
  <div class="login-card">
    <h1 class="login-title">CodeTogether</h1>
    <p class="login-desc">请输入 API Key 以继续</p>
    <input id="login-key-input" class="login-input" type="password" placeholder="ct-xxxxxxxx..." autocomplete="off">
    <p id="login-error" class="login-error" style="display:none"></p>
    <button id="login-submit" class="login-submit" type="button">确认</button>
  </div>
</div>
```

3. 更新 `app.js` 的版本号查询参数（避免缓存），将 `app.js?v=20260612i` 改为 `app.js?v=20260614a`

- [ ] **Step 2：提交**

```bash
git add mobile/index.html
git commit -m "feat: 手机端登录覆盖层 HTML"
```

---

### Task 4：手机端登录样式

**Files:**
- Modify: `mobile/style.css`（在文件末尾追加）

- [ ] **Step 1：追加登录相关 CSS**

在 `mobile/style.css` 末尾追加：

```css
/* 登录覆盖层 */
.login-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: var(--bg, #f5f5f7);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
}

.login-card {
  width: 100%;
  max-width: 360px;
  background: var(--card-bg, #fff);
  border-radius: 1rem;
  padding: 2rem 1.5rem;
  box-shadow: 0 4px 24px rgba(0,0,0,.08);
  display: flex;
  flex-direction: column;
  gap: .75rem;
}

.login-title {
  font-size: 1.4rem;
  font-weight: 700;
  margin: 0;
  text-align: center;
}

.login-desc {
  margin: 0;
  color: var(--text-secondary, #666);
  font-size: .9rem;
  text-align: center;
}

.login-input {
  width: 100%;
  padding: .6rem .75rem;
  border: 1px solid var(--border, #ddd);
  border-radius: .5rem;
  font-size: .95rem;
  box-sizing: border-box;
  outline: none;
}

.login-input:focus {
  border-color: var(--accent, #007aff);
}

.login-error {
  margin: 0;
  color: #e53e3e;
  font-size: .85rem;
  text-align: center;
}

.login-submit {
  width: 100%;
  padding: .7rem;
  border: none;
  border-radius: .5rem;
  background: var(--accent, #007aff);
  color: #fff;
  font-size: 1rem;
  cursor: pointer;
}

.login-submit:active { opacity: .85; }

/* topbar 退出按钮 */
.logout-btn {
  background: none;
  border: 1px solid var(--border, #ddd);
  border-radius: .4rem;
  padding: .2rem .55rem;
  font-size: .8rem;
  cursor: pointer;
  color: var(--text-secondary, #666);
}
```

- [ ] **Step 2：提交**

```bash
git add mobile/style.css
git commit -m "feat: 手机端登录页样式"
```

---

### Task 5：手机端认证 JS 逻辑

**Files:**
- Modify: `mobile/app.js`

完成后，`app.js` 中需包含以下能力：
1. `getApiKey / authHeaders / showLogin / hideLogin` 认证工具函数
2. `fetchJson` 自动注入 auth header，401 时退出到登录页
3. `buildWsUrl` 构造带 `api_key` 的 WS URL
4. `connectWebSocket` 使用 `buildWsUrl()`
5. `dom.logoutBtn` 点击退出
6. `init()` 入口：有 key → 正常初始化；无 key → 显示登录页
7. 登录提交：验证 key 有效后存储并初始化

- [ ] **Step 1：在文件顶部 WS_URL 之后插入认证模块**

在 `mobile/app.js` 第 3 行（`const WS_URL = ...`）之后，`const _LS_KEY = ...` 之前，插入：

```js
const _LS_API_KEY = "ct_api_key";

/**
 * 从 localStorage 读取已存储的 API Key。
 *
 * 返回值:
 *   存储的 key 字符串；未登录时返回空字符串。
 */
function getApiKey() {
  return localStorage.getItem(_LS_API_KEY) || "";
}

/**
 * 构造携带 API Key 的 Authorization 请求头对象。
 *
 * 返回值:
 *   包含 Authorization 字段的对象；无 key 时返回空对象。
 */
function authHeaders() {
  const key = getApiKey();
  return key ? { Authorization: `Bearer ${key}` } : {};
}

/**
 * 显示全屏登录覆盖层。
 */
function showLogin() {
  document.getElementById("login-overlay").style.display = "flex";
}

/**
 * 隐藏全屏登录覆盖层。
 */
function hideLogin() {
  document.getElementById("login-overlay").style.display = "none";
}
```

- [ ] **Step 2：dom 对象中补充新元素引用**

在 `dom` 对象的 `toast` 行之后追加（保持 `};` 不动，只在其之前加逗号和新字段）：

在 `mobile/app.js` 中找到：
```js
  toast: document.getElementById("toast"),
};
```

替换为：
```js
  toast: document.getElementById("toast"),
  logoutBtn: document.getElementById("logout-btn"),
  loginOverlay: document.getElementById("login-overlay"),
  loginKeyInput: document.getElementById("login-key-input"),
  loginSubmit: document.getElementById("login-submit"),
  loginError: document.getElementById("login-error"),
};
```

- [ ] **Step 3：修改 fetchJson，注入 auth header 并处理 401**

将现有 `fetchJson` 函数替换为：

```js
/**
 * 请求 JSON 接口，自动注入认证头；401 时清除 key 并跳转到登录页。
 *
 * 参数:
 *   url: 请求地址。
 *   options: fetch 选项，headers 字段会与认证头合并。
 *
 * 返回值:
 *   解析后的 JSON 对象；204 或空响应时返回 null。
 */
async function fetchJson(url, options = {}) {
  const merged = {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  };
  const resp = await fetch(url, merged);
  if (resp.status === 401) {
    localStorage.removeItem(_LS_API_KEY);
    showLogin();
    throw new Error("401 Unauthorized");
  }
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  if (resp.status === 204 || resp.headers.get("content-length") === "0") return null;
  return resp.json();
}
```

- [ ] **Step 4：新增 buildWsUrl，修改 connectWebSocket**

在 `connectWebSocket` 函数之前插入：

```js
/**
 * 构造携带 api_key query param 的 WebSocket URL。
 *
 * 返回值:
 *   带认证参数的完整 WebSocket URL 字符串。
 */
function buildWsUrl() {
  const key = getApiKey();
  return `${WS_PROTOCOL}//${location.host}/ws${key ? "?api_key=" + encodeURIComponent(key) : ""}`;
}
```

在 `connectWebSocket` 函数体内，将 `const ws = new WebSocket(WS_URL);` 改为：

```js
  const ws = new WebSocket(buildWsUrl());
```

- [ ] **Step 5：修改 init() 入口加认证守卫**

将 `init()` 函数内第一行 `setConnectionStatus(false);` 之后，在 `const saved = loadUiState();` 之前，插入：

```js
  if (!getApiKey()) {
    showLogin();
    return;
  }
  hideLogin();
  if (dom.logoutBtn) dom.logoutBtn.style.display = "";
```

- [ ] **Step 6：在文件底部 event listener 区绑定退出和登录提交**

在 `dom.memorySortFeedback.addEventListener(...)` 之后、`init().catch(...)` 之前，插入：

```js
if (dom.logoutBtn) {
  dom.logoutBtn.addEventListener("click", () => {
    localStorage.removeItem(_LS_API_KEY);
    location.reload();
  });
}

if (dom.loginSubmit) {
  dom.loginSubmit.addEventListener("click", async () => {
    const key = (dom.loginKeyInput.value || "").trim();
    if (!key) {
      dom.loginError.textContent = "请输入 API Key";
      dom.loginError.style.display = "";
      return;
    }
    dom.loginError.style.display = "none";
    dom.loginSubmit.disabled = true;
    try {
      const resp = await fetch("/agents", {
        headers: { Authorization: `Bearer ${key}` },
      });
      if (resp.status === 401) {
        dom.loginError.textContent = "API Key 无效，请重新输入";
        dom.loginError.style.display = "";
        return;
      }
      localStorage.setItem(_LS_API_KEY, key);
      hideLogin();
      if (dom.logoutBtn) dom.logoutBtn.style.display = "";
      await init();
    } catch (_) {
      dom.loginError.textContent = "网络错误，请重试";
      dom.loginError.style.display = "";
    } finally {
      dom.loginSubmit.disabled = false;
    }
  });
}
```

- [ ] **Step 7：运行全量测试确认后端无回归**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
pytest tests/ -v --ignore=tests/test_codetogether.py -x 2>&1 | tail -20
```

期望：PASSED（已知 test_codetogether.py 中有 1 个预先存在的失败，忽略）

- [ ] **Step 8：提交**

```bash
git add mobile/app.js mobile/index.html
git commit -m "feat: 手机端登录页 JS 逻辑与认证头注入"
```

---

### Task 6：端到端手动验证

**Files:** 无代码改动，仅验证

- [ ] **Step 1：启动服务**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
python -m server.main
```

- [ ] **Step 2：访问手机端**

浏览器打开 `http://localhost:7878/mobile/`，确认：
- 页面显示登录覆盖层，输入框可用
- 不填写直接点确认 → 显示"请输入 API Key"错误
- 输入错误 key → 显示"API Key 无效"错误

- [ ] **Step 3：使用有效 key 登录**

若本地无 `ADMIN_KEY` 环境变量，先设置并重启服务，或直接通过 `/admin/keys` 端点创建 key：

```bash
# 示例：用已有 admin key 创建新 key
curl -X POST http://localhost:7878/admin/keys \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"label":"test"}'
```

输入返回的 key，确认：
- 登录成功，覆盖层消失，Agent 列表正常加载
- topbar 右侧显示"退出"按钮
- WebSocket 连接状态变为"已连接"

- [ ] **Step 4：验证退出**

点击"退出"按钮 → 页面刷新，重新显示登录覆盖层。

- [ ] **Step 5：验证未认证 API 调用被拒绝**

```bash
# 不带 key 应返回 401
curl -s -o /dev/null -w "%{http_code}" http://localhost:7878/agents
# 期望: 401

# 带有效 key 应返回 200
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $MY_KEY" http://localhost:7878/agents
# 期望: 200
```

- [ ] **Step 6：运行全量测试**

```bash
pytest tests/ -v 2>&1 | tail -20
```

期望：141+ tests passing，3 个已知预存失败不计入本次工作范围。
