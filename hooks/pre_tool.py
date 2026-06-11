#!/usr/bin/env python3
"""PreToolUse hook：上报事件，并将 pending 消息和相关记忆注入给 Claude。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import hooks._common as _common
from hooks.stop import sync_messages


def _project_id_from_cwd(cwd: str) -> "str | None":
    """
    用 cwd 最后一段路径作为 project_id 近似值。

    服务器存储 project.name 与目录名通常一致；若 cwd 为空则返回 None，
    服务器搜索不限项目范围。
    """
    if not cwd:
        return None
    return os.path.basename(cwd.rstrip("/"))


def _query_from_input(tool_name: str, tool_input: dict) -> str:
    """
    从工具输入中提取有意义的查询词。

    优先使用任务相关的文本字段（command、file_path、prompt 等），
    回退到工具名，避免搜索词过于泛化。
    """
    if not isinstance(tool_input, dict):
        return tool_name
    for key in ("command", "description", "prompt", "query", "file_path", "new_string"):
        val = tool_input.get(key)
        if val and isinstance(val, str):
            return val[:200]
    return tool_name


def main():
    """
    PreToolUse hook 主入口。

    1. 上报 pre_tool 事件
    2. 拉取 pending 消息 → print 给 Claude
    3. 搜索相关记忆 → print 给 Claude
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

    _common.ensure_session(agent_session_id, cwd=cwd)
    # 工具调用前先补同步一次 transcript，避免活跃会话里的上一段对话要等到 Stop 才出现在手机端
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

    project_id = _project_id_from_cwd(cwd)
    query = _query_from_input(tool_name, data.get("tool_input") or {})
    for mem in _common.search_memory(query, project_id=project_id, session_id=agent_session_id):
        print(f"\n[CodeTogether 记忆]: {mem['title']} — {mem['content']}\n", flush=True)


if __name__ == "__main__":
    main()
