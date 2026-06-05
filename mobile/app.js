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

/**
 * 转义 HTML 特殊字符，避免将接口返回内容直接插入页面时触发注入问题。
 *
 * 参数:
 *   value: 任意待展示的值，允许为空或非字符串类型。
 *
 * 返回值:
 *   转义后的安全字符串。
 */
function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * 将秒级时间戳格式化为中文本地时间，缺失时返回占位符。
 *
 * 参数:
 *   ts: 秒级 Unix 时间戳，可为空。
 *
 * 返回值:
 *   可直接展示在页面中的时间字符串。
 */
function formatTime(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false });
}

/**
 * 显示底部提示气泡，并在短暂延迟后自动隐藏。
 *
 * 参数:
 *   text: 需要展示给用户的提示文本。
 *
 * 返回值:
 *   无返回值。
 */
function showToast(text) {
  dom.toast.textContent = text;
  dom.toast.classList.add("visible");
  clearTimeout(showToast.timerId);
  showToast.timerId = setTimeout(() => dom.toast.classList.remove("visible"), 1800);
}

/**
 * 更新页面顶部的连接状态样式与文案。
 *
 * 参数:
 *   connected: 当前 WebSocket 是否处于已连接状态。
 *
 * 返回值:
 *   无返回值。
 */
function setConnectionStatus(connected) {
  dom.connStatus.textContent = connected ? "已连接" : "未连接";
  dom.connStatus.className = `conn-status ${connected ? "connected" : "disconnected"}`;
}

/**
 * 请求 JSON 接口并在响应异常时抛出错误，便于初始化流程统一处理失败。
 *
 * 参数:
 *   url: 目标接口地址。
 *   options: fetch 的可选配置。
 *
 * 返回值:
 *   解析后的 JSON 数据。
 */
async function fetchJson(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    throw new Error(`${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}

/**
 * 切换当前激活标签页，并同步更新标签按钮与视图容器状态。
 *
 * 参数:
 *   tab: 目标标签名，取值为 status、chat 或 memory。
 *
 * 返回值:
 *   无返回值。
 */
function switchTab(tab) {
  state.activeTab = tab;
  dom.tabButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  Object.entries(dom.views).forEach(([name, node]) => {
    node.classList.toggle("active", name === tab);
  });
}

/**
 * 根据当前会话列表重绘聊天页会话下拉框，并尽量保留用户当前选择。
 *
 * 参数:
 *   无。
 *
 * 返回值:
 *   无返回值。
 */
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

/**
 * 渲染状态页中的会话列表与工具事件列表，仅覆盖 Task 3 约定的状态展示能力。
 *
 * 参数:
 *   无。
 *
 * 返回值:
 *   无返回值。
 */
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

/**
 * 渲染聊天历史占位内容，明确聊天能力将在后续任务中接入。
 *
 * 参数:
 *   无。
 *
 * 返回值:
 *   无返回值。
 */
function renderChatHistory() {
  dom.chatHistory.innerHTML = '<div class="empty">请在后续任务中实现聊天渲染</div>';
}

/**
 * 渲染记忆页占位内容，确保当前任务不提前引入记忆接口行为。
 *
 * 参数:
 *   无。
 *
 * 返回值:
 *   无返回值。
 */
function renderMemories() {
  dom.memoryList.innerHTML = '<div class="empty">请在后续任务中实现记忆渲染</div>';
}

/**
 * 拉取状态页初始化所需的会话与事件数据，并在成功后刷新相关视图。
 *
 * 参数:
 *   无。
 *
 * 返回值:
 *   一个在数据加载完成后兑现的 Promise。
 */
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

/**
 * 将单个会话更新合并到本地状态中，并立即刷新状态页与聊天页会话下拉框。
 *
 * 参数:
 *   session: 来自实时事件或接口返回的会话对象。
 *
 * 返回值:
 *   无返回值。
 */
function upsertSession(session) {
  const idx = state.sessions.findIndex((item) => item.id === session.id);
  if (idx >= 0) {
    state.sessions[idx] = { ...state.sessions[idx], ...session };
  } else {
    state.sessions.unshift(session);
  }
  renderSessionOptions();
  renderStatus();
}

/**
 * 建立 WebSocket 连接并处理实时更新，在连接断开时采用指数退避重连。
 *
 * 参数:
 *   无。
 *
 * 返回值:
 *   无返回值。
 */
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

/**
 * 初始化移动端页面交互，加载状态数据并开启实时连接。
 *
 * 参数:
 *   无。
 *
 * 返回值:
 *   一个在初始化完成后兑现的 Promise。
 */
async function init() {
  setConnectionStatus(false);
  await loadStatusData();
  connectWebSocket();
  renderChatHistory();
  renderMemories();
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
  state.memoryFilter = "pending";
  dom.memoryFilterPending.classList.add("active");
  dom.memoryFilterActive.classList.remove("active");
  renderMemories();
});

dom.memoryFilterActive.addEventListener("click", () => {
  state.memoryFilter = "active";
  dom.memoryFilterActive.classList.add("active");
  dom.memoryFilterPending.classList.remove("active");
  renderMemories();
});

init().catch((error) => {
  console.error("初始化 mobile 状态页失败", error);
  setConnectionStatus(false);
  showToast("状态页初始化失败，请稍后重试");
});
