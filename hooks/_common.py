"""hooks 共用的 HTTP 工具函数。"""
import json
import os
import urllib.parse
import urllib.request

SERVER = os.environ.get("CODETOGETHER_SERVER", "http://localhost:8000")
TIMEOUT = 2


def get_session_id() -> str:
    """
    获取当前 agent 的会话 ID。

    优先从环境变量 CLAUDE_SESSION_ID 读取；
    回退到 unknown-<pid> 格式。
    """
    val = os.environ.get("CLAUDE_SESSION_ID", "")
    if val:
        return val
    return f"unknown-{os.getpid()}"


def post_event(payload: dict) -> None:
    """
    向服务器上报事件，失败时静默跳过。

    参数:
        payload: 事件数据，字段见 EventCreate schema
    """
    try:
        req = urllib.request.Request(
            f"{SERVER}/events",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=TIMEOUT)
    except Exception:
        pass


def poll_messages(session_id: str) -> list:
    """
    原子取走该会话的所有 pending 消息，失败时返回空列表。

    参数:
        session_id: 目标会话 ID

    返回值:
        list: MessageOut 字典列表
    """
    try:
        req = urllib.request.Request(
            f"{SERVER}/chat/{session_id}/poll",
            method="GET",
        )
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        return json.loads(resp.read())
    except Exception:
        return []


def search_memory(query: str, project_id: str = None) -> list:
    """
    搜索相关记忆条目，失败时返回空列表。

    参数:
        query: 搜索词（工具名 + 最近 assistant 消息）
        project_id: 限定项目范围（可选）

    返回值:
        list: MemoryOut 字典列表（最多 3 条）
    """
    try:
        params = {"q": query}
        if project_id:
            params["project_id"] = project_id
        url = f"{SERVER}/memory/search?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method="GET")
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        return json.loads(resp.read())
    except Exception:
        return []


def mark_stopped(session_id: str) -> None:
    """
    将指定会话状态标记为 stopped，失败时静默跳过。

    参数:
        session_id: 目标会话 ID
    """
    try:
        req = urllib.request.Request(
            f"{SERVER}/agents/{session_id}/status",
            data=json.dumps({"status": "stopped"}).encode(),
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )
        urllib.request.urlopen(req, timeout=TIMEOUT)
    except Exception:
        pass
