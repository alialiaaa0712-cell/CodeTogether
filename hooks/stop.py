#!/usr/bin/env python3
"""Stop hook：上报会话停止事件，并从 JSONL transcript 同步 assistant 消息到服务端。"""
import json
import os
import sys
import glob
import re
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


def _get_session_start_time(path: str) -> float:
    """
    读取 JSONL 第一条记录的 timestamp，作为 session 启动时间。

    用于过滤 user 消息：只同步 session 启动之后产生的消息，避免历史消息重复写入。
    读取失败时返回 0.0（相当于不过滤）。
    """
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                ts = record.get("timestamp", "")
                if ts:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    return dt.timestamp()
    except Exception:
        pass
    return 0.0


def _is_real_user_text(text: str) -> bool:
    """
    判断 user text 是否属于真实用户输入，而不是 IDE / Skill / 中断噪音。

    参数:
        text: 归一化后的文本内容。

    返回值:
        True 表示应同步到手机端；False 表示属于系统注入或噪音。
    """
    if not text:
        return False
    if text in {"Continue from where you left off.", "No response requested.", "[Request interrupted by user]"}:
        return False
    if text.startswith("API Error:"):
        return False
    if text.startswith("Base directory for this skill:"):
        return False
    if text.startswith("<EXTREMELY_IMPORTANT>"):
        return False
    if text.startswith("## Overview\n") or text.startswith("## The Process\n"):
        return False
    if re.match(r"^name: .*\ndescription: .*", text):
        return False
    return True


def _is_real_assistant_text(text: str) -> bool:
    """
    判断 assistant text 是否属于应展示给手机端的真实输出。

    参数:
        text: 归一化后的文本内容。

    返回值:
        True 表示应同步；False 表示属于控制占位或噪音。
    """
    if not text:
        return False
    if text == "No response requested.":
        return False
    return True



def _extract_messages(path: str, start_offset: int = 0, user_min_ts: float = 0.0) -> tuple:
    """
    从 JSONL 文件提取对话消息（仅 text block）。

    规则：
    1. 只处理 `type in (user, assistant)` 的记录
    2. 只提取 `message.content[*].type == text` 的 block
    3. assistant：保留所有真实 text，由 hook 触发更频繁的增量同步
    4. user：额外过滤 IDE/Skill/中断噪音

    参数:
        path: transcript 文件路径。
        start_offset: 起始字节偏移。
        user_min_ts: user 消息最早时间戳阈值（Unix 秒）。

    返回值:
        tuple[list[dict], int]: 提取出的消息列表与新的文件偏移量。
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
            if rtype not in ("assistant", "user"):
                continue
            content = record.get("message", {}).get("content", [])
            text_parts = []
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "text":
                    continue
                text = re.sub(r"<ide_[^>]+>.*?</ide_[^>]+>", "", (block.get("text") or ""), flags=re.DOTALL).strip()
                if text:
                    text_parts.append(text)
            if not text_parts:
                continue
            text = "\n".join(text_parts)
            if rtype == "user":
                if not _is_real_user_text(text):
                    continue
                if user_min_ts > 0:
                    ts_str = record.get("timestamp", "")
                    try:
                        rec_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                    except Exception:
                        rec_ts = 0.0
                    if rec_ts < user_min_ts:
                        continue
            else:
                if not _is_real_assistant_text(text):
                    continue
            role = "assistant" if rtype == "assistant" else "user"
            messages.append({
                "uuid": record.get("uuid", ""),
                "role": role,
                "text": text,
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
    user_min_ts = _get_session_start_time(path) if start_offset == 0 else 0.0

    try:
        messages, end_offset = _extract_messages(path, start_offset, user_min_ts)
    except Exception:
        return

    if not messages:
        _save_sync_offset(session_id, end_offset)
        return

    repo_url = _common.get_repo_url(cwd)
    _common.ensure_session(session_id, cwd=cwd, repo_url=repo_url)
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
