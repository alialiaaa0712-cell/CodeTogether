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
    验证移动端页面骨架包含三个视图容器与三个标签按钮的契约。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言页面 HTML 中包含视图与标签按钮的关键标识。
    """
    html = client.get("/mobile/index.html").text
    assert 'id="view-status"' in html
    assert 'id="view-chat"' in html
    assert 'id="view-memory"' in html
    assert 'id="tab-status"' in html
    assert 'id="tab-chat"' in html
    assert 'id="tab-memory"' in html


def test_mobile_shell_uses_status_view_as_default_active_tab(client):
    """
    验证移动端页面默认激活状态页，并为三个标签按钮声明正确的 data-tab。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言默认视图与标签按钮的静态骨架契约符合预期。
    """
    html = client.get("/mobile/index.html").text
    assert 'id="view-status" class="view active"' in html
    assert 'id="tab-status" class="tab-btn active" data-tab="status"' in html
    assert 'id="tab-chat" class="tab-btn" data-tab="chat"' in html
    assert 'id="tab-memory" class="tab-btn" data-tab="memory"' in html


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
    assert 'id="chat-session-select"' in html
    assert 'id="chat-form"' in html
    assert 'id="memory-list"' in html
    assert 'id="memory-filter-pending"' in html


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
    assert 'if (payload.data.session_id === state.selectedSessionId)' in js


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
    assert 'fetchJson(`${SERVER}/memory?status=${state.memoryFilter}`)' in js
    assert 'fetchJson(`${SERVER}/memory/${memoryId}`, {' in js
    assert 'method: "PATCH"' in js
    assert '记忆已启用' in js
    assert '记忆已拒绝' in js


def test_readme_mentions_mobile_entry():
    """
    验证 README 已包含手机 Web App 入口与使用说明。

    参数:
        无。

    返回值:
        无返回值；断言 README 中包含 mobile 入口地址与页面能力说明。
    """
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "手机 Web App" in readme
    assert "/mobile/index.html" in readme
    assert "7878" in readme
