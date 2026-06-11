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
    """验证 search_memory 发出一次请求并返回服务端结果。"""
    m = import_common()
    payload = [{"id": "1", "title": "T", "content": "C", "tags": "t", "tier": "long"}]
    def fake_urlopen(req, timeout):
        resp = mock.MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        return resp
    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen) as mock_open:
        result = m.search_memory("pytest", project_id="proj-1")
    assert result == payload
    assert mock_open.call_count == 1
    first_req = mock_open.call_args_list[0][0][0]
    assert "memory/search" in first_req.full_url
    assert "pytest" in first_req.full_url


def test_search_memory_empty_on_error():
    m = import_common()
    with mock.patch("urllib.request.urlopen", side_effect=Exception("timeout")):
        result = m.search_memory("query")
    assert result == []


def test_search_memory_includes_session_id_and_project_fallback():
    """验证 search_memory 会同时携带 session_id 与 project_id 回退参数。"""
    m = import_common()
    with mock.patch("urllib.request.urlopen") as mock_open:
        response = mock.MagicMock()
        response.read.return_value = json.dumps([]).encode()
        mock_open.return_value = response
        m.search_memory("pytest", project_id="proj-1", session_id="sess-1")

    req = mock_open.call_args[0][0]
    assert "session_id=sess-1" in req.full_url
    assert "project_id=proj-1" in req.full_url


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


def test_post_tool_syncs_transcript_before_posting_event():
    m = import_post_tool()
    with mock.patch("hooks.post_tool.sync_messages") as mock_sync, \
         mock.patch("hooks._common.post_event") as mock_post, \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_response": {"stdout": "ok", "stderr": "", "interrupted": False},
            "cwd": "/project",
        })
        m.main()
    mock_sync.assert_called_once_with("s1", "/project")
    mock_post.assert_called_once()



def test_post_tool_invalid_json_no_crash():
    m = import_post_tool()
    with mock.patch("hooks._common.post_event") as mock_post:
        with mock.patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "not json"
            m.main()
    mock_post.assert_not_called()


# ============================================================
# stop.py
# ============================================================

def import_stop():
    import hooks.stop as m
    importlib.reload(m)
    return m


def write_transcript(tmp_path, records):
    """将测试记录写入临时 transcript 文件，返回文件路径。"""
    path = tmp_path / "session.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def test_extract_messages_keeps_intermediate_assistant_updates(tmp_path):
    m = import_stop()
    path = write_transcript(tmp_path, [
        {
            "type": "user",
            "uuid": "u1",
            "timestamp": "2026-06-10T10:00:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "问题"}]},
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "parentUuid": "u1",
            "timestamp": "2026-06-10T10:00:01Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "我先看看代码。"}]},
        },
        {
            "type": "assistant",
            "uuid": "a2",
            "parentUuid": "a1",
            "timestamp": "2026-06-10T10:00:02Z",
            "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "x.py"}}]},
        },
        {
            "type": "user",
            "uuid": "u2",
            "parentUuid": "a2",
            "timestamp": "2026-06-10T10:00:03Z",
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tool-1", "content": "ok"}]},
        },
        {
            "type": "assistant",
            "uuid": "a3",
            "parentUuid": "u2",
            "timestamp": "2026-06-10T10:00:04Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "最终回答"}]},
        },
    ])

    messages, _ = m._extract_messages(str(path))

    assert [(msg["role"], msg["text"]) for msg in messages] == [
        ("user", "问题"),
        ("assistant", "我先看看代码。"),
        ("assistant", "最终回答"),
    ]


def test_extract_messages_keeps_terminal_assistant_text(tmp_path):
    m = import_stop()
    path = write_transcript(tmp_path, [
        {
            "type": "user",
            "uuid": "u1",
            "timestamp": "2026-06-10T10:00:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "问题"}]},
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "parentUuid": "u1",
            "timestamp": "2026-06-10T10:00:01Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "最终回答"}]},
        },
        {
            "type": "attachment",
            "uuid": "att1",
            "parentUuid": "a1",
            "timestamp": "2026-06-10T10:00:02Z",
        },
    ])

    messages, _ = m._extract_messages(str(path))

    assert [(msg["role"], msg["text"]) for msg in messages] == [
        ("user", "问题"),
        ("assistant", "最终回答"),
    ]


def test_extract_messages_filters_no_response_requested_assistant(tmp_path):
    m = import_stop()
    path = write_transcript(tmp_path, [
        {
            "type": "user",
            "uuid": "u1",
            "timestamp": "2026-06-10T10:00:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "Continue from where you left off."}]},
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "parentUuid": "u1",
            "timestamp": "2026-06-10T10:00:01Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "No response requested."}]},
        },
    ])

    messages, _ = m._extract_messages(str(path))

    assert messages == []


def test_stop_posts_event_and_marks_stopped():
    m = import_stop()
    with mock.patch("hooks._common.post_event") as mock_post, \
         mock.patch("hooks._common.mark_stopped") as mock_mark, \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "sess-99",
            "cwd": "/project",
        })
        m.main()
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][0]
    assert payload["session_id"] == "sess-99"
    assert payload["type"] == "stop"
    assert payload["cwd"] == "/project"
    mock_mark.assert_called_once_with("sess-99")


def test_stop_invalid_json_no_crash():
    m = import_stop()
    with mock.patch("hooks._common.post_event") as mock_post, \
         mock.patch("hooks._common.mark_stopped") as mock_mark, \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = "bad json"
        m.main()
    mock_post.assert_not_called()
    mock_mark.assert_not_called()


# ============================================================
# pre_tool.py
# ============================================================

def import_pre_tool():
    import hooks.pre_tool as m
    importlib.reload(m)
    return m


def test_pre_tool_posts_event():
    m = import_pre_tool()
    with mock.patch("hooks._common.post_event") as mock_post, \
         mock.patch("hooks._common.poll_messages", return_value=[]), \
         mock.patch("hooks._common.search_memory", return_value=[]), \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "cwd": "/Users/user/myproject",
        })
        m.main()
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][0]
    assert payload["session_id"] == "s1"
    assert payload["type"] == "pre_tool"
    assert payload["tool_name"] == "Bash"


def test_pre_tool_prints_messages(capsys):
    m = import_pre_tool()
    messages = [{"content": "请帮我优化这段代码"}, {"content": "记得加测试"}]
    with mock.patch("hooks._common.post_event"), \
         mock.patch("hooks._common.poll_messages", return_value=messages), \
         mock.patch("hooks._common.search_memory", return_value=[]), \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {},
            "cwd": "/project",
        })
        m.main()
    out = capsys.readouterr().out
    assert "请帮我优化这段代码" in out
    assert "记得加测试" in out
    assert "[CodeTogether 消息]" in out


def test_pre_tool_prints_memories(capsys):
    m = import_pre_tool()
    memories = [{"title": "Bash 最佳实践", "content": "总是用 set -e"}]
    with mock.patch("hooks._common.post_event"), \
         mock.patch("hooks._common.poll_messages", return_value=[]), \
         mock.patch("hooks._common.search_memory", return_value=memories), \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {},
            "cwd": "/project",
        })
        m.main()
    out = capsys.readouterr().out
    assert "Bash 最佳实践" in out
    assert "总是用 set -e" in out
    assert "[CodeTogether 记忆]" in out


def test_pre_tool_search_uses_tool_name_as_query():
    m = import_pre_tool()
    with mock.patch("hooks._common.post_event"), \
         mock.patch("hooks._common.poll_messages", return_value=[]), \
         mock.patch("hooks._common.search_memory", return_value=[]) as mock_search, \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "s1",
            "tool_name": "Edit",
            "tool_input": {},
            "cwd": "/Users/user/myproject",
        })
        m.main()
    mock_search.assert_called_once()
    call_kwargs = mock_search.call_args
    query = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1]["query"]
    assert "Edit" in query


def test_pre_tool_cwd_infers_project_id():
    m = import_pre_tool()
    with mock.patch("hooks._common.post_event"), \
         mock.patch("hooks._common.poll_messages", return_value=[]), \
         mock.patch("hooks._common.search_memory", return_value=[]) as mock_search, \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": {},
            "cwd": "/Users/user/myproject",
        })
        m.main()
    call_kwargs = mock_search.call_args
    project_id = call_kwargs[1].get("project_id") or (call_kwargs[0][1] if len(call_kwargs[0]) > 1 else None)
    assert project_id == "myproject"


def test_pre_tool_child_agent_parent_session():
    m = import_pre_tool()
    with mock.patch("hooks._common.post_event") as mock_post, \
         mock.patch("hooks._common.poll_messages", return_value=[]), \
         mock.patch("hooks._common.search_memory", return_value=[]), \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "parent-uuid",
            "agent_id": "childabc",
            "tool_name": "Bash",
            "tool_input": {},
            "cwd": "/project",
        })
        m.main()
    payload = mock_post.call_args[0][0]
    assert payload["session_id"] == "childabc"
    assert payload["parent_session_id"] == "parent-uuid"


def test_pre_tool_invalid_json_no_crash():
    m = import_pre_tool()
    with mock.patch("hooks._common.post_event") as mock_post, \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = "not json"
        m.main()
    mock_post.assert_not_called()


def test_search_memory_two_stage():
    """验证 search_memory 只发一次请求（两段式逻辑已下沉到服务端）。"""
    m = import_common()
    results_payload = [
        {"id": "1", "tier": "long", "title": "L", "content": "c"},
        {"id": "2", "tier": "short", "title": "S", "content": "c"},
    ]
    def fake_urlopen(req, timeout):
        resp = mock.MagicMock()
        resp.read.return_value = json.dumps(results_payload).encode()
        return resp

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen) as mock_open:
        results = m.search_memory("test")
    assert mock_open.call_count == 1
    assert results[0]["tier"] == "long"
    assert results[1]["tier"] == "short"


def test_flag_memory_for_review():
    """验证 flag_memory_for_review 发出 PATCH /memory/{id} 并设置 status=review。"""
    m = import_common()
    captured = {}
    def fake_urlopen(req, timeout):
        captured["method"] = req.method
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        return mock.MagicMock()

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        m.flag_memory_for_review("mem-123")

    assert captured["method"] == "PATCH"
    assert "mem-123" in captured["url"]
    assert captured["body"]["status"] == "review"
