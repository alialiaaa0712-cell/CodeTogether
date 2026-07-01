"""MCP 工具调用时的会话上下文解析。"""
import os
from typing import Optional

import hooks._common as _common

_SESSION_ENV_KEYS = (
    "CLAUDE_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
)
_CWD_ENV_KEYS = (
    "CLAUDE_CWD",
    "PWD",
)



def require_session_id(explicit_session_id: Optional[str] = None) -> str:
    """
    解析当前 MCP 调用应绑定的会话 ID。

    参数:
        explicit_session_id: 工具显式传入的会话 ID；为空时回退到运行环境。

    返回值:
        当前调用应使用的会话 ID。

    异常:
        RuntimeError: 当显式参数与环境变量都拿不到 session_id 时抛出。
    """
    if explicit_session_id:
        return explicit_session_id

    for env_key in _SESSION_ENV_KEYS:
        value = os.environ.get(env_key, "").strip()
        if value:
            return value

    raise RuntimeError("缺少 session_id，无法调用记忆工具")



def get_current_cwd() -> Optional[str]:
    """
    解析当前 Claude 运行环境中的工作目录。

    参数:
        无。

    返回值:
        当前工作目录；若运行环境未提供则返回 None。
    """
    for env_key in _CWD_ENV_KEYS:
        value = os.environ.get(env_key, "").strip()
        if value:
            return value
    return None



def ensure_session_ready(session_id: str, cwd: Optional[str]) -> None:
    """
    调用记忆工具前，确保服务端中存在当前会话记录。

    参数:
        session_id: 当前会话 ID。
        cwd: 当前工作目录，可为空。

    返回值:
        无。
    """
    _common.ensure_session(session_id, cwd=cwd)
