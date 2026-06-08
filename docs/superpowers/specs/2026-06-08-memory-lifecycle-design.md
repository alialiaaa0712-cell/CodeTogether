# 记忆生命周期升级 设计文档

**目标：** 在现有记忆系统基础上，引入短期/长期分层、自动晋升、Agent 标记复查、定时清理四项能力。

**架构：** 在 Memory 表新增 `tier` 和 `updated_at` 两个字段，status 枚举扩展 `review` 状态，通过 APScheduler 定时任务驱动生命周期流转，hooks 层优先检索长期记忆，移动端支持分层查看与降级确认。

**技术栈：** FastAPI · SQLAlchemy · MySQL · APScheduler · 现有 OpenAI-compatible 内部 API

---

## 数据模型

### Memory 表新增字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `tier` | VARCHAR(10) | `short` | `short`（短期）/ `long`（长期） |
| `updated_at` | DOUBLE | 创建时间 | 最后一次内容或状态变更的时间戳（Unix 秒） |

### status 枚举（扩展后）

| 值 | 含义 |
|----|------|
| `pending` | 提炼后等待人工审核 |
| `active` | 审核通过，正常可用 |
| `review` | Agent 标记为"与项目实际不符，待复查降级" |
| `rejected` | 已拒绝或超期废弃 |

### 生命周期流转规则

```
提炼写入 → pending/short
     ↓ 人工审核通过
  active/short
     ↓ updated_at 超过 7 天（定时任务）
  active/long
     ↓ Agent 发现冲突，标记复查
  review/long
     ↓ 人工确认降级
  active/short（updated_at 重置）
     ↓ review 超过 30 天无处理（定时任务）
  rejected
```

---

## API 变更

### `GET /memory`

新增可选查询参数：
- `tier`: `short` / `long`，按 tier 过滤

### `PATCH /memory/{id}`

请求体扩展：

```json
{
  "status": "active" | "rejected" | "review",
  "tier": "short"
}
```

- 任意字段变更时自动更新 `updated_at`
- `tier=short` 仅允许对 `review/long` 记忆操作（降级），同时将 `status` 重置为 `active`
- `status=review` 仅允许对 `active/long` 记忆操作

### `GET /memory/search`

搜索优先级：先搜索 `active + long`，结果不足 3 条时追加 `active + short`，合计最多返回 3 条。

---

## 定时任务

使用 `APScheduler`（`BackgroundScheduler`），在 FastAPI `lifespan` 启动时注册，应用退出时关闭。

**任务：每天 02:00 执行 `run_memory_housekeeping()`**

1. **短→长晋升：** `status=active AND tier=short AND updated_at < now()-7d` → `tier='long'`，更新 `updated_at`
2. **超期废弃：** `status=review AND updated_at < now()-30d` → `status='rejected'`，更新 `updated_at`

---

## hooks 变更（`hooks/_common.py`）

### `search_memory(query, project_id)`

改为两段式查询：

1. 调用 `GET /memory/search?q=...&tier=long`，最多取 3 条
2. 若不足 3 条，再调用 `GET /memory/search?q=...&tier=short`，补足至 3 条

### 新增 `flag_memory_for_review(memory_id)`

调用 `PATCH /memory/{memory_id}` 将 `status` 设为 `review`，供 Agent 在发现长期记忆与当前项目状态冲突时调用。

---

## 移动端变更（`mobile/app.js` + `mobile/style.css`）

### 记忆筛选维度

在现有"待审核 / 已启用"tab 基础上，"已启用"状态下增加二级筛选：
- 全部 / 长期 / 短期

### 待复查记忆展示

`status=review` 的记忆展示在单独分区（或在"已启用"列表中以特殊样式标注），提供：
- **确认降级** 按钮：将 `tier` 改回 `short`，`status` 改回 `active`
- **废弃** 按钮：将 `status` 改为 `rejected`

### 记忆卡片信息

每条记忆显示：标题、内容摘要、标签、tier 标签（长期/短期）、`updated_at` 时间。
