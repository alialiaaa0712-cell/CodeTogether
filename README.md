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
2. 在本地 `7879` 端口启动服务

手机浏览器访问 `http://<电脑IP>:7879/mobile/`

## 命令

```bash
python3 codetogether.py init              # 注册 Hooks + 启动服务（推荐首次使用）
python3 codetogether.py start             # 仅启动服务
python3 codetogether.py install-service   # 安装 launchd 服务（macOS 开机自启）
python3 codetogether.py uninstall-service # 卸载 launchd 服务
```

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

## 架构

```
Claude Code (本地)
  └─ Hooks (pre_tool.py / post_tool.py / stop.py)
       └─ HTTP → CodeTogether Server (FastAPI)
                   ├─ SQLite / MySQL
                   ├─ WebSocket 推送
                   └─ /mobile/ 静态页面
                         └─ 手机浏览器
```

- **Hooks**：注册在 `~/.claude/settings.json`，每次工具调用/会话结束时自动触发
- **stop.py**：会话结束时同步 assistant 消息到数据库；若有待处理手机消息则返回 `continue: true` 自动唤醒
- **pre_tool.py**：工具调用前拉取手机消息注入上下文，并查询相关记忆
- **Server**：FastAPI，默认 SQLite 零配置，支持 MySQL

## 开发

```bash
pytest tests/ -v   # 运行测试
```
