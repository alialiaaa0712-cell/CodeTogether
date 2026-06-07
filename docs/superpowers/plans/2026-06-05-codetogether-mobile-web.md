# CodeTogether Mobile Web App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 CodeTogether 实现一个可在手机浏览器访问的移动 Web App，支持查看 Agent 状态、发送聊天消息、审核记忆条目。

**Architecture:** 采用纯 HTML/CSS/JS 单页应用，静态资源由 FastAPI 挂载在 `/mobile` 路径下，前端通过 REST API 读取 sessions/events/messages/memories，通过现有 `/ws` WebSocket 接收实时事件更新。保留现有 `/` 健康检查不变，手机端入口使用 `/mobile/index.html`。

**Tech Stack:** FastAPI StaticFiles、纯 HTML/CSS/JavaScript（零构建工具）、pytest + FastAPI TestClient

---

## 项目上下文

当前项目已经完成：
- 服务器 API：`/agents`、`/events`、`/chat`、`/memory`
- Hooks：`hooks/pre_tool.py`、`hooks/post_tool.py`、`hooks/stop.py`
- WebSocket：`/ws`

当前还没有静态前端入口，`server/main.py` 仅提供健康检查 `GET /` 和 WebSocket。

手机 Web App 的第一期范围只有 3 个页面能力：
1. **状态页**：查看所有 Agent 运行状态、最近工具事件时间线
2. **聊天页**：给指定 session 发送消息、查看历史消息、感知实时进展
3. **记忆页**：浏览 pending/active 记忆，并审核 pending → active / rejected

已有 API 可直接复用：
- `GET /agents`
- `GET /events?session_id=<id>`
- `POST /chat`
- `GET /chat/{session_id}/history`
- `GET /memory?status=pending|active`
- `PATCH /memory/{memory_id}`
- `WS /ws`

---

## 文件结构

```
CodeTogether/
├── mobile/
│   ├── index.html      # 手机端单页入口，包含状态/聊天/记忆三个 tab
│   ├── style.css       # 移动端样式（卡片布局、底部 tab、状态徽标）
│   └── app.js          # 前端逻辑：REST API、WebSocket、渲染、交互
├── server/
│   └── main.py         # 挂载 /mobile 静态资源
├── tests/
│   └── test_mobile.py  # 手机 Web App 静态服务与前端资源 smoke tests
└── README.md           # 手机入口与使用说明
```

---

### Task 1: 挂载 `/mobile` 静态入口

**Files:**
- Create: `mobile/index.html`
- Create: `mobile/style.css`
- Create: `mobile/app.js`
- Create: `tests/test_mobile.py`
- Modify: `server/main.py:1-54`

> 关键约束：`tests/conftest.py` 在导入时会加载 `server.main:app`。因此必须先创建 `mobile/` 目录和静态文件，再让 `main.py` 挂载 `StaticFiles`，避免导入阶段因目录不存在而失败。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_mobile.py`：

```python
from pathlib import Path


def test_root_still_returns_healthcheck(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "CodeTogether"}


def test_mobile_index_is_served(client):
    resp = client.get("/mobile/index.html")
    assert resp.status_code == 200
    assert "CodeTogether Mobile" in resp.text


def test_mobile_assets_are_served(client):
    css = client.get("/mobile/style.css")
    js = client.get("/mobile/app.js")
    assert css.status_code == 200
    assert js.status_code == 200
    assert ".topbar" in css.text
    assert 'console.log("CodeTogether mobile ready")' in js.text
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_mobile.py -v`
Expected: `test_mobile_index_is_served` 和 `test_mobile_assets_are_served` 因 404 失败

- [ ] **Step 3: 创建 `mobile/` 目录与占位静态文件**

```html
<!-- mobile/index.html -->
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>CodeTogether Mobile</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="topbar">
    <h1>CodeTogether Mobile</h1>
  </header>
  <main class="page-shell">
    <p>loading...</p>
  </main>
  <script src="app.js"></script>
</body>
</html>
```

```css
/* mobile/style.css */
html, body {
  margin: 0;
  padding: 0;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif;
  background: #f5f7fb;
  color: #18212f;
}

.topbar {
  padding: 16px;
  background: #111827;
  color: #fff;
}
```

```javascript
// mobile/app.js
console.log("CodeTogether mobile ready");
```

- [ ] **Step 4: 修改 `server/main.py`，挂载 `/mobile` 静态资源**

将 `server/main.py` 改为：

```python
from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.database import Base, engine
from server.routers import agents, chat, events, memory
from server.ws_manager import ConnectionManager

logging.basicConfig(level=logging.INFO)

if not os.getenv("TESTING"):
    Base.metadata.create_all(bind=engine)

app = FastAPI(title="CodeTogether")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()
app.state.ws_manager = manager

_mobile_dir = Path(__file__).parent.parent / "mobile"
app.mount("/mobile", StaticFiles(directory=str(_mobile_dir), html=True), name="mobile")

app.include_router(agents.router)
app.include_router(events.router)
app.include_router(chat.router)
app.include_router(memory.router)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/")
def root():
    return {"status": "ok", "service": "CodeTogether"}


if __name__ == "__main__":
    port = int(os.getenv("SERVER_PORT", "7878"))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_mobile.py -v`
Expected: 3 tests passed

- [ ] **Step 6: 提交**

```bash
git add mobile/index.html mobile/style.css mobile/app.js server/main.py tests/test_mobile.py
git commit -m "feat: 挂载 mobile 静态入口"
```

---

### Task 2: 实现手机端页面骨架与移动样式

**Files:**
- Modify: `mobile/index.html`
- Modify: `mobile/style.css`
- Modify: `tests/test_mobile.py`

- [ ] **Step 1: 在 `tests/test_mobile.py` 末尾追加失败测试**

```python

def test_mobile_shell_contains_three_tabs(client):
    html = client.get("/mobile/index.html").text
    assert 'id="tab-status"' in html
    assert 'id="tab-chat"' in html
    assert 'id="tab-memory"' in html


def test_mobile_shell_contains_chat_and_memory_controls(client):
    html = client.get("/mobile/index.html").text
    assert 'id="chat-session-select"' in html
    assert 'id="chat-form"' in html
    assert 'id="memory-list"' in html
    assert 'id="memory-filter-pending"' in html


def test_mobile_css_contains_mobile_layout_rules(client):
    css = client.get("/mobile/style.css").text
    assert ".tab-bar" in css
    assert ".view.active" in css
    assert ".card" in css
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_mobile.py -v -k "shell or layout"`
Expected: 因缺少 tab 和样式规则失败

- [ ] **Step 3: 完整实现 `mobile/index.html`**

```html
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="description" content="CodeTogether Mobile Web App">
  <title>CodeTogether Mobile</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="topbar">
    <div>
      <h1>CodeTogether</h1>
      <p class="subtitle">手机查看 Agent 状态、聊天与记忆审核</p>
    </div>
    <span id="conn-status" class="conn-status disconnected">未连接</span>
  </header>

  <main class="page-shell">
    <section id="view-status" class="view active">
      <div class="card">
        <h2>运行状态</h2>
        <div id="session-list" class="session-list"></div>
      </div>
      <div class="card">
        <h2>最近事件</h2>
        <div id="event-list" class="event-list"></div>
      </div>
    </section>

    <section id="view-chat" class="view">
      <div class="card">
        <label for="chat-session-select">目标 Session</label>
        <select id="chat-session-select"></select>
      </div>
      <div class="card">
        <h2>聊天历史</h2>
        <div id="chat-history" class="chat-history"></div>
      </div>
      <form id="chat-form" class="chat-form">
        <textarea id="chat-input" rows="3" placeholder="输入发给 Agent 的消息"></textarea>
        <button id="chat-send" type="submit">发送</button>
      </form>
      <p class="hint">消息会在 Agent 下一次工具调用时送达。</p>
    </section>

    <section id="view-memory" class="view">
      <div class="card">
        <div class="memory-toolbar">
          <button id="memory-filter-pending" class="pill active" type="button">待审核</button>
          <button id="memory-filter-active" class="pill" type="button">已启用</button>
        </div>
        <div id="memory-list" class="memory-list"></div>
      </div>
    </section>
  </main>

  <nav class="tab-bar">
    <button id="tab-status" class="tab-btn active" data-tab="status" type="button">状态</button>
    <button id="tab-chat" class="tab-btn" data-tab="chat" type="button">聊天</button>
    <button id="tab-memory" class="tab-btn" data-tab="memory" type="button">记忆</button>
  </nav>

  <div id="toast" class="toast"></div>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 4: 完整实现 `mobile/style.css`**

```css
html, body {
  margin: 0;
  padding: 0;
  min-height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif;
  background: #f3f6fb;
  color: #18212f;
}

* {
  box-sizing: border-box;
}

body {
  padding-bottom: 72px;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px;
  background: linear-gradient(135deg, #111827, #1f2937);
  color: #fff;
}

.topbar h1 {
  margin: 0;
  font-size: 20px;
}

.subtitle {
  margin: 4px 0 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.78);
}

.conn-status {
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  white-space: nowrap;
}

.conn-status.connected {
  background: rgba(52, 211, 153, 0.2);
  color: #9ff3cd;
}

.conn-status.disconnected {
  background: rgba(248, 113, 113, 0.18);
  color: #fecaca;
}

.page-shell {
  padding: 12px;
}

.view {
  display: none;
}

.view.active {
  display: block;
}

.card {
  background: #fff;
  border-radius: 16px;
  padding: 14px;
  margin-bottom: 12px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
}

.card h2 {
  margin: 0 0 12px;
  font-size: 16px;
}

.session-list,
.event-list,
.chat-history,
.memory-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.session-item,
.event-item,
.message-item,
.memory-item {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 12px;
  background: #fbfdff;
}

.session-row,
.event-row,
.memory-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
  margin-right: 6px;
}

.status-dot.active {
  background: #10b981;
}

.status-dot.stopped {
  background: #9ca3af;
}

label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  color: #4b5563;
}

select,
textarea,
button {
  width: 100%;
  font: inherit;
}

select,
textarea {
  border: 1px solid #d1d5db;
  border-radius: 12px;
  padding: 10px 12px;
  background: #fff;
}

textarea {
  resize: vertical;
}

button {
  border: 0;
  border-radius: 12px;
  padding: 12px;
  font-weight: 600;
  background: #2563eb;
  color: #fff;
}

button.secondary {
  background: #e5e7eb;
  color: #111827;
}

button.danger {
  background: #ef4444;
}

.chat-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hint {
  margin: 4px 2px 0;
  font-size: 12px;
  color: #6b7280;
}

.memory-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.pill {
  flex: 1;
  background: #e5e7eb;
  color: #111827;
}

.pill.active {
  background: #1d4ed8;
  color: #fff;
}

.memory-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.tab-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
  background: rgba(255, 255, 255, 0.96);
  border-top: 1px solid #e5e7eb;
  backdrop-filter: blur(10px);
}

.tab-btn {
  background: #e5e7eb;
  color: #111827;
}

.tab-btn.active {
  background: #111827;
  color: #fff;
}

.empty {
  color: #6b7280;
  text-align: center;
  padding: 16px 12px;
}

.toast {
  position: fixed;
  left: 50%;
  bottom: 88px;
  transform: translateX(-50%);
  min-width: 180px;
  max-width: calc(100vw - 24px);
  padding: 10px 14px;
  border-radius: 999px;
  background: rgba(17, 24, 39, 0.92);
  color: #fff;
  font-size: 13px;
  text-align: center;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s ease;
}

.toast.visible {
  opacity: 1;
}
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_mobile.py -v -k "shell or layout"`
Expected: 3 tests passed

- [ ] **Step 6: 提交**

```bash
git add mobile/index.html mobile/style.css tests/test_mobile.py
git commit -m "feat: 实现 mobile 页面骨架与样式"
```

---

### Task 3: 实现状态页与 WebSocket 实时更新

**Files:**
- Modify: `mobile/app.js`
- Modify: `tests/test_mobile.py`

- [ ] **Step 1: 在 `tests/test_mobile.py` 末尾追加失败测试**

```python

def test_mobile_status_script_contains_ws_and_status_endpoints(client):
    js = client.get("/mobile/app.js").text
    assert "connectWebSocket" in js
    assert "loadStatusData" in js
    assert "renderStatus" in js
    assert "`/agents`" in js or "/agents" in js
    assert "`/events`" in js or "/events" in js
    assert "`/ws`" in js or "/ws" in js
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_mobile.py -v -k "status_script"`
Expected: 因 `app.js` 仍只有 `console.log` 而失败

- [ ] **Step 3: 完整实现 `mobile/app.js` 的状态页逻辑**

```javascript
const SERVER = location.origin;
const WS_PROTOCOL = location.protocol === "https:" ? "wss:" : "ws:";
const WS_URL = `${WS_PROTOCOL}//${location.host}/ws`;

const state = {
  activeTab: "status",
  reconnectDelay: 1000,
  sessions: [],
  events: [],
  selectedSessionId: "",
  chatMessages: [],
  memories: [],
  memoryFilter: "pending",
};

const dom = {
  connStatus: document.getElementById("conn-status"),
  tabButtons: document.querySelectorAll(".tab-btn"),
  views: {
    status: document.getElementById("view-status"),
    chat: document.getElementById("view-chat"),
    memory: document.getElementById("view-memory"),
  },
  sessionList: document.getElementById("session-list"),
  eventList: document.getElementById("event-list"),
  chatSessionSelect: document.getElementById("chat-session-select"),
  chatHistory: document.getElementById("chat-history"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  memoryList: document.getElementById("memory-list"),
  memoryFilterPending: document.getElementById("memory-filter-pending"),
  memoryFilterActive: document.getElementById("memory-filter-active"),
  toast: document.getElementById("toast"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatTime(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false });
}

function showToast(text) {
  dom.toast.textContent = text;
  dom.toast.classList.add("visible");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => dom.toast.classList.remove("visible"), 1800);
}

function setConnectionStatus(connected) {
  dom.connStatus.textContent = connected ? "已连接" : "未连接";
  dom.connStatus.className = `conn-status ${connected ? "connected" : "disconnected"}`;
}

async function fetchJson(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    throw new Error(`${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}

function switchTab(tab) {
  state.activeTab = tab;
  dom.tabButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  Object.entries(dom.views).forEach(([name, node]) => {
    node.classList.toggle("active", name === tab);
  });
}

function renderSessionOptions() {
  const options = state.sessions
    .map((session) => `<option value="${escapeHtml(session.id)}">${escapeHtml(session.id)}</option>`)
    .join("");
  dom.chatSessionSelect.innerHTML = options;
  if (!state.selectedSessionId && state.sessions.length > 0) {
    state.selectedSessionId = state.sessions[0].id;
  }
  if (state.selectedSessionId) {
    dom.chatSessionSelect.value = state.selectedSessionId;
  }
}

function renderStatus() {
  if (state.sessions.length === 0) {
    dom.sessionList.innerHTML = '<div class="empty">暂无 Agent 会话</div>';
  } else {
    const rows = [...state.sessions]
      .sort((a, b) => (b.started_at || 0) - (a.started_at || 0))
      .map((session) => `
        <div class="session-item">
          <div class="session-row">
            <strong><span class="status-dot ${escapeHtml(session.status)}"></span>${escapeHtml(session.id)}</strong>
            <span>${escapeHtml(session.status)}</span>
          </div>
          <div class="hint">cwd: ${escapeHtml(session.cwd || "—")}</div>
          <div class="hint">开始时间: ${escapeHtml(formatTime(session.started_at))}</div>
        </div>
      `)
      .join("");
    dom.sessionList.innerHTML = rows;
  }

  if (state.events.length === 0) {
    dom.eventList.innerHTML = '<div class="empty">暂无工具事件</div>';
  } else {
    dom.eventList.innerHTML = state.events
      .slice(0, 50)
      .map((event) => `
        <div class="event-item">
          <div class="event-row">
            <strong>${escapeHtml(event.tool_name || event.type)}</strong>
            <span>${escapeHtml(formatTime(event.created_at))}</span>
          </div>
          <div class="hint">session: ${escapeHtml(event.session_id)}</div>
          <div class="hint">type: ${escapeHtml(event.type)}</div>
        </div>
      `)
      .join("");
  }
}

function renderChatHistory() {
  dom.chatHistory.innerHTML = '<div class="empty">请在后续任务中实现聊天渲染</div>';
}

function renderMemories() {
  dom.memoryList.innerHTML = '<div class="empty">请在后续任务中实现记忆渲染</div>';
}

async function loadStatusData() {
  const [sessions, events] = await Promise.all([
    fetchJson(`${SERVER}/agents`),
    fetchJson(`${SERVER}/events`),
  ]);
  state.sessions = sessions;
  state.events = events;
  renderSessionOptions();
  renderStatus();
}

function upsertSession(session) {
  const idx = state.sessions.findIndex((item) => item.id === session.id);
  if (idx >= 0) state.sessions[idx] = { ...state.sessions[idx], ...session };
  else state.sessions.unshift(session);
  renderSessionOptions();
  renderStatus();
}

function connectWebSocket() {
  const ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    setConnectionStatus(true);
    state.reconnectDelay = 1000;
  };

  ws.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "event") {
      state.events.unshift(payload.data);
      state.events = state.events.slice(0, 100);
      renderStatus();
    }
    if (payload.type === "agent_update") {
      upsertSession(payload.data);
    }
  };

  ws.onclose = () => {
    setConnectionStatus(false);
    setTimeout(connectWebSocket, Math.min(state.reconnectDelay, 30000));
    state.reconnectDelay *= 2;
  };

  ws.onerror = () => ws.close();
}

dom.tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

dom.chatSessionSelect.addEventListener("change", (event) => {
  state.selectedSessionId = event.target.value;
  renderChatHistory();
});

dom.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  showToast("聊天能力将在后续任务中接入");
});

dom.memoryFilterPending.addEventListener("click", () => {
  dom.memoryFilterPending.classList.add("active");
  dom.memoryFilterActive.classList.remove("active");
  renderMemories();
});

dom.memoryFilterActive.addEventListener("click", () => {
  dom.memoryFilterActive.classList.add("active");
  dom.memoryFilterPending.classList.remove("active");
  renderMemories();
});

(async function init() {
  setConnectionStatus(false);
  await loadStatusData();
  connectWebSocket();
})();
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_mobile.py -v -k "status_script"`
Expected: 1 test passed

- [ ] **Step 5: 提交**

```bash
git add mobile/app.js tests/test_mobile.py
git commit -m "feat: 实现 mobile 状态页与 WebSocket 更新"
```

---

### Task 4: 接入聊天页（发送消息 + 历史记录）

**Files:**
- Modify: `mobile/app.js`
- Modify: `tests/test_mobile.py`

- [ ] **Step 1: 在 `tests/test_mobile.py` 末尾追加失败测试**

```python

def test_mobile_chat_script_contains_chat_endpoints(client):
    js = client.get("/mobile/app.js").text
    assert "sendChatMessage" in js
    assert "loadChatHistory" in js
    assert "/chat/" in js
    assert "POST" in js
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_mobile.py -v -k "chat_script"`
Expected: 因 `sendChatMessage` / `loadChatHistory` 不存在失败

- [ ] **Step 3: 用完整版本替换 `mobile/app.js`，接入聊天页**

```javascript
const SERVER = location.origin;
const WS_PROTOCOL = location.protocol === "https:" ? "wss:" : "ws:";
const WS_URL = `${WS_PROTOCOL}//${location.host}/ws`;

const state = {
  activeTab: "status",
  reconnectDelay: 1000,
  sessions: [],
  events: [],
  selectedSessionId: "",
  chatMessages: [],
  memories: [],
  memoryFilter: "pending",
};

const dom = {
  connStatus: document.getElementById("conn-status"),
  tabButtons: document.querySelectorAll(".tab-btn"),
  views: {
    status: document.getElementById("view-status"),
    chat: document.getElementById("view-chat"),
    memory: document.getElementById("view-memory"),
  },
  sessionList: document.getElementById("session-list"),
  eventList: document.getElementById("event-list"),
  chatSessionSelect: document.getElementById("chat-session-select"),
  chatHistory: document.getElementById("chat-history"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  memoryList: document.getElementById("memory-list"),
  memoryFilterPending: document.getElementById("memory-filter-pending"),
  memoryFilterActive: document.getElementById("memory-filter-active"),
  toast: document.getElementById("toast"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatTime(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false });
}

function showToast(text) {
  dom.toast.textContent = text;
  dom.toast.classList.add("visible");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => dom.toast.classList.remove("visible"), 1800);
}

function setConnectionStatus(connected) {
  dom.connStatus.textContent = connected ? "已连接" : "未连接";
  dom.connStatus.className = `conn-status ${connected ? "connected" : "disconnected"}`;
}

async function fetchJson(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    throw new Error(`${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}

function switchTab(tab) {
  state.activeTab = tab;
  dom.tabButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  Object.entries(dom.views).forEach(([name, node]) => {
    node.classList.toggle("active", name === tab);
  });
  if (tab === "chat") {
    loadChatHistory();
  }
}

function renderSessionOptions() {
  const options = state.sessions
    .map((session) => `<option value="${escapeHtml(session.id)}">${escapeHtml(session.id)}</option>`)
    .join("");
  dom.chatSessionSelect.innerHTML = options;
  if (!state.selectedSessionId && state.sessions.length > 0) {
    state.selectedSessionId = state.sessions[0].id;
  }
  if (state.selectedSessionId) {
    dom.chatSessionSelect.value = state.selectedSessionId;
  }
}

function renderStatus() {
  if (state.sessions.length === 0) {
    dom.sessionList.innerHTML = '<div class="empty">暂无 Agent 会话</div>';
  } else {
    const rows = [...state.sessions]
      .sort((a, b) => (b.started_at || 0) - (a.started_at || 0))
      .map((session) => `
        <div class="session-item">
          <div class="session-row">
            <strong><span class="status-dot ${escapeHtml(session.status)}"></span>${escapeHtml(session.id)}</strong>
            <span>${escapeHtml(session.status)}</span>
          </div>
          <div class="hint">cwd: ${escapeHtml(session.cwd || "—")}</div>
          <div class="hint">开始时间: ${escapeHtml(formatTime(session.started_at))}</div>
        </div>
      `)
      .join("");
    dom.sessionList.innerHTML = rows;
  }

  if (state.events.length === 0) {
    dom.eventList.innerHTML = '<div class="empty">暂无工具事件</div>';
  } else {
    dom.eventList.innerHTML = state.events
      .slice(0, 50)
      .map((event) => `
        <div class="event-item">
          <div class="event-row">
            <strong>${escapeHtml(event.tool_name || event.type)}</strong>
            <span>${escapeHtml(formatTime(event.created_at))}</span>
          </div>
          <div class="hint">session: ${escapeHtml(event.session_id)}</div>
          <div class="hint">type: ${escapeHtml(event.type)}</div>
        </div>
      `)
      .join("");
  }
}

function renderChatHistory() {
  if (!state.selectedSessionId) {
    dom.chatHistory.innerHTML = '<div class="empty">暂无可聊天的 Session</div>';
    return;
  }
  if (state.chatMessages.length === 0) {
    dom.chatHistory.innerHTML = '<div class="empty">暂无聊天消息</div>';
    return;
  }
  dom.chatHistory.innerHTML = state.chatMessages
    .map((message) => `
      <div class="message-item">
        <div class="event-row">
          <strong>${escapeHtml(message.status)}</strong>
          <span>${escapeHtml(formatTime(message.created_at))}</span>
        </div>
        <div>${escapeHtml(message.content)}</div>
      </div>
    `)
    .join("");
}

function renderMemories() {
  dom.memoryList.innerHTML = '<div class="empty">请在后续任务中实现记忆渲染</div>';
}

async function loadStatusData() {
  const [sessions, events] = await Promise.all([
    fetchJson(`${SERVER}/agents`),
    fetchJson(`${SERVER}/events`),
  ]);
  state.sessions = sessions;
  state.events = events;
  renderSessionOptions();
  renderStatus();
}

async function loadChatHistory() {
  if (!state.selectedSessionId) {
    state.chatMessages = [];
    renderChatHistory();
    return;
  }
  state.chatMessages = await fetchJson(`${SERVER}/chat/${state.selectedSessionId}/history`);
  renderChatHistory();
}

async function sendChatMessage() {
  if (!state.selectedSessionId) {
    showToast("请先选择 Session");
    return;
  }
  const content = dom.chatInput.value.trim();
  if (!content) {
    showToast("消息不能为空");
    return;
  }
  await fetchJson(`${SERVER}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: state.selectedSessionId,
      content,
    }),
  });
  dom.chatInput.value = "";
  showToast("消息已发送，等待 Agent 下一次工具调用时接收");
  await loadChatHistory();
}

function upsertSession(session) {
  const idx = state.sessions.findIndex((item) => item.id === session.id);
  if (idx >= 0) state.sessions[idx] = { ...state.sessions[idx], ...session };
  else state.sessions.unshift(session);
  renderSessionOptions();
  renderStatus();
}

function connectWebSocket() {
  const ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    setConnectionStatus(true);
    state.reconnectDelay = 1000;
  };

  ws.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "event") {
      state.events.unshift(payload.data);
      state.events = state.events.slice(0, 100);
      renderStatus();
      if (payload.data.session_id === state.selectedSessionId) {
        loadChatHistory();
      }
    }
    if (payload.type === "agent_update") {
      upsertSession(payload.data);
    }
  };

  ws.onclose = () => {
    setConnectionStatus(false);
    setTimeout(connectWebSocket, Math.min(state.reconnectDelay, 30000));
    state.reconnectDelay *= 2;
  };

  ws.onerror = () => ws.close();
}

dom.tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

dom.chatSessionSelect.addEventListener("change", async (event) => {
  state.selectedSessionId = event.target.value;
  await loadChatHistory();
});

dom.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await sendChatMessage();
});

dom.memoryFilterPending.addEventListener("click", () => {
  dom.memoryFilterPending.classList.add("active");
  dom.memoryFilterActive.classList.remove("active");
  renderMemories();
});

dom.memoryFilterActive.addEventListener("click", () => {
  dom.memoryFilterActive.classList.add("active");
  dom.memoryFilterPending.classList.remove("active");
  renderMemories();
});

(async function init() {
  setConnectionStatus(false);
  await loadStatusData();
  await loadChatHistory();
  connectWebSocket();
})();
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_mobile.py -v -k "chat_script"`
Expected: 1 test passed

- [ ] **Step 5: 提交**

```bash
git add mobile/app.js tests/test_mobile.py
git commit -m "feat: 接入 mobile 聊天页"
```

---

### Task 5: 接入记忆审核页并补充 README/手工验证

**Files:**
- Modify: `mobile/app.js`
- Modify: `tests/test_mobile.py`
- Modify: `README.md:1-63`

- [ ] **Step 1: 在 `tests/test_mobile.py` 末尾追加失败测试**

```python

def test_mobile_memory_script_contains_review_actions(client):
    js = client.get("/mobile/app.js").text
    assert "loadMemories" in js
    assert "reviewMemory" in js
    assert "/memory?status=" in js
    assert 'method: "PATCH"' in js


def test_readme_mentions_mobile_entry():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "手机 Web App" in readme
    assert "/mobile/index.html" in readme
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_mobile.py -v -k "memory_script or readme_mentions_mobile_entry"`
Expected: 因 `loadMemories` / `reviewMemory` / README 缺少手机入口说明而失败

- [ ] **Step 3: 用最终版本替换 `mobile/app.js`，接入记忆审核页**

```javascript
const SERVER = location.origin;
const WS_PROTOCOL = location.protocol === "https:" ? "wss:" : "ws:";
const WS_URL = `${WS_PROTOCOL}//${location.host}/ws`;

const state = {
  activeTab: "status",
  reconnectDelay: 1000,
  sessions: [],
  events: [],
  selectedSessionId: "",
  chatMessages: [],
  memories: [],
  memoryFilter: "pending",
};

const dom = {
  connStatus: document.getElementById("conn-status"),
  tabButtons: document.querySelectorAll(".tab-btn"),
  views: {
    status: document.getElementById("view-status"),
    chat: document.getElementById("view-chat"),
    memory: document.getElementById("view-memory"),
  },
  sessionList: document.getElementById("session-list"),
  eventList: document.getElementById("event-list"),
  chatSessionSelect: document.getElementById("chat-session-select"),
  chatHistory: document.getElementById("chat-history"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  memoryList: document.getElementById("memory-list"),
  memoryFilterPending: document.getElementById("memory-filter-pending"),
  memoryFilterActive: document.getElementById("memory-filter-active"),
  toast: document.getElementById("toast"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatTime(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false });
}

function showToast(text) {
  dom.toast.textContent = text;
  dom.toast.classList.add("visible");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => dom.toast.classList.remove("visible"), 1800);
}

function setConnectionStatus(connected) {
  dom.connStatus.textContent = connected ? "已连接" : "未连接";
  dom.connStatus.className = `conn-status ${connected ? "connected" : "disconnected"}`;
}

async function fetchJson(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    throw new Error(`${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}

function switchTab(tab) {
  state.activeTab = tab;
  dom.tabButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  Object.entries(dom.views).forEach(([name, node]) => {
    node.classList.toggle("active", name === tab);
  });
  if (tab === "chat") {
    loadChatHistory();
  }
  if (tab === "memory") {
    loadMemories();
  }
}

function renderSessionOptions() {
  const options = state.sessions
    .map((session) => `<option value="${escapeHtml(session.id)}">${escapeHtml(session.id)}</option>`)
    .join("");
  dom.chatSessionSelect.innerHTML = options;
  if (!state.selectedSessionId && state.sessions.length > 0) {
    state.selectedSessionId = state.sessions[0].id;
  }
  if (state.selectedSessionId) {
    dom.chatSessionSelect.value = state.selectedSessionId;
  }
}

function renderStatus() {
  if (state.sessions.length === 0) {
    dom.sessionList.innerHTML = '<div class="empty">暂无 Agent 会话</div>';
  } else {
    const rows = [...state.sessions]
      .sort((a, b) => (b.started_at || 0) - (a.started_at || 0))
      .map((session) => `
        <div class="session-item">
          <div class="session-row">
            <strong><span class="status-dot ${escapeHtml(session.status)}"></span>${escapeHtml(session.id)}</strong>
            <span>${escapeHtml(session.status)}</span>
          </div>
          <div class="hint">cwd: ${escapeHtml(session.cwd || "—")}</div>
          <div class="hint">开始时间: ${escapeHtml(formatTime(session.started_at))}</div>
        </div>
      `)
      .join("");
    dom.sessionList.innerHTML = rows;
  }

  if (state.events.length === 0) {
    dom.eventList.innerHTML = '<div class="empty">暂无工具事件</div>';
  } else {
    dom.eventList.innerHTML = state.events
      .slice(0, 50)
      .map((event) => `
        <div class="event-item">
          <div class="event-row">
            <strong>${escapeHtml(event.tool_name || event.type)}</strong>
            <span>${escapeHtml(formatTime(event.created_at))}</span>
          </div>
          <div class="hint">session: ${escapeHtml(event.session_id)}</div>
          <div class="hint">type: ${escapeHtml(event.type)}</div>
        </div>
      `)
      .join("");
  }
}

function renderChatHistory() {
  if (!state.selectedSessionId) {
    dom.chatHistory.innerHTML = '<div class="empty">暂无可聊天的 Session</div>';
    return;
  }
  if (state.chatMessages.length === 0) {
    dom.chatHistory.innerHTML = '<div class="empty">暂无聊天消息</div>';
    return;
  }
  dom.chatHistory.innerHTML = state.chatMessages
    .map((message) => `
      <div class="message-item">
        <div class="event-row">
          <strong>${escapeHtml(message.status)}</strong>
          <span>${escapeHtml(formatTime(message.created_at))}</span>
        </div>
        <div>${escapeHtml(message.content)}</div>
      </div>
    `)
    .join("");
}

function renderMemories() {
  if (state.memories.length === 0) {
    dom.memoryList.innerHTML = '<div class="empty">暂无记忆条目</div>';
    return;
  }
  dom.memoryList.innerHTML = state.memories
    .map((memory) => {
      const actions = state.memoryFilter === "pending"
        ? `
          <div class="memory-actions">
            <button type="button" data-action="activate" data-id="${escapeHtml(memory.id)}">启用</button>
            <button type="button" class="danger" data-action="reject" data-id="${escapeHtml(memory.id)}">拒绝</button>
          </div>
        `
        : "";
      return `
        <div class="memory-item">
          <div class="memory-row">
            <strong>${escapeHtml(memory.title)}</strong>
            <span>${escapeHtml(memory.status)}</span>
          </div>
          <div class="hint">tags: ${escapeHtml(memory.tags || "—")}</div>
          <div>${escapeHtml(memory.content)}</div>
          ${actions}
        </div>
      `;
    })
    .join("");

  dom.memoryList.querySelectorAll("button[data-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.dataset.id;
      const status = button.dataset.action === "activate" ? "active" : "rejected";
      await reviewMemory(id, status);
    });
  });
}

async function loadStatusData() {
  const [sessions, events] = await Promise.all([
    fetchJson(`${SERVER}/agents`),
    fetchJson(`${SERVER}/events`),
  ]);
  state.sessions = sessions;
  state.events = events;
  renderSessionOptions();
  renderStatus();
}

async function loadChatHistory() {
  if (!state.selectedSessionId) {
    state.chatMessages = [];
    renderChatHistory();
    return;
  }
  state.chatMessages = await fetchJson(`${SERVER}/chat/${state.selectedSessionId}/history`);
  renderChatHistory();
}

async function sendChatMessage() {
  if (!state.selectedSessionId) {
    showToast("请先选择 Session");
    return;
  }
  const content = dom.chatInput.value.trim();
  if (!content) {
    showToast("消息不能为空");
    return;
  }
  await fetchJson(`${SERVER}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: state.selectedSessionId,
      content,
    }),
  });
  dom.chatInput.value = "";
  showToast("消息已发送，等待 Agent 下一次工具调用时接收");
  await loadChatHistory();
}

async function loadMemories() {
  state.memories = await fetchJson(`${SERVER}/memory?status=${state.memoryFilter}`);
  renderMemories();
}

async function reviewMemory(memoryId, status) {
  await fetchJson(`${SERVER}/memory/${memoryId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  showToast(status === "active" ? "记忆已启用" : "记忆已拒绝");
  await loadMemories();
}

function upsertSession(session) {
  const idx = state.sessions.findIndex((item) => item.id === session.id);
  if (idx >= 0) state.sessions[idx] = { ...state.sessions[idx], ...session };
  else state.sessions.unshift(session);
  renderSessionOptions();
  renderStatus();
}

function connectWebSocket() {
  const ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    setConnectionStatus(true);
    state.reconnectDelay = 1000;
  };

  ws.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "event") {
      state.events.unshift(payload.data);
      state.events = state.events.slice(0, 100);
      renderStatus();
      if (payload.data.session_id === state.selectedSessionId) {
        loadChatHistory();
      }
    }
    if (payload.type === "agent_update") {
      upsertSession(payload.data);
    }
  };

  ws.onclose = () => {
    setConnectionStatus(false);
    setTimeout(connectWebSocket, Math.min(state.reconnectDelay, 30000));
    state.reconnectDelay *= 2;
  };

  ws.onerror = () => ws.close();
}

dom.tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

dom.chatSessionSelect.addEventListener("change", async (event) => {
  state.selectedSessionId = event.target.value;
  await loadChatHistory();
});

dom.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await sendChatMessage();
});

dom.memoryFilterPending.addEventListener("click", async () => {
  state.memoryFilter = "pending";
  dom.memoryFilterPending.classList.add("active");
  dom.memoryFilterActive.classList.remove("active");
  await loadMemories();
});

dom.memoryFilterActive.addEventListener("click", async () => {
  state.memoryFilter = "active";
  dom.memoryFilterActive.classList.add("active");
  dom.memoryFilterPending.classList.remove("active");
  await loadMemories();
});

(async function init() {
  setConnectionStatus(false);
  await loadStatusData();
  await loadChatHistory();
  await loadMemories();
  connectWebSocket();
})();
```

- [ ] **Step 4: 更新 `README.md`，加入手机入口说明**

将 `README.md` 改为：

```markdown
# CodeTogether

Claude Code Agent 团队协作平台。

## Hooks 安装

将以下内容添加到 `~/.claude/settings.json` 的 `hooks` 字段，或在项目目录创建 `.claude/settings.json`：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python /path/to/CodeTogether/hooks/pre_tool.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python /path/to/CodeTogether/hooks/post_tool.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python /path/to/CodeTogether/hooks/stop.py"
          }
        ]
      }
    ]
  }
}
```

将 `/path/to/CodeTogether` 替换为实际路径（如 `/Users/qinepan/Desktop/search/CodeTogether`）。

## 手机 Web App

启动服务后，在手机浏览器访问：

- `http://<你的电脑 IP>:7878/mobile/index.html`
- 本机调试：`http://127.0.0.1:7878/mobile/index.html`

页面能力：
- **状态**：查看 Agent 状态与最近工具事件
- **聊天**：给指定 Session 发送消息，并查看历史消息
- **记忆**：审核 pending 记忆并启用 / 拒绝

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CODETOGETHER_SERVER` | `http://localhost:8000` | CodeTogether 服务器地址 |

## 服务器启动

```bash
pip install -r requirements.txt
uvicorn server.main:app --reload --port 7878
```

- [ ] **Step 5: 运行自动化测试，确认通过**

Run: `python3 -m pytest tests/test_mobile.py -v`
Expected: 所有 mobile tests 通过

- [ ] **Step 6: 运行原有后端测试，确认无回归**

Run: `python3 -m pytest tests/ -v --ignore=tests/test_mobile.py`
Expected: 原有服务器与 hooks 测试全部通过

- [ ] **Step 7: 启动服务并进行手工验证**

Run: `uvicorn server.main:app --reload --port 7878`

另开终端准备演示数据：

```bash
curl -X POST http://127.0.0.1:7878/agents \
  -H 'Content-Type: application/json' \
  -d '{"id":"mobile-demo","cwd":"/Users/qinepan/Desktop/search/CodeTogether"}'

curl -X POST http://127.0.0.1:7878/events \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"mobile-demo","type":"pre_tool","tool_name":"Read","input":{"file_path":"README.md"}}'

curl -X POST http://127.0.0.1:7878/memory \
  -H 'Content-Type: application/json' \
  -d '{"project_id":null,"title":"消息送达延迟说明","content":"手机消息会在 Agent 下一次工具调用时送达","tags":"chat,hooks"}'
```

在浏览器打开 `http://127.0.0.1:7878/mobile/index.html`，验证：
- 状态页能看到 `mobile-demo` 与 `Read` 事件
- 聊天页能选择 `mobile-demo`，发送一条消息后看到 `pending/delivered` 历史记录
- 记忆页默认展示 pending 记忆，点击“启用”后切换到“已启用”能看到该条目
- 顶部连接状态从“未连接”变为“已连接”

- [ ] **Step 8: 提交**

```bash
git add mobile/app.js tests/test_mobile.py README.md
git commit -m "feat: 完成 mobile 记忆审核页与使用说明"
```
