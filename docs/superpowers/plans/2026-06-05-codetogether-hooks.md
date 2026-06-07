# CodeTogether Hooks 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现三个 Claude Code Hooks（PreToolUse、PostToolUse、Stop），连接 PC 端 Agent 与 CodeTogether 服务器，实现事件上报、聊天消息注入和知识提炼触发。

**Architecture:** 每个 hook 是独立的 Python 脚本，从 stdin 读取 Claude Code 的 JSON 事件，调用 `_common.py` 中的共用 HTTP 工具函数与服务器通信；所有 HTTP 调用失败时静默跳过，确保 hook 崩溃不影响 Agent 运行。PreToolUse hook 额外从服务器拉取 pending 消息和相关记忆，print 到 stdout 注入给 Claude。Stop hook 调用 `PATCH /agents/{id}/status` 将会话标记为 stopped，服务器端触发知识提炼。

**Tech Stack:** Python 3.9+（stdlib only：json, os, sys, urllib.request）；测试使用 pytest + unittest.mock

---

## 项目上下文

服务器已实现（Plan 1/4），关键端点：

| 端点 | 说明 |
|------|------|
| `POST /events` | 上报工具事件，body: `{session_id, type, tool_name, input, output, duration_ms}` |
| `GET /chat/{session_id}/poll` | 原子取走 pending 消息，返回 `[{id, content, ...}]` |
| `GET /memory/search?q=<query>&project_id=<id>` | 搜索记忆，返回最多 3 条 `[{title, content, tags}]` |
| `PATCH /agents/{session_id}/status` | 更新状态，body: `{"status": "stopped"}` |

服务器默认地址由环境变量 `CODETOGETHER_SERVER`（默认 `http://localhost:8000`）控制。

Claude Code hook 的 stdin JSON 格式（以 PreToolUse 为例）：
```json
{
  "session_id": "abc123",
  "agent_id": "hex-child-id",
  "tool_name": "Bash",
  "tool_input": {"command": "ls"},
  "cwd": "/Users/user/project"
}
```
- `session_id`：当前会话 UUID（主 agent 与子 agent 均有）
- `agent_id`：仅子 agent 有值（hex 格式），主 agent 无此字段
- 主 agent：用 `session_id` 作为自身标识
- 子 agent：用 `agent_id` 作为自身标识，`session_id`（父的 UUID）作为 `parent_session_id`

WatchingYou 已有参考实现：
- `/Users/qinepan/Desktop/test/WatchingYou/hooks/_common.py`
- `/Users/qinepan/Desktop/test/WatchingYou/hooks/pre_tool.py`
- `/Users/qinepan/Desktop/test/WatchingYou/hooks/post_tool.py`
- `/Users/qinepan/Desktop/test/WatchingYou/hooks/stop.py`

## 文件结构

```
CodeTogether/
├── hooks/
│   ├── _common.py        # 共用 HTTP 工具：get_session_id, post_event, poll_messages, search_memory, mark_stopped
│   ├── pre_tool.py       # PreToolUse hook：上报事件 + 拉取消息 + 注入记忆
│   ├── post_tool.py      # PostToolUse hook：上报工具结果
│   └── stop.py           # Stop hook：标记会话结束
└── tests/
    └── test_hooks.py     # 所有 hook 的单元测试
```

---

### Task 1: `_common.py` — 共用工具函数

**Files:**
- Create: `hooks/_common.py`
- Test: `tests/test_hooks.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_hooks.py`：

```python
import sys
import os
import json
import importlib
import unittest.mock as mock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    monkeypatch.delenv("CODETOGETHER_SERVER", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)


def import_common():
    import hooks._common as m
    importlib.reload(m)
    return m


# --- get_session_id ---

def test_get_session_id_from_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess-abc")
    m = import_common()
    assert m.get_session_id() == "sess-abc"


def test_get_session_id_fallback():
    m = import_common()
    result = m.get_session_id()
    assert result.startswith("unknown-")


# --- post_event ---

def test_post_event_calls_server(monkeypatch):
    m = import_common()
    with mock.patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = mock.Mock(return_value=False)
        m.post_event({"session_id": "s1", "type": "pre_tool"})
    mock_open.assert_called_once()
    req = mock_open.call_args[0][0]
    assert "/events" in req.full_url
    body = json.loads(req.data)
    assert body["session_id"] == "s1"


def test_post_event_silent_on_error(monkeypatch):
    m = import_common()
    with mock.patch("urllib.request.urlopen", side_effect=Exception("conn refused")):
        m.post_event({"session_id": "s1", "type": "pre_tool"})  # 不抛异常


# --- poll_messages ---

def test_poll_messages_returns_list(monkeypatch):
    m = import_common()
    payload = [{"id": "m1", "content": "hello", "status": "pending"}]
    response = mock.MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    with mock.patch("urllib.request.urlopen", return_value=response) as mock_open:
        result = m.poll_messages("sess-1")
    assert result == payload
    req = mock_open.call_args[0][0]
    assert "/chat/sess-1/poll" in req.full_url


def test_poll_messages_empty_on_error():
    m = import_common()
    with mock.patch("urllib.request.urlopen", side_effect=Exception("timeout")):
        result = m.poll_messages("sess-1")
    assert result == []


# --- search_memory ---

def test_search_memory_returns_list(monkeypatch):
    m = import_common()
    payload = [{"title": "T", "content": "C", "tags": "t"}]
    response = mock.MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    with mock.patch("urllib.request.urlopen", return_value=response) as mock_open:
        result = m.search_memory("pytest", project_id="proj-1")
    assert result == payload
    req = mock_open.call_args[0][0]
    assert "memory/search" in req.full_url
    assert "pytest" in req.full_url


def test_search_memory_empty_on_error():
    m = import_common()
    with mock.patch("urllib.request.urlopen", side_effect=Exception("timeout")):
        result = m.search_memory("query")
    assert result == []


# --- mark_stopped ---

def test_mark_stopped_calls_patch(monkeypatch):
    m = import_common()
    with mock.patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = mock.Mock(return_value=False)
        m.mark_stopped("sess-1")
    req = mock_open.call_args[0][0]
    assert "/agents/sess-1/status" in req.full_url
    assert req.method == "PATCH"
    body = json.loads(req.data)
    assert body["status"] == "stopped"


def test_mark_stopped_silent_on_error():
    m = import_common()
    with mock.patch("urllib.request.urlopen", side_effect=Exception("conn refused")):
        m.mark_stopped("sess-1")  # 不抛异常
```

- [ ] **Step 2: 运行确认测试失败**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
python -m pytest tests/test_hooks.py -v 2>&1 | head -30
```

预期：`ModuleNotFoundError: No module named 'hooks'`

- [ ] **Step 3: 创建 `hooks/__init__.py`（空文件）**

```bash
touch hooks/__init__.py
```

- [ ] **Step 4: 实现 `hooks/_common.py`**

```python
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
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
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
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
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
```

- [ ] **Step 5: 运行确认测试通过**

```bash
python -m pytest tests/test_hooks.py -v -k "common or get_session or post_event or poll_messages or search_memory or mark_stopped"
```

预期：全部通过

- [ ] **Step 6: 提交**

```bash
git add hooks/__init__.py hooks/_common.py tests/test_hooks.py
git commit -m "feat: hooks _common.py — get_session_id, post_event, poll_messages, search_memory, mark_stopped"
```

---

### Task 2: `post_tool.py` — PostToolUse Hook

**Files:**
- Create: `hooks/post_tool.py`
- Modify: `tests/test_hooks.py` (append tests)

PostToolUse 从 stdin 读取 Claude Code 事件 JSON，解析工具输出，上报 `POST /events`。

Claude Code PostToolUse stdin 格式：
```json
{
  "session_id": "abc123",
  "agent_id": "hex-child-id",
  "tool_name": "Bash",
  "tool_input": {"command": "ls"},
  "tool_response": {"stdout": "file.py\n", "stderr": "", "interrupted": false},
  "cwd": "/project"
}
```
`tool_response` 可能是 dict（含 stdout/stderr/interrupted/isImage）或字符串。

- [ ] **Step 1: 在 `tests/test_hooks.py` 末尾追加测试**

```python
# ============================================================
# post_tool.py
# ============================================================

def import_post_tool():
    import hooks.post_tool as m
    importlib.reload(m)
    return m


def run_hook(module, stdin_data: dict):
    """辅助：将 stdin_data 注入 hook 的 main() 并捕获 post_event 调用。"""
    with mock.patch("hooks._common.post_event") as mock_post:
        with mock.patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = json.dumps(stdin_data)
            module.main()
    return mock_post


def test_post_tool_bash_output():
    m = import_post_tool()
    mock_post = run_hook(m, {
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "tool_response": {"stdout": "file.py\n", "stderr": "", "interrupted": False},
        "cwd": "/project",
    })
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][0]
    assert payload["session_id"] == "s1"
    assert payload["type"] == "post_tool"
    assert payload["tool_name"] == "Bash"
    assert "file.py" in payload["output"]
    assert payload["parent_session_id"] is None


def test_post_tool_with_stderr():
    m = import_post_tool()
    mock_post = run_hook(m, {
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": "bad"},
        "tool_response": {"stdout": "", "stderr": "error msg", "interrupted": False},
        "cwd": "/project",
    })
    payload = mock_post.call_args[0][0]
    assert "[stderr]" in payload["output"]


def test_post_tool_child_agent():
    m = import_post_tool()
    mock_post = run_hook(m, {
        "session_id": "parent-uuid",
        "agent_id": "childabc",
        "tool_name": "Read",
        "tool_input": {"file_path": "/x.py"},
        "tool_response": "content",
        "cwd": "/project",
    })
    payload = mock_post.call_args[0][0]
    assert payload["session_id"] == "childabc"
    assert payload["parent_session_id"] == "parent-uuid"


def test_post_tool_agent_tool_serializes_response():
    m = import_post_tool()
    mock_post = run_hook(m, {
        "session_id": "s1",
        "tool_name": "Agent",
        "tool_input": {"description": "do X"},
        "tool_response": {"result": "done"},
        "cwd": "/project",
    })
    payload = mock_post.call_args[0][0]
    assert payload["tool_name"] == "Agent"
    assert '"result"' in payload["output"]


def test_post_tool_invalid_json_no_crash():
    m = import_post_tool()
    with mock.patch("hooks._common.post_event") as mock_post:
        with mock.patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "not json"
            m.main()
    mock_post.assert_not_called()
```

- [ ] **Step 2: 运行确认测试失败**

```bash
python -m pytest tests/test_hooks.py -v -k "post_tool"
```

预期：`ModuleNotFoundError: No module named 'hooks.post_tool'`

- [ ] **Step 3: 实现 `hooks/post_tool.py`**

```python
#!/usr/bin/env python3
"""PostToolUse hook：上报工具调用结果到 CodeTogether 服务器。"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from _common import post_event


def main():
    """
    PostToolUse hook 主入口。

    从 stdin 读取事件 JSON，解析工具响应，上报到服务器。
    子 agent 用自身 agent_id 标识，父 session_id 作为 parent_session_id。
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

    tool_name = data.get("tool_name")
    tr = data.get("tool_response")

    if tool_name == "Agent":
        output = json.dumps(tr, ensure_ascii=False) if tr is not None else None
    elif isinstance(tr, dict):
        parts = []
        if tr.get("stdout"):
            parts.append(tr["stdout"])
        if tr.get("stderr"):
            parts.append("[stderr] " + tr["stderr"])
        if tr.get("interrupted"):
            parts.append("[interrupted]")
        if tr.get("isImage"):
            parts.append("[image output]")
        output = "\n".join(parts) if parts else None
    else:
        output = tr

    post_event({
        "session_id": agent_session_id,
        "type": "post_tool",
        "tool_name": tool_name,
        "input": data.get("tool_input"),
        "output": output,
        "cwd": data.get("cwd"),
        "parent_session_id": parent_session_id,
    })


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认测试通过**

```bash
python -m pytest tests/test_hooks.py -v -k "post_tool"
```

预期：5 个测试全部通过

- [ ] **Step 5: 提交**

```bash
git add hooks/post_tool.py tests/test_hooks.py
git commit -m "feat: hooks post_tool.py — PostToolUse 事件上报"
```

---

### Task 3: `stop.py` — Stop Hook

**Files:**
- Create: `hooks/stop.py`
- Modify: `tests/test_hooks.py` (append tests)

Stop hook 从 stdin 读取 Claude Code 停止事件，上报 stop 事件，并将会话标记为 stopped（服务器端触发知识提炼）。

Claude Code Stop stdin 格式：
```json
{
  "session_id": "abc123",
  "cwd": "/project"
}
```

- [ ] **Step 1: 在 `tests/test_hooks.py` 末尾追加测试**

```python
# ============================================================
# stop.py
# ============================================================

def import_stop():
    import hooks.stop as m
    importlib.reload(m)
    return m


def test_stop_posts_event_and_marks_stopped():
    m = import_stop()
    with mock.patch("hooks._common.post_event") as mock_post, \
         mock.patch("hooks._common.mark_stopped") as mock_mark, \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "sess-99",
            "cwd": "/project",
        })
        m.main()
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][0]
    assert payload["session_id"] == "sess-99"
    assert payload["type"] == "stop"
    assert payload["cwd"] == "/project"
    mock_mark.assert_called_once_with("sess-99")


def test_stop_invalid_json_no_crash():
    m = import_stop()
    with mock.patch("hooks._common.post_event") as mock_post, \
         mock.patch("hooks._common.mark_stopped") as mock_mark, \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = "bad json"
        m.main()
    mock_post.assert_not_called()
    mock_mark.assert_not_called()
```

- [ ] **Step 2: 运行确认测试失败**

```bash
python -m pytest tests/test_hooks.py -v -k "stop"
```

预期：`ModuleNotFoundError: No module named 'hooks.stop'`

- [ ] **Step 3: 实现 `hooks/stop.py`**

```python
#!/usr/bin/env python3
"""Stop hook：上报会话停止事件，触发服务器知识提炼。"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from _common import post_event, mark_stopped


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
    post_event({
        "session_id": session_id,
        "type": "stop",
        "cwd": data.get("cwd"),
    })
    mark_stopped(session_id)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认测试通过**

```bash
python -m pytest tests/test_hooks.py -v -k "stop"
```

预期：2 个测试全部通过

- [ ] **Step 5: 提交**

```bash
git add hooks/stop.py tests/test_hooks.py
git commit -m "feat: hooks stop.py — Stop 事件上报 + mark_stopped"
```

---

### Task 4: `pre_tool.py` — PreToolUse Hook（消息注入 + 记忆检索）

**Files:**
- Create: `hooks/pre_tool.py`
- Modify: `tests/test_hooks.py` (append tests)

PreToolUse hook：
1. 上报 `pre_tool` 事件
2. 拉取 `GET /chat/{session_id}/poll` 的 pending 消息 → print 给 Claude
3. 搜索相关记忆（以 `tool_name` 作为查询词，用 `cwd` 推断 project_id）→ print 给 Claude

记忆检索查询词：`tool_name`（已足够精确，避免过多上下文干扰搜索质量）。

project_id 推断规则：Claude Code 不在 hook 数据中提供 project_id，用 `cwd` 的最后一段路径作为 project_id（近似匹配，与服务器存储的 project.name 相关联）。若 cwd 为空则 project_id 为 None，服务器搜索不限项目。

print 格式：
```
[CodeTogether 消息]: <content>
[CodeTogether 记忆]: <title> — <content>
```

- [ ] **Step 1: 在 `tests/test_hooks.py` 末尾追加测试**

```python
# ============================================================
# pre_tool.py
# ============================================================

def import_pre_tool():
    import hooks.pre_tool as m
    importlib.reload(m)
    return m


def test_pre_tool_posts_event():
    m = import_pre_tool()
    with mock.patch("hooks._common.post_event") as mock_post, \
         mock.patch("hooks._common.poll_messages", return_value=[]), \
         mock.patch("hooks._common.search_memory", return_value=[]), \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "cwd": "/Users/user/myproject",
        })
        m.main()
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][0]
    assert payload["session_id"] == "s1"
    assert payload["type"] == "pre_tool"
    assert payload["tool_name"] == "Bash"


def test_pre_tool_prints_messages(capsys):
    m = import_pre_tool()
    messages = [{"content": "请帮我优化这段代码"}, {"content": "记得加测试"}]
    with mock.patch("hooks._common.post_event"), \
         mock.patch("hooks._common.poll_messages", return_value=messages), \
         mock.patch("hooks._common.search_memory", return_value=[]), \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {},
            "cwd": "/project",
        })
        m.main()
    out = capsys.readouterr().out
    assert "请帮我优化这段代码" in out
    assert "记得加测试" in out
    assert "[CodeTogether 消息]" in out


def test_pre_tool_prints_memories(capsys):
    m = import_pre_tool()
    memories = [{"title": "Bash 最佳实践", "content": "总是用 set -e"}]
    with mock.patch("hooks._common.post_event"), \
         mock.patch("hooks._common.poll_messages", return_value=[]), \
         mock.patch("hooks._common.search_memory", return_value=memories), \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {},
            "cwd": "/project",
        })
        m.main()
    out = capsys.readouterr().out
    assert "Bash 最佳实践" in out
    assert "总是用 set -e" in out
    assert "[CodeTogether 记忆]" in out


def test_pre_tool_search_uses_tool_name_as_query():
    m = import_pre_tool()
    with mock.patch("hooks._common.post_event"), \
         mock.patch("hooks._common.poll_messages", return_value=[]), \
         mock.patch("hooks._common.search_memory", return_value=[]) as mock_search, \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "s1",
            "tool_name": "Edit",
            "tool_input": {},
            "cwd": "/Users/user/myproject",
        })
        m.main()
    mock_search.assert_called_once()
    call_kwargs = mock_search.call_args
    query = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1]["query"]
    assert "Edit" in query


def test_pre_tool_cwd_infers_project_id():
    m = import_pre_tool()
    with mock.patch("hooks._common.post_event"), \
         mock.patch("hooks._common.poll_messages", return_value=[]), \
         mock.patch("hooks._common.search_memory", return_value=[]) as mock_search, \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": {},
            "cwd": "/Users/user/myproject",
        })
        m.main()
    call_kwargs = mock_search.call_args
    project_id = call_kwargs[1].get("project_id") or (call_kwargs[0][1] if len(call_kwargs[0]) > 1 else None)
    assert project_id == "myproject"


def test_pre_tool_child_agent_parent_session():
    m = import_pre_tool()
    with mock.patch("hooks._common.post_event") as mock_post, \
         mock.patch("hooks._common.poll_messages", return_value=[]), \
         mock.patch("hooks._common.search_memory", return_value=[]), \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = json.dumps({
            "session_id": "parent-uuid",
            "agent_id": "childabc",
            "tool_name": "Bash",
            "tool_input": {},
            "cwd": "/project",
        })
        m.main()
    payload = mock_post.call_args[0][0]
    assert payload["session_id"] == "childabc"
    assert payload["parent_session_id"] == "parent-uuid"


def test_pre_tool_invalid_json_no_crash():
    m = import_pre_tool()
    with mock.patch("hooks._common.post_event") as mock_post, \
         mock.patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = "not json"
        m.main()
    mock_post.assert_not_called()
```

- [ ] **Step 2: 运行确认测试失败**

```bash
python -m pytest tests/test_hooks.py -v -k "pre_tool"
```

预期：`ModuleNotFoundError: No module named 'hooks.pre_tool'`

- [ ] **Step 3: 实现 `hooks/pre_tool.py`**

```python
#!/usr/bin/env python3
"""PreToolUse hook：上报事件，并将 pending 消息和相关记忆注入给 Claude。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _common import post_event, poll_messages, search_memory


def _project_id_from_cwd(cwd: str) -> "str | None":
    """
    用 cwd 最后一段路径作为 project_id 近似值。

    服务器存储 project.name 与目录名通常一致；若 cwd 为空则返回 None，
    服务器搜索不限项目范围。
    """
    if not cwd:
        return None
    return os.path.basename(cwd.rstrip("/"))


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

    post_event({
        "session_id": agent_session_id,
        "type": "pre_tool",
        "tool_name": tool_name,
        "input": data.get("tool_input"),
        "cwd": cwd,
        "parent_session_id": parent_session_id,
    })

    for msg in poll_messages(agent_session_id):
        print(f"\n[CodeTogether 消息]: {msg['content']}\n", flush=True)

    project_id = _project_id_from_cwd(cwd)
    for mem in search_memory(tool_name, project_id=project_id):
        print(f"\n[CodeTogether 记忆]: {mem['title']} — {mem['content']}\n", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认测试通过**

```bash
python -m pytest tests/test_hooks.py -v -k "pre_tool"
```

预期：7 个测试全部通过

- [ ] **Step 5: 提交**

```bash
git add hooks/pre_tool.py tests/test_hooks.py
git commit -m "feat: hooks pre_tool.py — 消息注入 + 记忆检索"
```

---

### Task 5: 全量测试 + README 安装说明

**Files:**
- Modify: `README.md`（若不存在则创建）

- [ ] **Step 1: 运行全量测试**

```bash
cd /Users/qinepan/Desktop/search/CodeTogether
python -m pytest tests/test_hooks.py -v
```

预期：所有测试通过（约 20 个）

- [ ] **Step 2: 同时运行服务器测试确认无回归**

```bash
python -m pytest tests/ -v --ignore=tests/test_hooks.py 2>&1 | tail -5
```

预期：原有 20 个服务器测试全部通过

- [ ] **Step 3: 确认 hooks 文件列表**

```bash
ls hooks/
```

预期：`__init__.py  _common.py  pre_tool.py  post_tool.py  stop.py`

- [ ] **Step 4: 更新 README.md（Hooks 安装说明）**

在 `README.md` 中添加 Hooks 安装说明章节。若文件不存在，以如下内容创建：

```markdown
# CodeTogether

Claude Code Agent 团队协作平台。

## Hooks 安装

将以下内容添加到 `~/.claude/settings.json` 的 `hooks` 字段，或在项目目录创建 `.claude/settings.json`：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python /path/to/CodeTogether/hooks/pre_tool.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python /path/to/CodeTogether/hooks/post_tool.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python /path/to/CodeTogether/hooks/stop.py"
          }
        ]
      }
    ]
  }
}
```

将 `/path/to/CodeTogether` 替换为实际路径（如 `/Users/qinepan/Desktop/search/CodeTogether`）。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CODETOGETHER_SERVER` | `http://localhost:8000` | CodeTogether 服务器地址 |

## 服务器启动

```bash
pip install -r requirements.txt
uvicorn server.main:app --reload
```
```

- [ ] **Step 5: 提交**

```bash
git add README.md
git commit -m "docs: hooks 安装说明"
```
