# 手机端认证设计

**日期**：2026-06-14  
**状态**：已确认

---

## 目标

手机端 Web App 加入 API Key 认证，使其与服务端认证体系对齐：用户首次访问需输入 API Key，所有后续请求携带 Bearer Token，服务端读端点和 WebSocket 均受保护。

---

## 整体改动范围

| 组件 | 改动 |
|------|------|
| `mobile/index.html` | 新增登录覆盖层 HTML |
| `mobile/app.js` | 认证状态管理、fetchJson 注入 header、WebSocket URL 带 api_key、退出登录 |
| `server/main.py` | WebSocket 握手从 query string 读取并验证 api_key |
| `server/routers/agents.py` | GET 端点加 `Depends(get_current_key)` |
| `server/routers/chat.py` | GET 端点加 `Depends(get_current_key)` |
| `server/routers/memory.py` | GET 端点加 `Depends(get_current_key)` |
| `tests/` | 相关测试用例补充 |

---

## 第一节：手机端登录页

### 登录覆盖层

在 `index.html` `<body>` 内追加一个全屏覆盖 `<div id="login-overlay">`，包含：
- 标题文字"CodeTogether"
- 说明文字"请输入 API Key 以继续"
- `<input id="login-key-input" type="password" placeholder="ct-xxxxxxxx...">`
- `<button id="login-submit">确认</button>`
- 错误提示 `<p id="login-error">`（默认隐藏）

### 认证状态管理

`app.js` 中新增认证模块（在 `state` 对象之前）：

```js
const _LS_API_KEY = "ct_api_key";

function getApiKey() {
  return localStorage.getItem(_LS_API_KEY) || "";
}

function authHeaders() {
  const key = getApiKey();
  return key ? { "Authorization": `Bearer ${key}` } : {};
}

function showLogin() {
  document.getElementById("login-overlay").style.display = "flex";
}

function hideLogin() {
  document.getElementById("login-overlay").style.display = "none";
}
```

### 启动流程

`DOMContentLoaded` 时检查 `getApiKey()`：
- 有 key → `hideLogin()`，正常初始化（调用 `loadUiState`、`connectWs`、`loadAgents` 等）
- 无 key → `showLogin()`，不初始化

`login-submit` 点击事件：
1. 读取 input value，trim
2. 若为空，显示错误"请输入 API Key"
3. 向 `GET /agents` 发一次带 header 的探测请求（用于验证 key 是否有效）
4. 若 401 → 显示错误"API Key 无效"
5. 若成功 → `localStorage.setItem(_LS_API_KEY, key)`，`hideLogin()`，初始化 App

### 退出登录

在 topbar 右侧加一个"退出"按钮（`id="logout-btn"`）：
- 点击 → `localStorage.removeItem(_LS_API_KEY)`，`location.reload()`

---

## 第二节：所有请求携带 Authorization 头

### fetchJson

现有函数签名不变，在 options 合并阶段注入认证头：

```js
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

401 时自动退出到登录页，避免用户看到一堆错误弹窗。

### WebSocket URL

```js
function buildWsUrl() {
  const key = getApiKey();
  return `${WS_PROTOCOL}//${location.host}/ws${key ? "?api_key=" + encodeURIComponent(key) : ""}`;
}
```

`connectWs()` 中将 `WS_URL` 替换为 `buildWsUrl()`。

---

## 第三节：服务端读端点认证

### HTTP 端点

所有 GET 端点加 `_key: Optional[ApiKey] = Depends(get_current_key)`（已豁免的 `/` 和 `/mobile/*` 不受影响）：

- `GET /agents` — `list_sessions`
- `GET /agents/{session_id}` — `get_session`
- `GET /agents/{session_id}/events` — `get_events`
- `GET /chat/{session_id}/history` — `get_history`
- `GET /chat/{session_id}/messages` — `poll_messages`
- `GET /memory/` — `list_memories`
- `GET /memory/search` — `search_memories`

### WebSocket 认证

`server/main.py` 中 `/ws` 端点从 query string 读取并验证：

```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, api_key: str = ""):
    db = SessionLocal()
    try:
        if api_key:
            key_hash = _hash_key(api_key)
            ok = db.query(ApiKey).filter(
                ApiKey.key_hash == key_hash,
                ApiKey.is_active == 1,
            ).first()
            if not ok:
                await websocket.close(code=4001)
                return
    finally:
        db.close()
    await manager.connect(websocket)
    ...
```

若 `api_key` 为空（本地无认证场景），`get_current_key` 已保证 HTTP 路径豁免；WebSocket 也在无 key 时放行（保持本地模式兼容）。

---

## 兼容性说明

- 本地无 `CODETOGETHER_API_KEY` 的旧配置：WS 不带 `api_key` 参数，服务端直接放行，保持向后兼容
- 服务端若未设置 `ADMIN_KEY`，所有端点实际上不校验（`get_current_key` 在数据库无记录时查不到 key），已有行为不变

---

## 不在本次范围内

- 注册/找回 API Key UI（由管理员通过 `/admin/keys` 端点管理）
- 记住登录设备 / 过期时间（localStorage 持久存储，除非手动退出或清除浏览器数据）
