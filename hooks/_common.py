"""hooks 共用的 HTTP 工具函数。"""
import json
import os
import subprocess
import time
import urllib.error
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


# 重试间隔序列（秒）：第1次失败后等 0.5s，第2次失败后等 1.0s；共最多 3 次尝试
_RETRY_DELAYS = (0.5, 1.0)


def _http_request_with_retry(req: urllib.request.Request) -> None:
    """
    带指数退避重试的 HTTP 请求，专用于写操作（POST/PATCH）。

    网络错误或 5xx 时按 _RETRY_DELAYS 间隔重试；4xx 时立即放弃（不重试）。
    所有重试耗尽后静默跳过，不向上层抛出异常。

    参数:
        req: 已构造好的 urllib.request.Request 对象。

    返回值:
        无。
    """
    for i, delay in enumerate(_RETRY_DELAYS):
        try:
            urllib.request.urlopen(req, timeout=TIMEOUT)
            return
        except urllib.error.HTTPError as exc:
            # 4xx 客户端错误不重试，直接返回
            if exc.code < 500:
                return
            # 5xx 服务端错误：等待后重试
            time.sleep(delay)
        except Exception:
            # 网络错误等：等待后重试
            time.sleep(delay)
    # 最后一次尝试（无等待）
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT)
    except Exception:
        pass


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
        _http_request_with_retry(req)
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


def ensure_session(session_id: str, cwd: str = None, repo_url: str = None, parent_id: str = None) -> None:
    """
    确保 session 存在，不存在时静默创建，避免写消息时因 session 缺失而 404。

    参数:
        session_id: 目标会话 ID
        cwd: 工作目录（可选）
        repo_url: git remote origin URL（可选）
        parent_id: 父会话 ID（可选，子 Agent 时传入）
    """
    try:
        payload: dict = {"id": session_id}
        if cwd:
            payload["cwd"] = cwd
        if repo_url:
            payload["repo_url"] = repo_url
        if parent_id:
            payload["parent_id"] = parent_id
        req = urllib.request.Request(
            f"{SERVER}/agents",
            data=json.dumps(payload).encode(),
            headers=_auth_headers(),
            method="POST",
        )
        _http_request_with_retry(req)
    except Exception:
        pass


def create_memory(title: str, content: str, session_id: str, tags: str = None) -> dict:
    """
    由模型主动创建一条短期记忆，服务端自动关联项目。

    参数:
        title: 记忆标题，简短描述核心结论。
        content: 记忆正文，描述约束/规则/坑点及其原因。
        session_id: 当前会话 ID，用于服务端解析所属项目。
        tags: 可选的逗号分隔标签。

    返回值:
        服务端返回的记忆对象；失败时返回 None。
    """
    try:
        payload: dict = {
            "title": title,
            "content": content,
            "source_session_id": session_id,
        }
        if tags:
            payload["tags"] = tags
        req = urllib.request.Request(
            f"{SERVER}/memory",
            data=json.dumps(payload).encode(),
            headers=_auth_headers(),
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        return json.loads(resp.read())
    except Exception:
        return None


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
        _http_request_with_retry(req)
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
        _http_request_with_retry(req)
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