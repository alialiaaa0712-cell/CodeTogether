#!/usr/bin/env python3
"""Notification hook：将 Claude 的文本回复写入消息表，供手机端查看。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import hooks._common as _common


def main():
    """
    Notification hook 主入口。

    Claude Code 每次向用户输出文本消息时触发，stdin 包含 session_id 和 message 字段。
    将 message 以 role=assistant 写入服务端消息表，使手机端能看到 Claude 的回复。
    """
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except Exception:
        return

    session_id = data.get("session_id") or ""
    child_agent_id = data.get("agent_id")
    if child_agent_id:
        target_session_id = child_agent_id
        parent_session_id = session_id
    else:
        target_session_id = session_id
        parent_session_id = None

    message = data.get("message") or ""
    if not target_session_id or not message:
        return

    # 确保 session 存在，否则先创建
    _common.ensure_session(target_session_id, cwd=data.get("cwd"), parent_id=parent_session_id)
    _common.post_chat_message(target_session_id, message, role="assistant")


if __name__ == "__main__":
    main()
