# CodeTogether

用手机监控和与 Claude Code Agent 交互的工具。通过 Claude Code Hooks 实时同步 Agent 状态、工具调用事件和聊天消息，并在手机浏览器中展示。

## 功能

- **Agent 监控**：实时查看所有运行中/已停止的 Claude 会话及最近工具调用
- **手机聊天**：给任意 Session 发消息，Agent 停止时自动唤醒并回复
- **记忆管理**：审核 pending 记忆，启用或拒绝
- **父子 Agent**：子 Agent 的工具调用在父 Agent 视图中合并展示，带蓝色标注

## 快速开始

```bash
git clone <repo>
cd CodeTogether
pip install -r requirements.txt
python3 codetogether.py init
```

`init` 命令会：
1. 将 Hooks 注册到 `~/.claude/settings.json`
2. 将记忆 MCP Server 注册到 `~/.claude.json`
3. 在本地 `7879` 端口启动服务

手机浏览器访问 `http://<电脑IP>:7879/mobile/`

## 命令

```bash
python3 codetogether.py init              # 注册 Hooks + 记忆 MCP + 启动服务（推荐首次使用）
python3 codetogether.py start             # 仅启动服务
python3 codetogether.py install-service   # 安装 launchd 服务（macOS 开机自启）
python3 codetogether.py uninstall-service # 卸载 launchd 服务
```

## 日常使用

### 首次接入

1. 运行 `python3 codetogether.py init`
2. 确认服务已启动在 `127.0.0.1:7879`
3. **新开一个 Claude Code 会话**

之所以要新开会话，是因为 `codetogether.py init` 会把 `codetogether-memory` 写入 `~/.claude.json`，但 MCP 工具通常在 Claude Code 会话启动时加载；当前已打开的窗口不一定会热加载新工具。

### 日常启动

如果 Hooks 和 MCP 已经注册过，平时只需要：

```bash
python3 codetogether.py start
```

如果你改了 `~/.claude.json` 里的 MCP 配置，也需要重新打开 Claude Code 会话，再验证工具是否可见。

### 记忆系统当前工作流

当前记忆不是“全自动工具化写入”，而是分成三段：

1. **写入**：会话结束、session 进入 `stopped` 后，服务端自动提炼最近消息/事件，生成候选记忆
2. **搜索**：Claude 在需要时通过 `memory_search` 搜索当前项目下的已有记忆
3. **反馈**：Claude 使用过某条记忆后，通过 `memory_feedback` 提交 `-2/-1/0/+1/+2` 反馈

也就是说：
- `memory_search` / `memory_feedback` 负责“取用闭环”
- 新记忆写入仍然来自服务端提炼，不是通过 MCP 工具直接创建

## 远程访问

局域网内直接用电脑 IP 访问。跨网络推荐 Cloudflare Tunnel：

```bash
brew install cloudflared
cloudflared tunnel --url http://127.0.0.1:7879
```

会生成一个公网 HTTPS 地址，手机通过该地址访问即可。

## 配置

服务读取项目根目录 `.env` 文件（可选）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | `sqlite:///<home>/.codetogether/data.db` | 数据库连接串，支持 MySQL |

MySQL 示例：
```bash
DATABASE_URL=mysql+pymysql://user:password@localhost:3306/codetogether
```

## 记忆工具

CodeTogether 会向 Claude 注册两个 MCP 工具：

- `memory_search(query, limit=3, session_id=None)`：按当前会话所属项目搜索记忆
- `memory_feedback(memory_id, score, reason, session_id=None)`：对已曝光记忆提交 `-2/-1/0/+1/+2` 反馈

默认情况下不需要模型自己传 `session_id`；MCP 会优先读取当前 Claude 会话环境，并在调用前自动确保服务端存在对应 session。

## 架构

```
Claude Code (本地)
  ├─ Hooks (pre_tool.py / post_tool.py / stop.py)
  │    └─ HTTP → CodeTogether Server (FastAPI)
  └─ MCP (codetogether-memory)
       └─ HTTP → CodeTogether Server (FastAPI)
                    ├─ SQLite / MySQL
                    ├─ WebSocket 推送
                    └─ /mobile/ 静态页面
                          └─ 手机浏览器
```

- **Hooks**：注册在 `~/.claude/settings.json`，负责工具事件同步、消息注入、停止唤醒与 transcript 同步
- **MCP**：注册在 `~/.claude.json`，向 Claude 暴露 `memory_search` / `memory_feedback` 两个记忆工具
- **stop.py**：会话结束时同步 assistant 消息到数据库；若有待处理手机消息则返回 `continue: true` 自动唤醒
- **pre_tool.py**：工具调用前拉取手机消息注入上下文，不自动查询记忆
- **Server**：FastAPI，默认 SQLite 零配置，支持 MySQL

## 开发

```bash
pytest tests/ -v   # 运行测试
```
