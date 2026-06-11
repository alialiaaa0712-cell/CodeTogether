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
  memoryScope: "current",
  tierFilter: "all",
  inChat: false,
  chatPollTimer: null,
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
  memoryFilterReview: document.getElementById("memory-filter-review"),
  memoryFilterActive: document.getElementById("memory-filter-active"),
  memoryScopeCurrent: document.getElementById("memory-scope-current"),
  memoryScopeAll: document.getElementById("memory-scope-all"),
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
  if (resp.status === 204 || resp.headers.get("content-length") === "0") return null;
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
  if (!Array.isArray(state.sessions) || state.sessions.filter((s) => !s.parent_id).length === 0) {
    dom.projectGroups.innerHTML = '<div class="empty">暂无 Agent</div>';
    return;
  }

  // 按项目分组，子 Agent（有 parent_id）不显示在列表
  const groups = {};
  [...state.sessions]
    .filter((s) => !s.parent_id)
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

  clearInterval(state.chatPollTimer);
  state.chatPollTimer = setInterval(() => {
    if (state.inChat) loadChatHistory().catch(() => {});
  }, 5000);
}

/**
 * 从聊天视图返回 agent 列表。
 */
function closeChat() {
  state.inChat = false;
  clearInterval(state.chatPollTimer);
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
  console.log(`[render] total=${state.chatMessages.length} events=${state.chatMessages.filter(m => m._type==="event").length}`);
  dom.chatHistory.innerHTML = state.chatMessages
    .map((item) => {
      if (item._type === "event") {
        const isChild = item.parent_session_id && item.parent_session_id !== state.selectedSessionId;
        const childBadge = isChild ? `<span class="child-agent-badge">子 ${escapeHtml(item.session_id.slice(0, 8))}</span>` : "";
        const statusClass = item.done ? "post_tool" : "pre_tool";
        const durationStr = item.duration_ms ? ` · ${item.duration_ms}ms` : "";
        const tool = item.tool_name || "";
        const inp = item.input && typeof item.input === "object" ? item.input : {};

        // 按工具类型渲染标题和展开内容
        let titleExtra = "";
        let detailBlock = "";

        if (tool === "Read" || tool === "Write") {
          titleExtra = inp.file_path || "";
          if (tool === "Write" && item.done) {
            const out = item.output || "";
            detailBlock = out ? `<details class="tool-io"><summary>OUT</summary><pre class="tool-detail tool-output">${escapeHtml(out.slice(0, 1000))}</pre></details>` : "";
          }
        } else if (tool === "Edit") {
          titleExtra = inp.file_path || "";
          // 只展示 old/new，不展示 file_path 重复
          const editContent = inp.old_string != null ? `- ${String(inp.old_string).split("\n")[0].slice(0, 60)}\n+ ${String(inp.new_string || "").split("\n")[0].slice(0, 60)}` : "";
          detailBlock = editContent ? `<details class="tool-io"><summary>DIFF</summary><pre class="tool-detail">${escapeHtml(editContent)}</pre></details>` : "";
        } else if (tool === "Bash") {
          titleExtra = inp.description || String(inp.command || "").split("\n")[0].slice(0, 60);
          const cmd = inp.command || "";
          const out = item.output || "";
          const inBlock = cmd ? `<details class="tool-io"><summary>IN</summary><pre class="tool-detail">${escapeHtml(cmd.slice(0, 1000))}</pre></details>` : "";
          const outBlock = out ? `<details class="tool-io"><summary>OUT</summary><pre class="tool-detail tool-output">${escapeHtml(out.slice(0, 2000))}${out.length > 2000 ? "\n…（已截断）" : ""}</pre></details>` : "";
          detailBlock = inBlock + outBlock;
        } else if (tool === "Agent") {
          titleExtra = inp.description || "";
          const out = item.output || "";
          detailBlock = out ? `<details class="tool-io"><summary>OUT</summary><pre class="tool-detail tool-output">${escapeHtml(out.slice(0, 1000))}</pre></details>` : "";
        } else {
          // 通用：取第一个字符串字段作摘要，IN/OUT 折叠
          const firstStr = Object.values(inp).find(v => typeof v === "string");
          if (firstStr) titleExtra = String(firstStr).split("\n")[0].slice(0, 60);
          const inputStr = Object.keys(inp).length ? JSON.stringify(inp, null, 2) : "";
          const out = item.output || "";
          const inBlock = inputStr ? `<details class="tool-io"><summary>IN</summary><pre class="tool-detail">${escapeHtml(inputStr.slice(0, 1000))}</pre></details>` : "";
          const outBlock = out ? `<details class="tool-io"><summary>OUT</summary><pre class="tool-detail tool-output">${escapeHtml(out.slice(0, 2000))}</pre></details>` : "";
          detailBlock = inBlock + outBlock;
        }

        const title = titleExtra ? `${escapeHtml(tool)} ${escapeHtml(titleExtra)}` : escapeHtml(tool);

        return `<div class="tool-call${isChild ? " child-agent" : ""} ${statusClass}">
            <div class="tool-call-summary">
              ${childBadge}
              <span class="tool-title">${title}</span>
              <span class="tool-time">${escapeHtml(formatTime(item.created_at))}${escapeHtml(durationStr)}</span>
            </div>
            ${detailBlock}
          </div>`;
      }
      return `<div class="bubble-row ${escapeHtml(item.role)}">
          <div class="bubble ${escapeHtml(item.role)}">
            <div class="bubble-content">${escapeHtml(item.content)}</div>
            <div class="bubble-meta">${escapeHtml(formatTime(item.created_at))}${item.role === "user" && item.status === "pending" ? " · 发送中" : ""}</div>
          </div>
        </div>`;
    })
    .join("");
  // 只在已经接近底部时才自动滚动，避免轮询刷新时打断用户阅读
  const el = dom.chatHistory;
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 80) {
    el.scrollTop = el.scrollHeight;
  }
}

/**
 * 渲染记忆列表。
 */
function renderMemories() {
  const tierFilterHtml = state.memoryFilter === "active" ? `
    <div class="tier-filter">
      <button type="button" data-tier="all" class="${state.tierFilter === 'all' ? 'active' : ''}">全部</button>
      <button type="button" data-tier="long" class="${state.tierFilter === 'long' ? 'active' : ''}">长期</button>
      <button type="button" data-tier="short" class="${state.tierFilter === 'short' ? 'active' : ''}">短期</button>
    </div>` : "";

  if (state.memories.length === 0) {
    dom.memoryList.innerHTML = tierFilterHtml + '<div class="empty">暂无记忆条目</div>';
    dom.memoryList.querySelectorAll(".tier-filter button").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.tierFilter = btn.dataset.tier;
        loadMemories().catch(() => {});
      });
    });
    return;
  }

  dom.memoryList.innerHTML = tierFilterHtml + state.memories.map((memory) => {
    const isReview = memory.status === "review";
    const tierText = memory.tier === "long" ? "长期" : memory.tier === "short" ? "短期" : escapeHtml(memory.tier);
    const tierLabel = `<span class="tier-badge ${escapeHtml(memory.tier)}">${tierText}</span>`;
    const hitHint = ` · 7天命中 ${escapeHtml(memory.hit_count_7d ?? 0)} 次`;
    const actions = state.memoryFilter === "pending"
      ? `<div class="memory-actions">
          <button type="button" data-action="activate" data-id="${escapeHtml(memory.id)}">启用</button>
          <button type="button" class="danger" data-action="delete" data-id="${escapeHtml(memory.id)}">删除</button>
         </div>`
      : isReview
        ? `<div class="memory-actions">
            <button type="button" data-action="promote" data-id="${escapeHtml(memory.id)}">升为长期</button>
            <button type="button" class="danger" data-action="delete" data-id="${escapeHtml(memory.id)}">删除</button>
           </div>`
        : "";
    return `
      <div class="memory-item${isReview ? ' memory-review' : ''}">
        <div class="memory-row">
          <strong>${escapeHtml(memory.title)}</strong>${tierLabel}
          <span>${escapeHtml(memory.status)}</span>
        </div>
        <div class="hint">tags: ${escapeHtml(memory.tags || "—")} · ${escapeHtml(formatTime(memory.updated_at || memory.created_at))}${hitHint}</div>
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
      } else if (action === "promote") {
        promoteMemory(btn.dataset.id).catch(() => showToast("操作失败"));
      } else if (action === "delete") {
        deleteMemory(btn.dataset.id).catch(() => showToast("操作失败"));
      }
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
  let messages = [], events = [];
  try {
    [messages, events] = await Promise.all([
      fetchJson(`${SERVER}/chat/${state.selectedSessionId}/history`),
    fetchJson(`${SERVER}/events?session_id=${state.selectedSessionId}&include_children=true`),
    ]);
  } catch (e) {
    console.error("loadChatHistory fetch error", e);
    showToast("加载失败: " + e.message);
    return;
  }

  // pre/post 配对：优先用 tool_use_id 精确匹配，回退到 tool_name FIFO
  const paired = [];
  const preById = {};   // tool_use_id → pre event
  const preQueue = {};  // tool_name → pre event[]（无 tool_use_id 时的回退）
  [...events].sort((a, b) => a.created_at - b.created_at).forEach((e) => {
    if (e.type === "pre_tool") {
      const pre = { ...e, done: false };
      if (e.tool_use_id) preById[e.tool_use_id] = pre;
      else (preQueue[e.tool_name] = preQueue[e.tool_name] || []).push(pre);
    } else if (e.type === "post_tool") {
      let pre = null;
      if (e.tool_use_id && preById[e.tool_use_id]) {
        pre = preById[e.tool_use_id];
        delete preById[e.tool_use_id];
      } else {
        const q = preQueue[e.tool_name];
        if (q && q.length) pre = q.shift();
      }
      if (pre) paired.push({ ...pre, done: true, output: e.output, duration_ms: e.duration_ms });
    }
  });
  Object.values(preById).forEach((e) => paired.push(e));
  Object.values(preQueue).forEach((q) => q.forEach((e) => paired.push(e)));

  console.log(`[chat] messages=${messages.length} events=${events.length} paired=${paired.length}`);

  const eventItems = paired.map((e) => ({ _type: "event", ...e }));
  const msgItems = messages.map((m) => ({ ...m, _type: "message" }));
  state.chatMessages = [...msgItems, ...eventItems].sort((a, b) => a.created_at - b.created_at);
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

function getCurrentMemoryProjectId() {
  if (state.selectedSessionId) {
    const session = state.sessions.find((item) => item.id === state.selectedSessionId);
    if (session?.project_id) return session.project_id;
  }
  const latest = [...state.sessions]
    .sort((a, b) => (b.started_at || 0) - (a.started_at || 0))
    .find((item) => item.project_id);
  return latest?.project_id || null;
}

async function loadMemories() {
  let url = `${SERVER}/memory?status=${state.memoryFilter}`;
  if (state.memoryScope === "current") {
    const projectId = getCurrentMemoryProjectId();
    if (projectId) {
      url += `&project_id=${encodeURIComponent(projectId)}`;
    }
  }
  if (state.memoryFilter === "active" && state.tierFilter !== "all") {
    url += `&tier=${encodeURIComponent(state.tierFilter)}`;
  }
  state.memories = await fetchJson(url);
  renderMemories();
}

async function reviewMemory(memoryId, status) {
  await fetchJson(`${SERVER}/memory/${memoryId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  showToast("记忆已启用");
  await loadMemories();
}

async function promoteMemory(memoryId) {
  await fetchJson(`${SERVER}/memory/${memoryId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tier: "long" }),
  });
  showToast("已升为长期记忆");
  await loadMemories();
}

async function deleteMemory(memoryId) {
  await fetchJson(`${SERVER}/memory/${memoryId}`, { method: "DELETE" });
  showToast("记忆已删除");
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
      const relatedToCurrentChat = state.inChat && (
        payload.data.session_id === state.selectedSessionId ||
        payload.data.parent_session_id === state.selectedSessionId
      );
      if (relatedToCurrentChat) {
        loadChatHistory().catch(() => {});
      }
    }
    if (payload.type === "chat_message") {
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
  updateMemoryFilterButtons();
  updateMemoryScopeButtons();
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
function updateMemoryFilterButtons() {
  dom.memoryFilterPending.classList.toggle("active", state.memoryFilter === "pending");
  dom.memoryFilterReview.classList.toggle("active", state.memoryFilter === "review");
  dom.memoryFilterActive.classList.toggle("active", state.memoryFilter === "active");
}

function updateMemoryScopeButtons() {
  dom.memoryScopeCurrent.classList.toggle("active", state.memoryScope === "current");
  dom.memoryScopeAll.classList.toggle("active", state.memoryScope === "all");
}

dom.memoryFilterPending.addEventListener("click", () => {
  state.memoryFilter = "pending";
  state.tierFilter = "all";
  updateMemoryFilterButtons();
  loadMemories().catch(() => {});
});
dom.memoryFilterReview.addEventListener("click", () => {
  state.memoryFilter = "review";
  state.tierFilter = "all";
  updateMemoryFilterButtons();
  loadMemories().catch(() => {});
});
dom.memoryFilterActive.addEventListener("click", () => {
  state.memoryFilter = "active";
  state.tierFilter = "all";
  updateMemoryFilterButtons();
  loadMemories().catch(() => {});
});
dom.memoryScopeCurrent.addEventListener("click", () => {
  state.memoryScope = "current";
  updateMemoryScopeButtons();
  loadMemories().catch(() => {});
});
dom.memoryScopeAll.addEventListener("click", () => {
  state.memoryScope = "all";
  updateMemoryScopeButtons();
  loadMemories().catch(() => {});
});

init().catch((e) => {
  console.error("初始化失败", e);
  setConnectionStatus(false);
  showToast("初始化失败，请刷新重试");
});
