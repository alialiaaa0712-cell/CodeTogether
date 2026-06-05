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
