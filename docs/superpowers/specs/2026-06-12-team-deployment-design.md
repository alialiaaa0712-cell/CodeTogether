# CodeTogether 团队级部署设计

**日期**：2026-06-12  
**状态**：已确认

---

## 目标

将 CodeTogether 从单人本地模式升级为团队共享模式：不同成员电脑上的 Claude Code Agent 通过云端共享服务器协作，按项目（git 仓库）隔离数据，每人持有独立 API Key 认证。

---

## 整体架构

```
团队成员 A 的电脑                团队成员 B 的电脑
  Claude Code Agent               Claude Code Agent
  hooks/_common.py                hooks/_common.py
  CODETOGETHER_SERVER=https://... CODETOGETHER_SERVER=https://...
  CODETOGETHER_API_KEY=key-xxx    CODETOGETHER_API_KEY=key-yyy
        │                               │
        └──────────────┬────────────────┘
                       ▼
              云服务器 (任意 VPS)
              Docker Compose
              ┌─────────────────┐
              │  FastAPI 服务    │  :443 (nginx 反代 + HTTPS)
              │  + Auth 中间件   │
              └────────┬────────┘
                       │
              ┌─────────────────┐
              │     MySQL 8.0   │  (数据持久化，Docker 卷)
              └─────────────────┘
```

---

## 第一节：认证系统

### ApiKey 数据模型

新增 `api_keys` 表：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | VARCHAR(36) | UUID 主键 |
| `key_hash` | VARCHAR(64) | SHA-256 哈希，不存明文 |
| `label` | VARCHAR(128) | 备注，如 "alice-macbook" |
| `is_admin` | BOOL | 是否可调用 `/admin/*` |
| `is_active` | BOOL | 是否启用，默认 true |
| `created_at` | Double | 创建时间 |

API Key 格式：`ct-` 前缀 + 32 字节随机十六进制（共 66 字符）。

### Auth 中间件

- FastAPI 依赖注入 `get_current_key(request)`
- 从请求头 `Authorization: Bearer <key>` 提取，SHA-256 后查表
- **豁免路径**（无需认证）：`GET /`、`GET /mobile/*`、`GET /ws`
- 所有其他路径需要有效 key

### 管理端点（仅 admin key）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/admin/keys` | 创建 key，返回明文（仅此一次） |
| `GET` | `/admin/keys` | 列出所有 key（不含明文） |
| `DELETE` | `/admin/keys/{id}` | 禁用 key |

### 初始化

`ADMIN_KEY` 环境变量预置首个 admin key（startup 时若表为空则自动写入）。运维用该 key 调用 `/admin/keys` 为每位成员生成各自的 key。

---

## 第二节：项目自动匹配

### 流程

1. hooks 启动时执行 `git -C <cwd> remote get-url origin` 获取 repo URL
2. `ensure_session()` 将 `repo_url` 随 `cwd` 一起上报至 `POST /agents`
3. 服务端按 `repo_url` 精确匹配 `projects` 表：
   - 命中 → 将 Session 绑定到该 Project
   - 未命中 → 自动创建 Project（name 取 URL 最后一段，如 `my-repo`），再绑定

### Session 变更

`sessions` 表新增 `user_label` 字段（VARCHAR 128），写入发起请求的 API Key 的 `label`，方便在 UI 上区分是哪台机器的会话。

---

## 第三节：Docker 部署

### 新增文件

```
CodeTogether/
├── Dockerfile
├── docker-compose.yml
├── nginx.conf
└── .env.example
```

### Dockerfile

- 基于 `python:3.11-slim`
- 安装 `requirements.txt`
- 启动：`uvicorn server.main:app --host 0.0.0.0 --port 8000`

### docker-compose.yml

```yaml
services:
  app:
    build: .
    environment:
      - DATABASE_URL=mysql+pymysql://root:${MYSQL_ROOT_PASSWORD}@db:3306/codetogether
      - ADMIN_KEY=${ADMIN_KEY}
    depends_on: [db]
    ports: ["8000:8000"]

  db:
    image: mysql:8.0
    environment:
      - MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}
      - MYSQL_DATABASE=codetogether
    volumes:
      - mysql_data:/var/lib/mysql

volumes:
  mysql_data:
```

nginx 做 443 反代 + certbot HTTPS，对外只暴露 443。

### 成员接入（每台开发机）

在 `~/.claude/.env` 或 shell profile 中配置两个变量：

```bash
CODETOGETHER_SERVER=https://your-server.com
CODETOGETHER_API_KEY=ct-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

hooks 自动读取，无需其他改动。

---

## 改动范围总结

| 组件 | 改动 |
|------|------|
| `server/models.py` | 新增 `ApiKey` 表；`Session` 加 `user_label` |
| `server/main.py` | 启动时写入 admin key（若表空） |
| `server/routers/auth.py` | 新增认证依赖、`/admin/keys` 端点 |
| `server/routers/agents.py` | `POST /agents` 接收 `repo_url`，自动匹配/创建 Project |
| 所有 router | 添加 `Depends(get_current_key)` |
| `hooks/_common.py` | 读取 `CODETOGETHER_API_KEY`，加入请求头；`ensure_session` 传 `repo_url` |
| `Dockerfile` | 新增 |
| `docker-compose.yml` | 新增 |
| `nginx.conf` | 新增 |
| `.env.example` | 更新，增加云端部署所需变量 |
