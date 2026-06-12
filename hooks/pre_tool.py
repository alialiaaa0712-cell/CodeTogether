#!/usr/bin/env python3
"""PreToolUse hook：上报事件，并将 pending 消息注入给 Claude。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import hooks._common as _common
from hooks.stop import sync_messages


def main():
    """
    PreToolUse hook 主入口。

    1. 上报 pre_tool 事件
    2. 拉取 pending 消息 → print 给 Claude
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

    cwd = data.get("cwd") or ""
    tool_name = data.get("tool_name") or ""

    repo_url = _common.get_repo_url(cwd)
    _common.ensure_session(agent_session_id, cwd=cwd, repo_url=repo_url)
    if agent_session_id:
        sync_messages(agent_session_id, cwd)

    _common.post_event({
        "session_id": agent_session_id,
        "type": "pre_tool",
        "tool_name": tool_name,
        "tool_use_id": data.get("tool_use_id"),
        "input": data.get("tool_input"),
        "cwd": cwd,
        "parent_session_id": parent_session_id,
    })

    for msg in _common.poll_messages(agent_session_id):
        print(f"\n[CodeTogether 消息]: {msg['content']}\n", flush=True)


if __name__ == "__main__":
    main()
