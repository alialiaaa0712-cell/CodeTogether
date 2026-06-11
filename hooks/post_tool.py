#!/usr/bin/env python3
"""PostToolUse hook：上报工具调用结果到 CodeTogether 服务器。"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import hooks._common as _common
from hooks.stop import sync_messages


def main():
    """
    PostToolUse hook 主入口。

    从 stdin 读取事件 JSON，解析工具响应，上报到服务器。
    子 agent 用自身 agent_id 标识，父 session_id 作为 parent_session_id。
    """
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return

    session_id = data.get("session_id") or ""
    child_agent_id = data.get("agent_id")
    if child_agent_id:
        agent_session_id = child_agent_id
        parent_session_id = session_id
    else:
        agent_session_id = session_id
        parent_session_id = None

    tool_name = data.get("tool_name")
    tr = data.get("tool_response")
    cwd = data.get("cwd")

    _common.ensure_session(agent_session_id, cwd=cwd)
    if agent_session_id:
        sync_messages(agent_session_id, cwd or "")

    if tool_name == "Agent":
        output = json.dumps(tr, ensure_ascii=False) if tr is not None else None
    elif isinstance(tr, dict):
        parts = []
        if tr.get("stdout"):
            parts.append(tr["stdout"])
        if tr.get("stderr"):
            parts.append("[stderr] " + tr["stderr"])
        if tr.get("interrupted"):
            parts.append("[interrupted]")
        if tr.get("isImage"):
            parts.append("[image output]")
        output = "\n".join(parts) if parts else None
    else:
        output = tr

    _common.post_event({
        "session_id": agent_session_id,
        "type": "post_tool",
        "tool_name": tool_name,
        "tool_use_id": data.get("tool_use_id"),
        "output": output,
        "cwd": cwd,
        "duration_ms": data.get("duration_ms"),
        "parent_session_id": parent_session_id,
    })


if __name__ == "__main__":
    main()
