#!/usr/bin/env python3
"""SessionStart hook：确保会话存在并关联项目，支持 VSCode 等无 cwd 延迟上报的入口。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import hooks._common as _common


def main():
    """
    SessionStart hook 主入口。

    在会话启动时立即用 cwd 创建或更新 session，确保 project_id 在首次工具调用前就关联好。

    参数:
        无，从 stdin 读取 JSON payload。

    返回值:
        无。
    """
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return

    session_id = data.get("session_id") or ""
    cwd = data.get("cwd") or ""
    if not session_id:
        return

    repo_url = _common.get_repo_url(cwd) if cwd else None
    _common.ensure_session(session_id, cwd=cwd, repo_url=repo_url)


if __name__ == "__main__":
    main()
