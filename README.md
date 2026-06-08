# CodeTogether

Claude Code Agent 团队协作平台。

## Hooks 安装

项目已内置可直接使用的 Claude Code 配置文件：[.claude/settings.json](.claude/settings.json)。

其中包含：
- `PreToolUse`：上报工具调用开始事件，并拉取待处理消息/相关记忆
- `PostToolUse`：上报工具调用结果
- `Stop`：上报会话停止状态
- `CODETOGETHER_SERVER=http://127.0.0.1:7878`：默认指向本地启动的 CodeTogether 服务

如果你希望手动安装到全局 `~/.claude/settings.json`，可参考下面内容：

```json
{
  "env": {
    "CODETOGETHER_SERVER": "http://127.0.0.1:7878"
  },
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

## 手机 Web App

启动服务后，在手机浏览器访问：

- `http://<你的电脑 IP>:7878/mobile/index.html`
- 本机调试：`http://127.0.0.1:7878/mobile/index.html`

页面能力：
- **状态**：查看 Agent 状态与最近工具事件
- **聊天**：给指定 Session 发送消息，并查看历史消息
- **记忆**：审核 pending 记忆并启用 / 拒绝

## 环境变量

服务启动时会自动读取项目根目录的 `.env` 文件。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CODETOGETHER_SERVER` | `http://localhost:8000` | CodeTogether 服务器地址 |
| `DATABASE_URL` | `mysql+pymysql://root:root@localhost:3306/codetogether` | 服务端数据库连接串 |
| `SERVER_PORT` | `7878` | `python server/main.py` 启动时使用的端口 |

示例：

```bash
DATABASE_URL=mysql+pymysql://user:password@localhost:3306/codetogether
SERVER_PORT=7878
```

## 服务器启动

```bash
pip install -r requirements.txt
uvicorn server.main:app --reload --port 7878
```

如果使用项目根目录 `.env`，直接执行以上命令即可；也可以显式指定：

```bash
uvicorn --env-file .env server.main:app --reload --port 7878
```
