#!/usr/bin/env python3
"""Stop hook：上报会话停止事件，并从 JSONL transcript 同步 assistant 消息到服务端。"""
import json
import os
import sys
import glob
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import hooks._common as _common

CLAUDE_PROJECTS_DIR = os.path.expanduser("~/.claude/projects")


def _slug_from_cwd(cwd: str) -> str:
    """将 cwd 路径转为 Claude 项目目录 slug（用 - 替换 /）。"""
    return cwd.replace("/", "-").lstrip("-")


def _find_transcript(session_id: str, cwd: str) -> str:
    """
    定位会话对应的 JSONL transcript 文件。

    先按 cwd slug 找项目目录，再按 session_id 匹配文件名。
    """
    if cwd:
        slug = _slug_from_cwd(cwd)
        candidate = os.path.join(CLAUDE_PROJECTS_DIR, slug, f"{session_id}.jsonl")
        if os.path.exists(candidate):
            return candidate

    # 回退：全局搜索
    matches = glob.glob(os.path.join(CLAUDE_PROJECTS_DIR, "**", f"{session_id}.jsonl"), recursive=True)
    return matches[0] if matches else None


SYNC_STATE_DIR = os.path.expanduser("~/.claude/codetogether-sync")


def _get_sync_offset(session_id: str) -> int:
    """读取上次同步的文件字节偏移量，不存在时返回 0。"""
    path = os.path.join(SYNC_STATE_DIR, f"{session_id}.offset")
    try:
        return int(open(path).read().strip())
    except Exception:
        return 0


def _save_sync_offset(session_id: str, offset: int) -> None:
    """持久化当前同步偏移量。"""
    os.makedirs(SYNC_STATE_DIR, exist_ok=True)
    open(os.path.join(SYNC_STATE_DIR, f"{session_id}.offset"), "w").write(str(offset))


def _extract_messages(path: str, start_offset: int = 0) -> tuple:
    """
    从 JSONL 文件提取对话消息（user 和 assistant 文本块）。

    start_offset 指定从哪个字节开始读，跳过已同步内容；
    返回 (messages, end_offset)，end_offset 为读完后的文件位置。
    工具调用结果（tool_result）和纯工具调用（tool_use）不计入对话。
    """
    messages = []
    with open(path, encoding="utf-8") as f:
        f.seek(start_offset)
        while True:
            line = f.readline()
            if not line:
                break
            try:
                record = json.loads(line)
            except Exception:
                continue
            rtype = record.get("type")
            if rtype != "assistant":
                continue
            content = record.get("message", {}).get("content", [])
            text_parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") in ("tool_use", "tool_result"):
                    continue
                if block.get("type") == "text" and block.get("text", "").strip():
                    text_parts.append(block["text"])
            if not text_parts:
                continue
            messages.append({
                "uuid": record.get("uuid", ""),
                "role": "assistant",
                "text": "\n".join(text_parts),
                "timestamp": record.get("timestamp", ""),
            })
        end_offset = f.tell()
    return messages, end_offset


def sync_messages(session_id: str, cwd: str) -> None:
    """
    读取 JSONL transcript 增量部分，将新的 assistant/user 消息同步到服务端消息表。

    通过字节偏移量记录上次同步位置，每次只处理新增内容，避免随对话增长重复发送。
    """
    path = _find_transcript(session_id, cwd)
    if not path:
        return

    start_offset = _get_sync_offset(session_id)

    try:
        messages, end_offset = _extract_messages(path, start_offset)
    except Exception:
        return

    if not messages:
        _save_sync_offset(session_id, end_offset)
        return

    _common.ensure_session(session_id, cwd=cwd)
    for msg in messages:
        ts = None
        if msg.get("timestamp"):
            try:
                dt = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))
                ts = dt.timestamp()
            except Exception:
                pass
        _common.post_chat_message(session_id, msg["text"], role=msg["role"], source_uuid=msg["uuid"], created_at=ts)

    _save_sync_offset(session_id, end_offset)

def main():
    """
    Stop hook 主入口。

    上报 stop 事件，同步 assistant 消息。
    若服务端有 pending 消息，返回 continue 指令让 Claude 继续处理；
    否则标记会话为 stopped。
    """
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return

    session_id = data.get("session_id") or ""
    cwd = data.get("cwd") or ""

    _common.post_event({
        "session_id": session_id,
        "type": "stop",
        "cwd": cwd,
    })

    if session_id:
        sync_messages(session_id, cwd)

    messages = _common.poll_messages(session_id) if session_id else []
    if messages:
        combined = "\n".join(m["content"] for m in messages)
        print(json.dumps({"continue": True, "message": combined}), flush=True)
        return

    _common.mark_stopped(session_id)


if __name__ == "__main__":
    main()
