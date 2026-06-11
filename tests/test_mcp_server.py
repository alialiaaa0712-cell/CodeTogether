import importlib
import unittest.mock as mock

import pytest



def import_session_context():
    """
    重新加载 MCP 会话上下文模块，确保每个用例读取最新环境变量。

    参数:
        无。

    返回值:
        重新加载后的模块对象。
    """
    import mcp_server.session_context as m
    importlib.reload(m)
    return m



def import_tools():
    """
    重新加载 MCP 工具模块，避免模块级状态污染测试。

    参数:
        无。

    返回值:
        重新加载后的模块对象。
    """
    import mcp_server.tools as m
    importlib.reload(m)
    return m



def test_require_session_id_prefers_explicit_argument(monkeypatch):
    """
    验证显式传入的 session_id 优先于环境变量。

    参数:
        monkeypatch: pytest 提供的环境变量补丁工具。

    返回值:
        无返回值；通过断言优先级符合预期来验证行为。
    """
    monkeypatch.setenv("CLAUDE_SESSION_ID", "env-session")
    m = import_session_context()

    assert m.require_session_id("explicit-session") == "explicit-session"



def test_require_session_id_reads_environment(monkeypatch):
    """
    验证未显式传参时，会从运行环境读取当前 session_id。

    参数:
        monkeypatch: pytest 提供的环境变量补丁工具。

    返回值:
        无返回值；通过断言环境变量值被正确读取来验证行为。
    """
    monkeypatch.setenv("CLAUDE_SESSION_ID", "env-session")
    m = import_session_context()

    assert m.require_session_id() == "env-session"



def test_require_session_id_raises_without_any_source(monkeypatch):
    """
    验证缺少显式参数与环境变量时，MCP 工具会直接报错而不是回退 unknown 值。

    参数:
        monkeypatch: pytest 提供的环境变量补丁工具。

    返回值:
        无返回值；通过断言抛出 RuntimeError 来验证保护逻辑。
    """
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    m = import_session_context()

    with pytest.raises(RuntimeError, match="session_id"):
        m.require_session_id()



def test_memory_search_tool_passes_query_limit_and_session(monkeypatch):
    """
    验证 memory_search 工具会解析会话并把 query、limit、session_id 透传给搜索实现。

    参数:
        monkeypatch: pytest 提供的环境变量补丁工具。

    返回值:
        无返回值；通过断言 helper 调用参数与返回结构来验证行为。
    """
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess-1")
    m = import_tools()

    with mock.patch("mcp_server.tools.get_current_cwd", return_value=None), \
         mock.patch("mcp_server.tools.ensure_session_ready") as mock_ensure, \
         mock.patch("mcp_server.tools.search_memories", return_value=[{"id": "mem-1", "title": "DDL 约束"}]) as mock_search:
        result = m.memory_search_tool("mysql ddl", limit=5)

    mock_ensure.assert_called_once_with("sess-1", None)
    mock_search.assert_called_once_with("mysql ddl", "sess-1", 5)
    assert result["session_id"] == "sess-1"
    assert result["count"] == 1
    assert result["memories"][0]["id"] == "mem-1"



def test_memory_feedback_tool_passes_score_reason_and_session(monkeypatch):
    """
    验证 memory_feedback 工具会解析会话并把 memory_id、score、reason、session_id 透传给反馈实现。

    参数:
        monkeypatch: pytest 提供的环境变量补丁工具。

    返回值:
        无返回值；通过断言 helper 调用参数与返回结构来验证行为。
    """
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess-2")
    m = import_tools()

    with mock.patch("mcp_server.tools.get_current_cwd", return_value="/tmp/project"), \
         mock.patch("mcp_server.tools.ensure_session_ready") as mock_ensure, \
         mock.patch("mcp_server.tools.submit_memory_feedback", return_value={"id": "mem-2", "score_total": 2}) as mock_feedback:
        result = m.memory_feedback_tool("mem-2", 2, "确认了 DDL 边界")

    mock_ensure.assert_called_once_with("sess-2", "/tmp/project")
    mock_feedback.assert_called_once_with("mem-2", "sess-2", 2, "确认了 DDL 边界")
    assert result["session_id"] == "sess-2"
    assert result["memory"]["score_total"] == 2



def test_memory_search_tool_wraps_backend_error(monkeypatch):
    """
    验证后端搜索失败时，MCP 工具会抛出带中文上下文的错误信息。

    参数:
        monkeypatch: pytest 提供的环境变量补丁工具。

    返回值:
        无返回值；通过断言异常消息包含搜索失败语义来验证行为。
    """
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess-3")
    m = import_tools()

    with mock.patch("mcp_server.tools.get_current_cwd", return_value=None), \
         mock.patch("mcp_server.tools.ensure_session_ready"), \
         mock.patch("mcp_server.tools.search_memories", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="记忆搜索失败"):
            m.memory_search_tool("mysql ddl")
