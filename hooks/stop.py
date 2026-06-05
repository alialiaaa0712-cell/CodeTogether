#!/usr/bin/env python3
"""Stop hook：上报会话停止事件，触发服务器知识提炼。"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import hooks._common as _common


def main():
    """
    Stop hook 主入口。

    上报 stop 类型事件，然后调用 mark_stopped 将会话标记为 stopped，
    服务器收到状态变更后触发知识提炼后台任务。
    """
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return

    session_id = data.get("session_id") or ""
    _common.post_event({
        "session_id": session_id,
        "type": "stop",
        "cwd": data.get("cwd"),
    })
    _common.mark_stopped(session_id)


if __name__ == "__main__":
    main()
