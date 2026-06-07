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
  if (tab === "chat") {
    loadChatHistory().catch((error) => {
      console.error("加载聊天历史失败", error);
      showToast("聊天历史加载失败，请稍后重试");
    });
  }
  if (tab === "memory") {
    loadMemories().catch((error) => {
      console.error("加载记忆列表失败", error);
      showToast("记忆列表加载失败，请稍后重试");
    });
  }
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
 * 根据当前选中会话与聊天消息状态渲染聊天历史列表。
 *
 * 参数:
 *   无。
 *
 * 返回值:
 *   无返回值。
 */
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

/**
 * 根据当前筛选状态渲染记忆列表，并为待审核条目绑定审核动作。
 *
 * 参数:
 *   无。
 *
 * 返回值:
 *   无返回值。
 */
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
    button.addEventListener("click", () => {
      const status = button.dataset.action === "activate" ? "active" : "rejected";
      reviewMemory(button.dataset.id, status).catch((error) => {
        console.error("审核记忆失败", error);
        showToast("记忆审核失败，请稍后重试");
      });
    });
  });
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
 * 拉取当前选中会话的聊天历史；若尚未选择会话则渲染空状态。
 *
 * 参数:
 *   无。
 *
 * 返回值:
 *   一个在聊天历史加载并完成渲染后兑现的 Promise。
 */
async function loadChatHistory() {
  if (!state.selectedSessionId) {
    state.chatMessages = [];
    renderChatHistory();
    return;
  }
  state.chatMessages = await fetchJson(`${SERVER}/chat/${state.selectedSessionId}/history`);
  renderChatHistory();
}

/**
 * 向当前选中会话发送一条聊天消息，并在成功后刷新历史记录。
 *
 * 参数:
 *   无。
 *
 * 返回值:
 *   一个在消息发送完成后兑现的 Promise。
 */
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

/**
 * 按当前筛选状态拉取记忆列表，并在成功后刷新页面展示。
 *
 * 参数:
 *   无。
 *
 * 返回值:
 *   一个在记忆列表加载并渲染完成后兑现的 Promise。
 */
async function loadMemories() {
  state.memories = await fetchJson(`${SERVER}/memory?status=${state.memoryFilter}`);
  renderMemories();
}

/**
 * 审核指定记忆条目，并在状态更新后重新加载当前筛选列表。
 *
 * 参数:
 *   memoryId: 目标记忆 ID。
 *   status: 审核后的目标状态，只允许 active 或 rejected。
 *
 * 返回值:
 *   一个在审核完成并刷新列表后兑现的 Promise。
 */
async function reviewMemory(memoryId, status) {
  await fetchJson(`${SERVER}/memory/${memoryId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  showToast(status === "active" ? "记忆已启用" : "记忆已拒绝");
  await loadMemories();
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
  renderChatHistory();
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
      if (payload.data.session_id === state.selectedSessionId) {
        loadChatHistory().catch((error) => {
          console.error("收到事件后刷新聊天历史失败", error);
        });
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
  await loadChatHistory();
  await loadMemories();
  connectWebSocket();
}

dom.tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

dom.chatSessionSelect.addEventListener("change", (event) => {
  state.selectedSessionId = event.target.value;
  loadChatHistory().catch((error) => {
    console.error("切换 Session 后加载聊天历史失败", error);
    showToast("聊天历史加载失败，请稍后重试");
  });
});

dom.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendChatMessage().catch((error) => {
    console.error("发送聊天消息失败", error);
    showToast("消息发送失败，请稍后重试");
  });
});

dom.memoryFilterPending.addEventListener("click", () => {
  state.memoryFilter = "pending";
  dom.memoryFilterPending.classList.add("active");
  dom.memoryFilterActive.classList.remove("active");
  loadMemories().catch((error) => {
    console.error("切换待审核记忆失败", error);
    showToast("记忆列表加载失败，请稍后重试");
  });
});

dom.memoryFilterActive.addEventListener("click", () => {
  state.memoryFilter = "active";
  dom.memoryFilterActive.classList.add("active");
  dom.memoryFilterPending.classList.remove("active");
  loadMemories().catch((error) => {
    console.error("切换已启用记忆失败", error);
    showToast("记忆列表加载失败，请稍后重试");
  });
});

init().catch((error) => {
  console.error("初始化 mobile 状态页失败", error);
  setConnectionStatus(false);
  showToast("状态页初始化失败，请稍后重试");
});
