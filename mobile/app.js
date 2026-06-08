const SERVER = location.origin;
const WS_PROTOCOL = location.protocol === "https:" ? "wss:" : "ws:";
const WS_URL = `${WS_PROTOCOL}//${location.host}/ws`;

const state = {
  activeTab: "agents",
  reconnectDelay: 1000,
  sessions: [],
  events: [],
  selectedSessionId: "",
  chatMessages: [],
  memories: [],
  memoryFilter: "pending",
  inChat: false,
};

const dom = {
  connStatus: document.getElementById("conn-status"),
  topbarMain: document.getElementById("topbar-main"),
  backBtn: document.getElementById("back-btn"),
  tabButtons: document.querySelectorAll(".tab-btn"),
  views: {
    agents: document.getElementById("view-agents"),
    chat: document.getElementById("view-chat"),
    memory: document.getElementById("view-memory"),
  },
  projectGroups: document.getElementById("project-groups"),
  chatAgentInfo: document.getElementById("chat-agent-info"),
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
 * 将秒级时间戳格式化为本地时间，缺失时返回占位符。
 */
function formatTime(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false });
}

/**
 * 显示底部提示气泡，并在短暂延迟后自动隐藏。
 */
function showToast(text) {
  dom.toast.textContent = text;
  dom.toast.classList.add("visible");
  clearTimeout(showToast.timerId);
  showToast.timerId = setTimeout(() => dom.toast.classList.remove("visible"), 1800);
}

/**
 * 更新页面顶部的连接状态样式与文案。
 */
function setConnectionStatus(connected) {
  dom.connStatus.textContent = connected ? "已连接" : "未连接";
  dom.connStatus.className = `conn-status ${connected ? "connected" : "disconnected"}`;
}

/**
 * 请求 JSON 接口并在响应异常时抛出错误。
 */
async function fetchJson(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

/**
 * 从 cwd 提取项目名（最后一段路径），无 cwd 时归入"未知项目"。
 */
function projectLabel(session) {
  if (!session.cwd) return "未知项目";
  return session.cwd.replace(/\/$/, "").split("/").pop() || session.cwd;
}

/**
 * 渲染 Agent 列表页，按项目分组，每个 agent 是一张可点击的卡片。
 */
function renderAgents() {
  if (state.sessions.length === 0) {
    dom.projectGroups.innerHTML = '<div class="empty">暂无 Agent</div>';
    return;
  }

  // 按项目分组
  const groups = {};
  [...state.sessions]
    .sort((a, b) => (b.started_at || 0) - (a.started_at || 0))
    .forEach((s) => {
      const label = projectLabel(s);
      if (!groups[label]) groups[label] = [];
      groups[label].push(s);
    });

  dom.projectGroups.innerHTML = Object.entries(groups)
    .map(([project, sessions]) => `
      <div class="project-group">
        <div class="project-label">${escapeHtml(project)}</div>
        ${sessions.map((s) => `
          <button class="agent-card" type="button" data-session-id="${escapeHtml(s.id)}">
            <div class="agent-card-row">
              <span class="status-dot ${escapeHtml(s.status)}"></span>
              <span class="agent-id">${escapeHtml(s.id)}</span>
              <span class="agent-status-label ${escapeHtml(s.status)}">${escapeHtml(s.status)}</span>
              <span class="agent-delete-btn" role="button" data-delete-id="${escapeHtml(s.id)}" title="删除">✕</span>
            </div>
            <div class="hint">${escapeHtml(formatTime(s.started_at))}</div>
          </button>
        `).join("")}
      </div>
    `)
    .join("");

  dom.projectGroups.querySelectorAll(".agent-card").forEach((btn) => {
    btn.addEventListener("click", () => openChat(btn.dataset.sessionId));
  });
  dom.projectGroups.querySelectorAll(".agent-delete-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (!confirm(`确认删除 Agent ${btn.dataset.deleteId.slice(0, 8)}…？\n此操作将同时删除所有消息记录。`)) return;
      deleteAgent(btn.dataset.deleteId).catch((e) => {
        console.error("删除失败", e);
        showToast("删除失败");
      });
    });
  });
}

/**
 * 打开指定 session 的聊天视图，隐藏 tab 栏，显示返回按钮。
 */
function openChat(sessionId) {
  state.selectedSessionId = sessionId;
  state.inChat = true;

  const session = state.sessions.find((s) => s.id === sessionId);
  dom.chatAgentInfo.innerHTML = session
    ? `<span class="status-dot ${escapeHtml(session.status)}"></span><strong>${escapeHtml(projectLabel(session))}</strong><span class="hint" style="margin-left:8px">${escapeHtml(session.id)}</span>`
    : escapeHtml(sessionId);

  // 切换视图
  Object.values(dom.views).forEach((v) => v.classList.remove("active"));
  dom.views.chat.classList.add("active");
  dom.topbarMain.style.display = "none";
  dom.backBtn.style.display = "flex";
  document.querySelector(".tab-bar").style.display = "none";

  loadChatHistory().then(() => {
    dom.chatHistory.scrollTop = dom.chatHistory.scrollHeight;
  }).catch((e) => {
    console.error("加载聊天历史失败", e);
    showToast("聊天历史加载失败");
  });
}

/**
 * 从聊天视图返回 agent 列表。
 */
function closeChat() {
  state.inChat = false;
  Object.values(dom.views).forEach((v) => v.classList.remove("active"));
  dom.views.agents.classList.add("active");
  dom.topbarMain.style.display = "";
  dom.backBtn.style.display = "none";
  document.querySelector(".tab-bar").style.display = "";
}

/**
 * 切换底部标签页。
 */
function switchTab(tab) {
  if (state.inChat) closeChat();
  state.activeTab = tab;
  dom.tabButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  Object.entries(dom.views).forEach(([name, node]) => {
    node.classList.toggle("active", name === tab);
  });
  if (tab === "memory") {
    loadMemories().catch((e) => {
      console.error("加载记忆列表失败", e);
      showToast("记忆列表加载失败");
    });
  }
}

/**
 * 渲染聊天历史，滚动到底部。
 */
function renderChatHistory() {
  if (!state.selectedSessionId) {
    dom.chatHistory.innerHTML = '<div class="empty">请选择一个 Agent</div>';
    return;
  }
  if (!Array.isArray(state.chatMessages) || state.chatMessages.length === 0) {
    dom.chatHistory.innerHTML = '<div class="empty">暂无聊天消息</div>';
    return;
  }
  dom.chatHistory.innerHTML = [...state.chatMessages].reverse()
    .map((msg) => `
      <div class="bubble-row ${escapeHtml(msg.role)}">
        <div class="bubble ${escapeHtml(msg.role)}">
          <div class="bubble-content">${escapeHtml(msg.content)}</div>
          <div class="bubble-meta">${escapeHtml(formatTime(msg.created_at))}${msg.role === "user" && msg.status === "pending" ? " · 发送中" : ""}</div>
        </div>
      </div>
    `)
    .join("");
  dom.chatHistory.scrollTop = dom.chatHistory.scrollHeight;
}

/**
 * 渲染记忆列表。
 */
function renderMemories() {
  if (state.memories.length === 0) {
    dom.memoryList.innerHTML = '<div class="empty">暂无记忆条目</div>';
    return;
  }
  dom.memoryList.innerHTML = state.memories
    .map((memory) => {
      const actions = state.memoryFilter === "pending"
        ? `<div class="memory-actions">
            <button type="button" data-action="activate" data-id="${escapeHtml(memory.id)}">启用</button>
            <button type="button" class="danger" data-action="reject" data-id="${escapeHtml(memory.id)}">拒绝</button>
           </div>`
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

  dom.memoryList.querySelectorAll("button[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const status = btn.dataset.action === "activate" ? "active" : "rejected";
      reviewMemory(btn.dataset.id, status).catch((e) => {
        console.error("审核记忆失败", e);
        showToast("记忆审核失败");
      });
    });
  });
}

async function deleteAgent(sessionId) {
  await fetchJson(`${SERVER}/agents/${sessionId}`, { method: "DELETE" });
  state.sessions = state.sessions.filter((s) => s.id !== sessionId);
  if (state.inChat && state.selectedSessionId === sessionId) closeChat();
  renderAgents();
  showToast("Agent 已删除");
}

async function loadStatusData() {
  const [sessions, events] = await Promise.all([
    fetchJson(`${SERVER}/agents`),
    fetchJson(`${SERVER}/events`),
  ]);
  state.sessions = sessions;
  state.events = events;
  renderAgents();
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
  if (!state.selectedSessionId) { showToast("请先选择 Agent"); return; }
  const content = dom.chatInput.value.trim();
  if (!content) { showToast("消息不能为空"); return; }
  await fetchJson(`${SERVER}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: state.selectedSessionId, content }),
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
  const idx = state.sessions.findIndex((s) => s.id === session.id);
  if (idx >= 0) {
    state.sessions[idx] = { ...state.sessions[idx], ...session };
  } else {
    state.sessions.unshift(session);
  }
  renderAgents();
  if (state.inChat && session.id === state.selectedSessionId) {
    const s = state.sessions.find((x) => x.id === session.id);
    if (s) {
      dom.chatAgentInfo.querySelector(".status-dot").className = `status-dot ${s.status}`;
    }
  }
}

function connectWebSocket() {
  const ws = new WebSocket(WS_URL);
  ws.onopen = () => { setConnectionStatus(true); state.reconnectDelay = 1000; };
  ws.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "event") {
      state.events.unshift(payload.data);
      state.events = state.events.slice(0, 100);
      if (state.inChat && payload.data.session_id === state.selectedSessionId) {
        loadChatHistory().catch(() => {});
      }
    }
    if (payload.type === "agent_deleted") {
      state.sessions = state.sessions.filter((s) => s.id !== payload.data.id);
      renderAgents();
    }
    if (payload.type === "agent_update") upsertSession(payload.data);
  };
  ws.onclose = () => {
    setConnectionStatus(false);
    setTimeout(connectWebSocket, Math.min(state.reconnectDelay, 30000));
    state.reconnectDelay *= 2;
  };
  ws.onerror = () => ws.close();
}

async function init() {
  setConnectionStatus(false);
  await loadStatusData();
  await loadMemories();
  connectWebSocket();
}

dom.tabButtons.forEach((btn) => btn.addEventListener("click", () => switchTab(btn.dataset.tab)));
dom.backBtn.addEventListener("click", closeChat);
dom.chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  sendChatMessage().catch((e) => { console.error("发送失败", e); showToast("消息发送失败"); });
});
dom.memoryFilterPending.addEventListener("click", () => {
  state.memoryFilter = "pending";
  dom.memoryFilterPending.classList.add("active");
  dom.memoryFilterActive.classList.remove("active");
  loadMemories().catch(() => {});
});
dom.memoryFilterActive.addEventListener("click", () => {
  state.memoryFilter = "active";
  dom.memoryFilterActive.classList.add("active");
  dom.memoryFilterPending.classList.remove("active");
  loadMemories().catch(() => {});
});

init().catch((e) => {
  console.error("初始化失败", e);
  setConnectionStatus(false);
  showToast("初始化失败，请刷新重试");
});
