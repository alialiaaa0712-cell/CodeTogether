"""CodeTogether 记忆 MCP 工具实现。"""
from typing import Optional

from hooks._common import memory_feedback as submit_memory_feedback
from hooks._common import memory_search as search_memories

from mcp_server.session_context import ensure_session_ready, get_current_cwd, require_session_id

_ALLOWED_SCORES = {-2, -1, 0, 1, 2}



def memory_search_tool(query: str, limit: int = 3, session_id: Optional[str] = None) -> dict:
    """
    按当前会话或显式会话 ID 搜索项目记忆。

    参数:
        query: Agent 主动提供的搜索关键词。
        limit: 最多返回条数。
        session_id: 可选显式会话 ID，主要用于调试。

    返回值:
        包含 session_id、返回数量和记忆列表的字典。

    异常:
        RuntimeError: 当搜索过程失败时抛出。
    """
    resolved_session_id = require_session_id(session_id)
    cwd = get_current_cwd()
    ensure_session_ready(resolved_session_id, cwd)
    normalized_limit = max(1, min(limit, 10))

    try:
        memories = search_memories(query, resolved_session_id, normalized_limit)
    except Exception as exc:
        raise RuntimeError(f"记忆搜索失败: {exc}") from exc

    return {
        "session_id": resolved_session_id,
        "count": len(memories),
        "memories": memories,
    }



def memory_feedback_tool(memory_id: str, score: int, reason: str, session_id: Optional[str] = None) -> dict:
    """
    为当前会话已曝光的记忆提交显式反馈。

    参数:
        memory_id: 目标记忆 ID。
        score: 反馈分值，只允许 -2/-1/0/1/2。
        reason: 反馈原因。
        session_id: 可选显式会话 ID，主要用于调试。

    返回值:
        包含 session_id 和更新后记忆对象的字典。

    异常:
        ValueError: 当 score 不在允许集合内，或 reason 为空时抛出。
        RuntimeError: 当反馈过程失败时抛出。
    """
    if score not in _ALLOWED_SCORES:
        raise ValueError("score 只允许 -2、-1、0、1、2")
    if not reason.strip():
        raise ValueError("reason 不能为空")

    resolved_session_id = require_session_id(session_id)
    cwd = get_current_cwd()
    ensure_session_ready(resolved_session_id, cwd)

    try:
        memory = submit_memory_feedback(memory_id, resolved_session_id, score, reason)
    except Exception as exc:
        raise RuntimeError(f"记忆反馈失败: {exc}") from exc

    if memory is None:
        raise RuntimeError("记忆反馈失败: 服务端未返回结果")

    return {
        "session_id": resolved_session_id,
        "memory": memory,
    }
