# CodeTogether 开发踩坑记录

## 1. MySQL 5.7 不支持 `ADD COLUMN IF NOT EXISTS`

**现象**：服务启动时执行 `ALTER TABLE events ADD COLUMN IF NOT EXISTS parent_session_id VARCHAR(36)` 报语法错误。

**原因**：`IF NOT EXISTS` 语法在 MySQL 8.0+ 才支持，5.7 不支持。

**修复**：用 `sqlalchemy.inspect(engine)` 先检查列是否存在，再决定是否 ALTER：
```python
_insp = inspect(engine)
if "parent_session_id" not in [c["name"] for c in _insp.get_columns("events")]:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE events ADD COLUMN parent_session_id VARCHAR(36)"))
        conn.commit()
```

---

## 2. IDE 注入消息污染 JSONL 同步

**现象**：数据库里出现大量 "Continue from where you left off."、"No response requested." 等用户消息，导致手机聊天界面充满噪音（一次性出现 333 条无效消息）。

**原因**：`stop.py` 在同步 JSONL 记录时，将 `user` 类型的记录也写入数据库。IDE 扩展（如 Kiro）会在每次交互时向 JSONL 注入这些控制消息。

**修复**：`stop.py` 只同步 `type == "assistant"` 的记录，跳过所有 `user` 类型。

---

## 3. 网络错误消息写入 JSONL

**现象**：手机聊天里出现 "API Error: Unable to connect to API (ENOTFOUND)" 之类的系统错误消息。

**原因**：Claude Code 在网络连接失败时，会将错误信息作为 assistant 消息写入 JSONL。

**修复**：`stop.py` 同步时过滤掉以 `"API Error:"` 开头的消息：
```python
if text.startswith("API Error:"):
    continue
```

---

## 4. 手机消息触发双重发送

**现象**：手机发一条消息，Claude 收到两次——一次来自 `claude -p --resume` 的唤醒参数，一次来自 `PreToolUse` hook 拉取的 pending 消息。

**原因**：`send_message` 在唤醒时把消息内容传给 `--resume`，同时该消息仍处于 `pending` 状态，`PreToolUse` hook 会再次拉取并注入。

**修复**：唤醒之前先将消息标记为 `delivered`，PreToolUse 就不会再看到它：
```python
if session.status == "stopped":
    msg.status = "delivered"
    db.commit()
    _wake_session(body.session_id, session.cwd or "", body.content)
```

---

## 5. 并发唤醒同一 Session

**现象**：手机快速连发多条消息，后台启动了多个 `claude -p --resume` 进程，导致 Claude 会话混乱、CPU 飙升。

**原因**：每次 `send_message` 发现 session stopped 就触发唤醒，没有互斥保护。

**修复**：用 `Set[str] + Lock` 保证同一 session 同时只有一个唤醒进程：
```python
_waking: Set[str] = set()
_waking_lock = threading.Lock()

def _wake_session(session_id, cwd, content):
    with _waking_lock:
        if session_id in _waking:
            return
        _waking.add(session_id)
    # 后台线程跑完后 discard
```

---

## 6. `send_message` 路由必须是 async

**现象**：`await manager.broadcast(...)` 在 sync 函数里报 `RuntimeError: coroutine was never awaited`。

**原因**：FastAPI 路由函数是同步的，无法直接 `await` 异步调用。

**修复**：将 `send_message` 改为 `async def`。

---

## 7. SQLite 多线程报错

**现象**：FastAPI + SQLite 时出现 `SQLite objects created in a thread can only be used in that same thread`。

**原因**：SQLite 默认不允许跨线程共享连接，FastAPI 在不同线程处理请求。

**修复**：创建 engine 时传入 `connect_args={"check_same_thread": False}`。

---

## 8. `DELETE` 接口返回 204 时不能调用 `.json()`

**现象**：前端删除操作后报 `SyntaxError: Unexpected end of JSON input`。

**原因**：HTTP 204 No Content 响应体为空，`response.json()` 会抛异常。

**修复**：`fetchJson` 工具函数先检查状态码再解析：
```javascript
if (res.status === 204) return null;
return res.json();
```

---

## 9. stop hook 的 continue 循环

**现象**：stop hook 返回 `{"continue": true}` 唤醒 Claude 后，Claude 回复完又触发 stop hook，如果数据库里还有 pending 消息就会再次 continue，形成无限循环。

**根因**：`poll_messages` 是原子操作（`WITH FOR UPDATE` + 立即标记 delivered），所以同一条消息不会被重复消费。只要消息在唤醒前标记 delivered，循环就自然终止。

**结论**：无需额外修改，设计上已经安全。

---

## 10. `claude -p --resume` 依赖完整 JSONL 历史

**现象**：唤醒后 Claude 响应很慢，会话越老越慢。

**原因**：`--resume` 会重新读取整个 `~/.claude/projects/{slug}/{id}.jsonl` 文件后再继续，JSONL 越长加载越慢。

**教训**：长会话的唤醒延迟是结构性问题，不是 bug；可以在手机端加"响应中..."提示来缓解等待体验。

---

## 11. Pydantic V1 → V2 迁移无明显报错

**现象**：接口返回的对象字段全部缺失，但没有任何异常。

**原因**：用了 V1 的 `class Config: orm_mode = True` 写法，Pydantic V2 不报错但也不生效，导致 ORM 对象无法序列化。

**修复**：改为 V2 写法：
```python
model_config = ConfigDict(from_attributes=True)
```

---

## 12. 记忆自动提炼方案被废弃

**现象**：最初设计在会话结束时调用 Claude API 自动分析对话、提炼记忆条目，实际跑起来发现 API 调用慢、成本高、质量不稳定。

**教训**：自动提炼听起来很智能，但"人工审核"的成本其实很低——pre_tool.py 检测到有价值内容就 flag，手机端快速判断即可。能让人参与的环节不一定要全自动。

---

## 13. WebSocket manager 不能用模块级变量跨 router 共享

**现象**：router 里调用模块级 `manager.broadcast(...)` 时，广播出去但客户端收不到——实际上拿到的是一个空的 manager 实例。

**原因**：FastAPI 的 router 和 `main.py` 各自 import，模块级变量在不同模块里是不同对象。

**修复**：把 manager 挂在 `app.state` 上，router 里通过 `request.app.state.ws_manager` 取：
```python
# main.py
app.state.ws_manager = manager

# router 里
manager = request.app.state.ws_manager
await manager.broadcast(...)
```

---

## 14. 服务未重启导致调试迷惑

**现象**：改了代码，但行为没有变化，反复排查逻辑也没发现问题。

**原因**：`uvicorn` 在没有 `--reload` 的情况下不会热重载，改了代码要手动重启服务。

**教训**：开发时始终加 `--reload`；部署时确认进程已重启后再验证行为。
