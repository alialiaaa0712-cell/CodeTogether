import sys
import os
import json
import importlib
import unittest.mock as mock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    monkeypatch.delenv("CODETOGETHER_SERVER", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)


def import_common():
    import hooks._common as m
    importlib.reload(m)
    return m


# --- get_session_id ---

def test_get_session_id_from_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess-abc")
    m = import_common()
    assert m.get_session_id() == "sess-abc"


def test_get_session_id_fallback():
    m = import_common()
    result = m.get_session_id()
    assert result.startswith("unknown-")


# --- post_event ---

def test_post_event_calls_server(monkeypatch):
    m = import_common()
    with mock.patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = mock.Mock(return_value=False)
        m.post_event({"session_id": "s1", "type": "pre_tool"})
    mock_open.assert_called_once()
    req = mock_open.call_args[0][0]
    assert "/events" in req.full_url
    body = json.loads(req.data)
    assert body["session_id"] == "s1"


def test_post_event_silent_on_error(monkeypatch):
    m = import_common()
    with mock.patch("urllib.request.urlopen", side_effect=Exception("conn refused")):
        m.post_event({"session_id": "s1", "type": "pre_tool"})  # 不抛异常


# --- poll_messages ---

def test_poll_messages_returns_list(monkeypatch):
    m = import_common()
    payload = [{"id": "m1", "content": "hello", "status": "pending"}]
    response = mock.MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    with mock.patch("urllib.request.urlopen", return_value=response) as mock_open:
        result = m.poll_messages("sess-1")
    assert result == payload
    req = mock_open.call_args[0][0]
    assert "/chat/sess-1/poll" in req.full_url


def test_poll_messages_empty_on_error():
    m = import_common()
    with mock.patch("urllib.request.urlopen", side_effect=Exception("timeout")):
        result = m.poll_messages("sess-1")
    assert result == []


# --- search_memory ---

def test_search_memory_returns_list(monkeypatch):
    m = import_common()
    payload = [{"title": "T", "content": "C", "tags": "t"}]
    response = mock.MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    with mock.patch("urllib.request.urlopen", return_value=response) as mock_open:
        result = m.search_memory("pytest", project_id="proj-1")
    assert result == payload
    req = mock_open.call_args[0][0]
    assert "memory/search" in req.full_url
    assert "pytest" in req.full_url


def test_search_memory_empty_on_error():
    m = import_common()
    with mock.patch("urllib.request.urlopen", side_effect=Exception("timeout")):
        result = m.search_memory("query")
    assert result == []


# --- mark_stopped ---

def test_mark_stopped_calls_patch(monkeypatch):
    m = import_common()
    with mock.patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = mock.Mock(return_value=False)
        m.mark_stopped("sess-1")
    req = mock_open.call_args[0][0]
    assert "/agents/sess-1/status" in req.full_url
    assert req.method == "PATCH"
    body = json.loads(req.data)
    assert body["status"] == "stopped"


def test_mark_stopped_silent_on_error():
    m = import_common()
    with mock.patch("urllib.request.urlopen", side_effect=Exception("conn refused")):
        m.mark_stopped("sess-1")  # 不抛异常


# ============================================================
# post_tool.py
# ============================================================

def import_post_tool():
    import hooks.post_tool as m
    importlib.reload(m)
    return m


def run_hook(module, stdin_data: dict):
    """辅助：将 stdin_data 注入 hook 的 main() 并捕获 post_event 调用。"""
    with mock.patch("hooks._common.post_event") as mock_post:
        with mock.patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = json.dumps(stdin_data)
            module.main()
    return mock_post


def test_post_tool_bash_output():
    m = import_post_tool()
    mock_post = run_hook(m, {
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "tool_response": {"stdout": "file.py\n", "stderr": "", "interrupted": False},
        "cwd": "/project",
    })
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][0]
    assert payload["session_id"] == "s1"
    assert payload["type"] == "post_tool"
    assert payload["tool_name"] == "Bash"
    assert "file.py" in payload["output"]
    assert payload["parent_session_id"] is None


def test_post_tool_with_stderr():
    m = import_post_tool()
    mock_post = run_hook(m, {
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": "bad"},
        "tool_response": {"stdout": "", "stderr": "error msg", "interrupted": False},
        "cwd": "/project",
    })
    payload = mock_post.call_args[0][0]
    assert "[stderr]" in payload["output"]


def test_post_tool_child_agent():
    m = import_post_tool()
    mock_post = run_hook(m, {
        "session_id": "parent-uuid",
        "agent_id": "childabc",
        "tool_name": "Read",
        "tool_input": {"file_path": "/x.py"},
        "tool_response": "content",
        "cwd": "/project",
    })
    payload = mock_post.call_args[0][0]
    assert payload["session_id"] == "childabc"
    assert payload["parent_session_id"] == "parent-uuid"


def test_post_tool_agent_tool_serializes_response():
    m = import_post_tool()
    mock_post = run_hook(m, {
        "session_id": "s1",
        "tool_name": "Agent",
        "tool_input": {"description": "do X"},
        "tool_response": {"result": "done"},
        "cwd": "/project",
    })
    payload = mock_post.call_args[0][0]
    assert payload["tool_name"] == "Agent"
    assert '"result"' in payload["output"]


def test_post_tool_invalid_json_no_crash():
    m = import_post_tool()
    with mock.patch("hooks._common.post_event") as mock_post:
        with mock.patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "not json"
            m.main()
    mock_post.assert_not_called()
