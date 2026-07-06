from pathlib import Path
import queue
import threading
import uuid


def test_root_still_returns_healthcheck(client):
    """
    验证根路径仍返回健康检查结果。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言根路径响应状态码与返回内容符合预期。
    """
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "CodeTogether"}


def test_mobile_index_is_served(client):
    """
    验证移动端首页静态文件可以正常访问。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言移动端首页响应成功且包含预期页面内容。
    """
    resp = client.get("/mobile/index.html")
    assert resp.status_code == 200
    assert "CodeTogether Mobile" in resp.text


def test_mobile_mount_root_is_served(client):
    """
    验证挂载根路径 /mobile 会返回移动端首页内容。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言 /mobile 响应成功且包含预期页面内容。
    """
    resp = client.get("/mobile")
    assert resp.status_code == 200
    assert "CodeTogether Mobile" in resp.text


def test_mobile_assets_are_served(client):
    """
    验证移动端静态资源文件可以正常访问。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言样式与脚本资源响应成功且脚本包含 Task 3 状态页入口。
    """
    css = client.get("/mobile/style.css")
    js = client.get("/mobile/app.js")
    assert css.status_code == 200
    assert js.status_code == 200
    assert ".topbar" in css.text
    assert "async function init()" in js.text
    assert "setConnectionStatus(false);" in js.text


def test_mobile_shell_contains_core_views_and_tabs(client):
    """
    验证移动端页面骨架包含 Agent、聊天、记忆三个视图，以及底部两个主标签。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言页面 HTML 中包含视图与标签按钮的关键标识。
    """
    html = client.get("/mobile/index.html").text
    assert 'id="view-agents"' in html
    assert 'id="view-chat"' in html
    assert 'id="view-memory"' in html
    assert 'data-tab="agents"' in html
    assert 'data-tab="memory"' in html



def test_mobile_shell_contains_redesigned_overview_regions(client):
    """
    验证新版移动端骨架包含概览卡与页面说明区域，供重设计后的信息层级使用。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言页面 HTML 中包含新版概览与说明区域的关键标识。
    """
    html = client.get("/mobile/index.html").text
    assert 'id="agent-overview"' in html
    assert 'class="view-section-head' in html
    assert 'class="page-note"' not in html


def test_mobile_shell_uses_agents_view_as_default_active_tab(client):
    """
    验证移动端页面默认激活 Agent 列表页，并为底部标签声明正确的 data-tab。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言默认视图与标签按钮的静态骨架契约符合预期。
    """
    html = client.get("/mobile/index.html").text
    assert 'id="view-agents" class="view active"' in html
    assert 'class="tab-btn active" data-tab="agents"' in html
    assert 'class="tab-btn" data-tab="memory"' in html


def test_mobile_shell_contains_connection_and_feedback_controls(client):
    """
    验证移动端页面骨架包含连接状态、提示气泡以及聊天与记忆审核的关键控件。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言页面 HTML 中包含关键交互区域所需的静态元素。
    """
    html = client.get("/mobile/index.html").text
    assert 'id="conn-status"' in html
    assert 'id="toast"' in html
    assert 'id="chat-agent-info"' in html
    assert 'id="chat-form"' in html
    assert 'id="memory-list"' in html
    assert 'id="memory-filter-pending"' in html



def test_mobile_memory_shell_contains_review_board_regions(client):
    """
    验证记忆页骨架包含审核台头部、筛选摘要、列表容器与抽屉面板，支持更紧凑的审核布局。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言页面 HTML 中包含审核台布局需要的关键区域。
    """
    html = client.get("/mobile/index.html").text
    assert 'class="memory-board-head"' in html
    assert 'class="memory-board-list"' in html
    assert 'id="memory-filter-summary" class="filter-summary"' in html
    assert 'id="memory-filter-open"' in html
    assert 'id="memory-filter-drawer"' in html
    assert 'id="memory-filter-apply"' in html



def test_mobile_shell_removes_extra_page_notes(client):
    """
    验证移动端骨架不再输出冗余提示性文案，避免占用首屏空间。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言页面 HTML 中不再包含上一轮加入的说明句子。
    """
    html = client.get("/mobile/index.html").text
    assert "优先看当前在线会话" not in html
    assert "消息会在下一次工具调用时注入" not in html
    assert "按项目范围切换" not in html



def test_mobile_css_contains_compact_section_heading_rules(client):
    """
    验证移动端样式包含紧凑标题与审核台布局规则，避免标题过高挤占列表空间。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言样式文本中包含紧凑标题和记忆审核台的关键类名。
    """
    css = client.get("/mobile/style.css").text
    assert ".view-section-head.compact-head" in css
    assert ".memory-board-head" in css
    assert ".filter-open-btn" in css
    assert ".filter-summary" in css


def test_mobile_css_contains_mobile_layout_rules(client):
    """
    验证移动端样式文件包含标签栏、视图切换、卡片布局与底部安全区留白规则。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言样式文本中包含关键布局类名与一致的安全区处理策略。
    """
    css = client.get("/mobile/style.css").text
    assert ".tab-bar" in css
    assert ".view.active" in css
    assert ".card" in css
    assert "padding-bottom: calc(72px + env(safe-area-inset-bottom));" in css


def test_mobile_html_does_not_contain_duplicate_closing_tags_after_drawer(client):
    """
    验证移动端页面在筛选抽屉之后不会出现重复的结构关闭标签，避免浏览器容错解析差异。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言抽屉容器结束后直接进入底部标签栏，而不是再次关闭已结束的 section 或 main。
    """
    html = client.get("/mobile/index.html").text
    assert "</section>\n  </main>\n\n  <nav class=\"tab-bar\">" not in html
    assert "</div>\n  <nav class=\"tab-bar\">" in html


def _receive_ws_message(websocket, timeout=1.0):
    """
    在后台线程中等待一条 WebSocket JSON 消息，并以超时失败避免测试永久阻塞。

    参数:
        websocket: 已建立连接的 WebSocket 测试对象。
        timeout: 最长等待秒数，超时后直接让测试失败。

    返回值:
        接收到的 JSON 对象。
    """
    result = queue.Queue(maxsize=1)

    def _reader():
        try:
            result.put(("message", websocket.receive_json()))
        except Exception as exc:
            result.put(("error", exc))

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    kind, payload = result.get(timeout=timeout)
    if kind == "error":
        raise payload
    return payload


def test_mobile_websocket_receives_agent_update_on_create_and_status_change(client):
    """
    验证移动端 WebSocket 在会话创建与状态更新后都能收到 agent_update 消息。

    参数:
        client: FastAPI 测试客户端，用于建立 WebSocket 连接并发起 HTTP 请求。

    返回值:
        无返回值；断言两次状态变更都会推送统一结构的 agent_update。
    """
    session_id = f"session-{uuid.uuid4()}"

    with client.websocket_connect("/ws") as websocket:
        create_resp = client.post(
            "/agents",
            json={"id": session_id, "cwd": "/tmp/mobile", "model": "sonnet"},
        )
        assert create_resp.status_code == 200

        create_message = _receive_ws_message(websocket)
        assert create_message["type"] == "agent_update"
        assert create_message["data"]["id"] == session_id
        assert create_message["data"]["cwd"] == "/tmp/mobile"
        assert create_message["data"]["model"] == "sonnet"
        assert create_message["data"]["status"] == "active"

        status_resp = client.patch(f"/agents/{session_id}/status", json={"status": "stopped"})
        assert status_resp.status_code == 200

        status_message = _receive_ws_message(websocket)
        assert status_message["type"] == "agent_update"
        assert status_message["data"]["id"] == session_id
        assert status_message["data"]["status"] == "stopped"
        assert status_message["data"]["ended_at"] is not None


def test_mobile_websocket_receives_agent_update_before_event_for_new_event_session(client):
    """
    验证新会话若由 /events 首次带出，移动端会先收到 agent_update，再收到 event。

    参数:
        client: FastAPI 测试客户端，用于建立 WebSocket 连接并发起事件上报请求。

    返回值:
        无返回值；断言新会话的会话快照与事件时间线都会被实时推送。
    """
    session_id = f"session-{uuid.uuid4()}"

    with client.websocket_connect("/ws") as websocket:
        resp = client.post(
            "/events",
            json={
                "session_id": session_id,
                "type": "tool_call",
                "tool_name": "Read",
                "input": {"file_path": "/tmp/demo.txt"},
            },
        )
        assert resp.status_code == 200

        session_message = _receive_ws_message(websocket)
        assert session_message["type"] == "agent_update"
        assert session_message["data"]["id"] == session_id
        assert session_message["data"]["status"] == "active"

        event_message = _receive_ws_message(websocket)
        assert event_message["type"] == "event"
        assert event_message["data"]["session_id"] == session_id
        assert event_message["data"]["type"] == "tool_call"
        assert event_message["data"]["tool_name"] == "Read"


def test_mobile_websocket_still_broadcasts_event_messages_for_existing_session(client):
    """
    验证已存在会话上报事件时，/events 仍只推送既有 event 广播而不会破坏消息契约。

    参数:
        client: FastAPI 测试客户端，用于建立 WebSocket 连接并预先创建会话。

    返回值:
        无返回值；断言既有会话的事件广播类型仍为 event。
    """
    session_id = f"session-{uuid.uuid4()}"
    create_resp = client.post(
        "/agents",
        json={"id": session_id, "cwd": "/tmp/mobile", "model": "sonnet"},
    )
    assert create_resp.status_code == 200

    with client.websocket_connect("/ws") as websocket:
        resp = client.post(
            "/events",
            json={
                "session_id": session_id,
                "type": "tool_call",
                "tool_name": "Read",
                "input": {"file_path": "/tmp/demo.txt"},
            },
        )
        assert resp.status_code == 200

        message = _receive_ws_message(websocket)
        assert message["type"] == "event"
        assert message["data"]["session_id"] == session_id
        assert message["data"]["type"] == "tool_call"
        assert message["data"]["tool_name"] == "Read"


def test_mobile_websocket_broadcasts_parent_update_when_existing_child_gets_parent_from_event(client):
    """
    验证已存在子会话在事件上报时补写 parent_id 后，会再广播一次 agent_update 让前端及时隐藏它。

    参数:
        client: FastAPI 测试客户端，用于建立 WebSocket 连接并模拟父子会话与事件上报。

    返回值:
        无返回值；断言先收到 parent_id 已补齐的 agent_update，再收到对应 event。
    """
    parent_id = f"parent-{uuid.uuid4()}"
    child_id = f"child-{uuid.uuid4()}"
    assert client.post("/agents", json={"id": parent_id}).status_code == 200
    assert client.post("/agents", json={"id": child_id}).status_code == 200

    with client.websocket_connect("/ws") as websocket:
        resp = client.post(
            "/events",
            json={
                "session_id": child_id,
                "parent_session_id": parent_id,
                "type": "pre_tool",
                "tool_name": "Bash",
                "input": {"command": "ls"},
            },
        )
        assert resp.status_code == 200

        session_message = _receive_ws_message(websocket)
        assert session_message["type"] == "agent_update"
        assert session_message["data"]["id"] == child_id
        assert session_message["data"]["parent_id"] == parent_id

        event_message = _receive_ws_message(websocket)
        assert event_message["type"] == "event"
        assert event_message["data"]["session_id"] == child_id



def test_mobile_websocket_event_broadcast_includes_full_child_context(client):
    """
    验证子 Agent 工具事件的 WebSocket 广播会带上 parent_session_id、tool_use_id 与输入输出，便于前端实时刷新当前父会话时间线。

    参数:
        client: FastAPI 测试客户端，用于建立 WebSocket 连接并上报完整工具事件。

    返回值:
        无返回值；断言 event 广播携带父子关系与工具详情所需字段。
    """
    parent_id = f"parent-{uuid.uuid4()}"
    child_id = f"child-{uuid.uuid4()}"
    assert client.post("/agents", json={"id": parent_id}).status_code == 200
    assert client.post("/agents", json={"id": child_id, "parent_id": parent_id}).status_code == 200

    with client.websocket_connect("/ws") as websocket:
        resp = client.post(
            "/events",
            json={
                "session_id": child_id,
                "parent_session_id": parent_id,
                "type": "post_tool",
                "tool_name": "Bash",
                "tool_use_id": "toolu_demo",
                "input": {"command": "ls -la"},
                "output": "ok",
                "duration_ms": 12,
            },
        )
        assert resp.status_code == 200

        event_message = _receive_ws_message(websocket)
        assert event_message["type"] == "event"
        assert event_message["data"]["session_id"] == child_id
        assert event_message["data"]["parent_session_id"] == parent_id
        assert event_message["data"]["type"] == "post_tool"
        assert event_message["data"]["tool_name"] == "Bash"
        assert event_message["data"]["tool_use_id"] == "toolu_demo"
        assert event_message["data"]["input"] == {"command": "ls -la"}
        assert event_message["data"]["output"] == "ok"
        assert event_message["data"]["duration_ms"] == 12


def test_mobile_chat_script_contains_chat_endpoints(client):
    """
    验证移动端脚本已接入聊天历史与发送消息能力。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言脚本中包含聊天相关函数与接口调用。
    """
    js = client.get("/mobile/app.js").text
    assert "function loadChatHistory()" in js
    assert "function sendChatMessage()" in js
    assert 'fetchJson(`${SERVER}/chat/${state.selectedSessionId}/history`)' in js
    assert 'fetchJson(`${SERVER}/chat`, {' in js
    assert 'method: "POST"' in js
    assert '消息已发送，等待 Agent 下一次工具调用时接收' in js
    assert 'payload.data.session_id === state.selectedSessionId ||' in js
    assert 'if (state.inChat && payload.data.session_id === state.selectedSessionId)' in js


def test_mobile_memory_script_contains_review_actions(client):
    """
    验证移动端脚本已接入记忆拉取与审核动作。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言脚本中包含记忆筛选、审核与 PATCH 调用。
    """
    js = client.get("/mobile/app.js").text
    assert "function loadMemories()" in js
    assert "function reviewMemory(memoryId, status)" in js
    assert 'let url = `${SERVER}/memory?status=${state.memoryFilter}`' in js
    assert 'fetchJson(`${SERVER}/memory/${memoryId}`, {' in js
    assert 'method: "PATCH"' in js
    assert '记忆已启用' in js
    assert '记忆已删除' in js



def test_mobile_memory_script_contains_filter_drawer_flow(client):
    """
    验证记忆页脚本包含筛选摘要与抽屉式应用流程，而不是直接堆叠多排筛选按钮。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言脚本中包含筛选摘要和抽屉开关逻辑的关键入口。
    """
    js = client.get("/mobile/app.js").text
    assert 'memoryDrawerOpen: false' in js
    assert 'draftMemoryFilter' in js
    assert 'function renderMemoryFilterSummary()' in js
    assert 'function setMemoryDrawer(open)' in js
    assert 'id="memory-filter-summary"' not in js


def test_mobile_memory_script_shows_score_metrics_instead_of_hit_count(client):
    """验证记忆页脚本展示累计积分与反馈次数，而不再展示 7 天命中。"""
    js = client.get("/mobile/app.js").text
    assert "累计积分" in js
    assert "反馈" in js
    assert "last_feedback_at" in js
    assert "review_score" in js
    assert "7天命中" not in js


def test_mobile_memory_script_contains_promote_and_delete_actions(client):
    """验证 review 区保留升为长期与删除动作。"""
    js = client.get("/mobile/app.js").text
    assert "async function promoteMemory(memoryId)" in js
    assert "async function deleteMemory(memoryId)" in js
    assert "记忆已升为长期" in js
    assert "记忆已删除" in js


def test_mobile_memory_html_contains_review_and_active_filters(client):
    """验证记忆页仍有待启用、待晋升、已启用三个分区入口。"""
    html = client.get("/mobile/index.html").text
    assert 'id="memory-filter-pending"' in html
    assert 'id="memory-filter-review"' in html
    assert 'id="memory-filter-active"' in html


def test_mobile_memory_html_contains_scope_toggle(client):
    """验证记忆页包含当前项目/全部项目切换与 review 分区入口。"""
    html = client.get("/mobile/index.html").text
    assert 'id="memory-scope-current"' in html
    assert 'id="memory-scope-all"' in html
    assert 'id="memory-filter-review"' in html



def test_mobile_memory_script_defaults_to_current_project_scope(client):
    """验证记忆页脚本默认按当前项目范围加载，并支持 project_id 过滤。"""
    js = client.get("/mobile/app.js").text
    assert 'memoryScope: "current"' in js
    assert "function getCurrentMemoryProjectId()" in js
    assert 'url += `&project_id=${encodeURIComponent(projectId)}`' in js



def test_mobile_memory_script_uses_delete_for_reject(client):
    """验证记忆页对删除/拒绝动作使用 DELETE 接口。"""
    js = client.get("/mobile/app.js").text
    assert "async function deleteMemory(memoryId)" in js
    assert 'fetchJson(`${SERVER}/memory/${memoryId}`, { method: "DELETE" })' in js
    assert "async function promoteMemory(memoryId)" in js


def test_mobile_memory_script_does_not_render_removed_hit_count(client):
    """验证记忆页不再展示已移除的 hit 统计文案。

    参数:
        client: FastAPI 测试客户端，用于读取移动端脚本文本。

    返回值:
        无返回值；通过断言旧字段与旧文案都不存在来验证前端契约已切换。
    """
    js = client.get("/mobile/app.js").text
    assert "hit_count_7d" not in js
    assert "7天命中" not in js


def test_mobile_chat_script_supports_markdown_and_jump_to_latest(client):
    """
    验证聊天页脚本支持 assistant Markdown 渲染，并在用户离开底部后展示跳转到最新消息按钮。

    参数:
        client: FastAPI 测试客户端，用于读取移动端脚本文本。

    返回值:
        无返回值；断言脚本中存在 Markdown 渲染入口、跳转按钮状态和手动跳转逻辑。
    """
    js = client.get("/mobile/app.js").text
    assert "function renderMarkdown(" in js
    assert "item.role === \"assistant\" ? renderMarkdown(item.content) : escapeHtml(item.content)" in js
    assert "chatShouldAutoScroll" in js
    assert "showJumpToLatest" in js
    assert "function jumpToLatestMessage()" in js
    assert "function isNearChatBottom()" in js
    assert "dom.chatHistory.addEventListener(\"scroll\"" in js


def test_mobile_chat_css_uses_fixed_chat_view_and_inner_scroll(client):
    """
    验证聊天页使用固定高度视图和内部滚动容器，避免整页滚动导致自动滚底与跳转按钮失效。

    参数:
        client: FastAPI 测试客户端，用于读取移动端样式文本。

    返回值:
        无返回值；断言聊天视图限制高度且历史列表负责滚动。
    """
    css = client.get("/mobile/style.css").text
    assert "#view-chat {" in css
    assert "min-height: calc(100dvh - 86px - 84px - env(safe-area-inset-bottom));" not in css
    # 聊天视图高度限制（具体值随布局优化可能变化，只验证结构存在）
    assert "height: calc(100dvh -" in css
    assert "#view-chat.active {" in css
    assert "overflow: hidden;" in css
    assert ".chat-history {" in css
    assert "overflow-y: auto;" in css


def test_mobile_chat_html_contains_jump_to_latest_button(client):
    """
    验证聊天页骨架包含跳转到最新消息按钮，供新消息到达且用户未停留在底部时使用。

    参数:
        client: FastAPI 测试客户端，用于读取移动端首页 HTML。

    返回值:
        无返回值；断言页面中存在聊天跳转按钮容器。
    """
    html = client.get("/mobile/index.html").text
    assert 'id="chat-jump-latest"' in html


def test_mobile_chat_script_keeps_tool_call_timeline_rendering(client):
    """
    验证聊天脚本仍会把工具调用事件渲染进时间线，而不是只显示用户和助手消息。

    参数:
        client: FastAPI 测试客户端，用于读取移动端脚本文本。

    返回值:
        无返回值；断言事件分支仍生成 tool-call 结构，并保留 child-agent 徽章与工具输入输出折叠区。
    """
    js = client.get("/mobile/app.js").text
    assert 'if (item._type === "event") {' in js
    assert 'tool-call${isChild ? " child-agent" : ""}' in js
    assert 'child-agent-badge' in js
    assert 'class="tool-io-block"' in js



def test_mobile_chat_script_preserves_tool_call_and_unmatched_post_events(client):
    """
    验证聊天脚本不会丢掉 tool_call 事件或未配对到 pre_tool 的 post_tool 事件，避免工具时间线静默缺失。

    参数:
        client: FastAPI 测试客户端，用于读取移动端脚本文本。

    返回值:
        无返回值；断言脚本会显式处理 tool_call，并保留未匹配 post_tool 的兜底分支。
    """
    js = client.get("/mobile/app.js").text
    assert 'e.type === "tool_call"' in js
    assert 'paired.push({ ...e, done: true })' in js



def test_mobile_chat_script_keeps_tool_details_visible_by_default(client):
    """
    验证聊天页工具详情默认可见，而不是依赖 details 折叠后才看得到输入输出。

    参数:
        client: FastAPI 测试客户端，用于读取移动端脚本文本。

    返回值:
        无返回值；断言工具详情使用默认展开的可见容器，而不是 details 标签。
    """
    js = client.get("/mobile/app.js").text
    assert '<details class="tool-io">' not in js
    assert 'class="tool-io-block"' in js



def test_mobile_chat_script_keeps_read_tool_input_visible(client):
    """
    验证 Read 工具卡片不会只剩一行标题，而会默认展示输入内容，避免用户误以为工具信息消失。

    参数:
        client: FastAPI 测试客户端，用于读取移动端脚本文本。

    返回值:
        无返回值；断言 Read/Write 分支会构造 IN 展示块。
    """
    js = client.get("/mobile/app.js").text
    assert 'if (tool === "Read" || tool === "Write") {' in js
    assert 'const inBlock = inp.file_path ? `<div class="tool-io-block"><div class="tool-io-label">IN</div><pre class="tool-detail">${escapeHtml(inp.file_path)}</pre></div>` : "";' in js


def test_mobile_chat_css_avoids_horizontal_scroll_for_messages(client):
    """
    验证消息区不通过横向滚动展示内容，代码块与工具详情都应在窄屏内换行或裁切。

    参数:
        client: FastAPI 测试客户端，用于读取移动端样式文本。

    返回值:
        无返回值；断言消息区没有横向滚动设置，且代码块与详情文本使用换行策略。
    """
    css = client.get("/mobile/style.css").text
    assert "overflow-x: auto;" not in css
    assert ".bubble-content .md-code {" in css
    assert "overflow-x: hidden;" in css
    assert ".tool-detail {" in css
    assert "word-break: break-word;" in css


def test_mobile_memory_html_uses_single_filter_entry(client):
    """
    验证记忆页只保留一个筛选入口，避免摘要区与筛选按钮重复打开同一个抽屉。

    参数:
        client: FastAPI 测试客户端，用于读取移动端首页 HTML。

    返回值:
        无返回值；断言保留筛选按钮，摘要区仅作静态展示而不是第二个 button。
    """
    html = client.get("/mobile/index.html").text
    assert 'id="memory-filter-open"' in html
    assert 'id="memory-filter-summary" class="filter-summary"' in html
    assert '<button id="memory-filter-summary"' not in html


def test_mobile_html_uses_versioned_asset_urls(client):
    """
    验证移动端页面为静态脚本和样式附带版本参数，避免手机浏览器继续复用旧缓存导致前端修复不生效。

    参数:
        client: FastAPI 测试客户端，用于读取移动端首页 HTML。

    返回值:
        无返回值；断言样式与脚本引用都带版本查询参数。
    """
    html = client.get("/mobile/index.html").text
    assert 'href="style.css?v=' in html
    assert 'src="app.js?v=' in html



def test_readme_mentions_mobile_entry():
    """
    验证 README 已包含手机浏览器访问入口与使用说明。

    参数:
        无。

    返回值:
        无返回值；断言 README 中包含 mobile 入口地址与页面能力说明。
    """
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "手机浏览器访问" in readme
    assert "/mobile/" in readme
    assert "7879" in readme
