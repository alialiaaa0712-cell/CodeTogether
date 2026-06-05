# CodeTogether 设计文档

**日期**：2026-06-05
**状态**：已确认

---

## 项目定位

CodeTogether 是一个面向中大型团队的 Claude Code Agent 协作平台。核心价值：**团队共享 Agent 配置、项目记忆、运行记录，让每个成员的 AI 编程受益于团队积累。**

客户端形态：
- VS Code 插件（开发主力）
- 手机 Web App（移动查看 + 实时干预）
- Hooks（Agent 与服务器的桥梁）

与 WatchingYou 的关系：**替代**。复用 WatchingYou 的 hook 机制和 WebSocket 模式，重写存储层和功能层。

---

## 整体架构

```
手机 (Web App)                    PC (VS Code 插件)
    │  聊天/查看状态/记忆/配置          │  Claude Code Agent 运行
    │                                 │
    └──────────── 服务器 ──────────────┘
                 FastAPI + WebSocket + MySQL
```

**数据流（手机 → Agent）**

```
手机发消息 → POST /chat/{session_id}
          → 服务器存为 pending message
          → PC PreToolUse hook 轮询取走
          → print 给 Claude → Claude 处理
          → 后续工具调用/结果 → PostToolUse hook 上报
          → 服务器 WebSocket 广播 → 手机实时收到进度
```

**数据流（知识沉淀）**

```
Agent 结束 → Stop hook → POST /sessions/summary
          → 服务器调 Claude API 提炼知识条目
          → 存 MySQL (status=pending)
          → 推送通知到手机/VS Code
          → 人工审核 → 激活 → 后续 Agent 检索使用
```

---

## 核心模块

### 服务器模块

| 模块 | 职责 |
|------|------|
| `events` | Agent 工具调用事件接收、存储、WebSocket 广播 |
| `chat` | 手机消息存储、PC hook 轮询取走（复用 WatchingYou injection 机制） |
| `memory` | 知识条目 CRUD、Claude API 提炼任务队列、pending/active 状态管理 |
| `config` | CLAUDE.md、settings.json、hooks 版本存储、diff、分发 |
| `agents` | Agent 状态、父子关系、会话元数据 |

### PC 端

| 模块 | 职责 |
|------|------|
| `PreToolUse hook` | 拉取 pending chat 消息 + 检索相关记忆 → print 给 Claude |
| `Stop hook` | 上报会话摘要 → 触发服务器知识提炼 |
| `PostToolUse hook` | 上报工具结果 → 服务器广播到手机 |
| `VS Code 插件` | WebView 展示记忆审核、配置同步、Agent 状态 |

### 手机 Web App

| 页面 | 功能 |
|------|------|
| 聊天页 | 发消息给指定 session 的 Agent，实时看回复进度 |
| 状态页 | 所有 Agent 运行状态、工具调用时间线 |
| 记忆页 | 浏览/审核知识条目（pending → active） |
| 配置页 | 查看当前配置版本、订阅更新 |

---

## 数据模型

```sql
-- Agent 会话
sessions(id, project_id, parent_id, status, started_at, ended_at)

-- 工具调用事件
events(id, session_id, tool_name, input, output, duration_ms, created_at)

-- 聊天消息（手机 → Agent）
messages(id, session_id, content, status[pending/delivered], created_at)

-- 知识条目
memories(id, project_id, title, content, tags, status[pending/active/rejected],
         source_session_id, created_at, activated_at)

-- 配置版本
configs(id, project_id, type[claude_md/settings/hooks], content, version,
        author, created_at)

-- 项目
projects(id, name, repo_url, created_at)

-- 团队成员
members(id, project_id, user_id, role[owner/member])
```

**记忆检索策略**：MySQL FULLTEXT 全文搜索。PreToolUse hook 取当前工具名 + 最近一条 Assistant 消息作为查询词，匹配 `memories.tags` 和 `memories.content`，返回最多 3 条，总字数控制在 500 字以内。

**手机聊天延迟说明**：手机发出的消息不会立即送达 Agent，而是在 Agent 下一次工具调用时由 PreToolUse hook 取走。Agent 空闲时消息可能等待较长时间，这是 hook 机制的固有限制。

---

## 技术栈

| 层 | 技术 | 理由 |
|---|---|---|
| 服务器 | Python + FastAPI + uvicorn | 与 WatchingYou 一致，直接复用 |
| 数据库 | MySQL + SQLAlchemy | goal.txt 明确要求，支持 FULLTEXT |
| WebSocket | FastAPI 原生 | 已在 WatchingYou 验证 |
| Hooks | Python 脚本 | 与 WatchingYou hooks 结构完全一致 |
| VS Code 插件 | TypeScript + WebView | VS Code 插件标准方案 |
| 手机 Web App | 纯 HTML/CSS/JS | 与 WatchingYou dashboard 一致，零构建工具 |
| Claude API | Anthropic SDK | 知识提炼异步任务 |

---

## 与 WatchingYou 的复用边界

**复用**：
- `ws_manager.py`（WebSocket 连接池）
- `_common.py` hook 工具函数
- `pre_tool.py` / `post_tool.py` / `stop.py` hook 框架
- dashboard 前端 WebSocket 模式

**重写**：
- 存储层：SQLite → MySQL
- 知识提炼模块（新增）
- 配置管理模块（新增）
- 手机聊天中继（扩展 injection 机制）

---

## 第一期交付范围

**服务器**：events、chat、memory、agents 模块

**Hooks**：
- PreToolUse：记忆注入 + 消息取走
- PostToolUse：工具结果上报
- Stop：触发知识提炼

**手机 Web App**：聊天页 + 状态页 + 记忆审核页

**VS Code 插件**：记忆审核 WebView

**第二期（范围外）**：配置管理模块、VS Code 插件配置同步、向量检索升级
