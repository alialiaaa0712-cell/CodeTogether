"""hooks 共用的 HTTP 工具函数。"""
import json
import os
import subprocess
import urllib.request

SERVER = os.environ.get("CODETOGETHER_SERVER", "http://localhost:8000")
API_KEY = os.environ.get("CODETOGETHER_API_KEY", "")
TIMEOUT = 2


def _auth_headers() -> dict:
    """
    返回包含 Content-Type 和 Authorization 的请求头。

    返回值:
        dict：有 API_KEY 时包含 Bearer Token；无 key 时仅有 Content-Type。
    """
    if API_KEY:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    return {"Content-Type": "application/json"}


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
            headers=_auth_headers(),
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
            headers=_auth_headers(),
            method="GET",
        )
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        return json.loads(resp.read())
    except Exception:
        return []


def memory_search(query: str, session_id: str, limit: int = 3) -> list:
    """
    显式搜索记忆，按 session_id 让服务端自动解析项目范围。

    参数:
        query: 搜索关键词。
        session_id: 当前会话 ID。
        limit: 最多返回条数。

    返回值:
        命中的记忆列表；失败时返回空列表。
    """
    try:
        req = urllib.request.Request(
            f"{SERVER}/memory/search",
            data=json.dumps({
                "query": query,
                "session_id": session_id,
                "limit": limit,
            }).encode(),
            headers=_auth_headers(),
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        return json.loads(resp.read())
    except Exception:
        return []


def memory_feedback(memory_id: str, session_id: str, score: int, reason: str):
    """
    显式提交记忆反馈，失败时返回 None。

    参数:
        memory_id: 目标记忆 ID。
        session_id: 当前会话 ID。
        score: 反馈分值，只允许服务端定义的离散值。
        reason: 反馈原因。

    返回值:
        服务端返回的记忆对象；失败时返回 None。
    """
    try:
        req = urllib.request.Request(
            f"{SERVER}/memory/{memory_id}/feedback",
            data=json.dumps({
                "session_id": session_id,
                "score": score,
                "reason": reason,
            }).encode(),
            headers=_auth_headers(),
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        return json.loads(resp.read())
    except Exception:
        return None


def ensure_session(session_id: str, cwd: str = None, repo_url: str = None) -> None:
    """
    确保 session 存在，不存在时静默创建，避免写消息时因 session 缺失而 404。

    参数:
        session_id: 目标会话 ID
        cwd: 工作目录（可选）
        repo_url: git remote origin URL（可选）
    """
    try:
        payload: dict = {"id": session_id}
        if cwd:
            payload["cwd"] = cwd
        if repo_url:
            payload["repo_url"] = repo_url
        req = urllib.request.Request(
            f"{SERVER}/agents",
            data=json.dumps(payload).encode(),
            headers=_auth_headers(),
            method="POST",
        )
        urllib.request.urlopen(req, timeout=TIMEOUT)
    except Exception:
        pass


def post_chat_message(session_id: str, content: str, role: str = "user", source_uuid: str = None, created_at: float = None) -> None:
    """
    向服务端写入一条聊天消息，失败时静默跳过。source_uuid 用于去重。

    参数:
        session_id: 目标会话 ID
        content: 消息内容
        role: 消息角色，user 或 assistant
        source_uuid: JSONL 记录的 uuid，服务端用于幂等写入
        created_at: 消息的原始 Unix 时间戳（秒），为空时由服务端用当前时间
    """
    try:
        payload: dict = {"session_id": session_id, "content": content, "role": role}
        if source_uuid:
            payload["source_uuid"] = source_uuid
        if created_at is not None:
            payload["created_at"] = created_at
        req = urllib.request.Request(
            f"{SERVER}/chat",
            data=json.dumps(payload).encode(),
            headers=_auth_headers(),
            method="POST",
        )
        urllib.request.urlopen(req, timeout=TIMEOUT)
    except Exception:
        pass


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
            headers=_auth_headers(),
            method="PATCH",
        )
        urllib.request.urlopen(req, timeout=TIMEOUT)
    except Exception:
        pass


def get_repo_url(cwd: str) -> str:
    """
    获取指定目录的 git remote origin URL。

    参数:
        cwd: 工作目录路径。

    返回值:
        remote URL 字符串；非 git 目录或命令失败时返回空字符串。
    """
    if not cwd:
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=2,
        )
        return result.stdout.strip()
    except Exception:
        return ""