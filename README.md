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
