# 短期记忆自动启用与项目归属修复设计

## 背景
当前自动提炼出的记忆默认写为 `pending + short`，需要人工审核后才会进入可用状态；同时部分由 session 自动生成的记忆没有正确写入 `project_id`，导致“当前项目”视图无法展示这些记忆。用户希望取消短期记忆审核流，并修复由对应 session 生成的记忆项目归属问题。

## 目标
- 自动提炼出的短期记忆创建后直接启用，不再进入待审核列表。
- 自动提炼出的记忆必须优先归属到对应 session 所在项目。
- 对已有 `pending + short` 记忆执行一次性回填：直接启用，并尽可能补齐 `project_id`。
- 不扩大到无关 UI 重构，不改变手工创建记忆接口的语义。

## 非目标
- 不移除手工接口中 `pending -> active` 的流转能力。
- 不修改长期记忆晋升逻辑。
- 不新增新的记忆展示页面或摘要卡片。
- 不处理无法从 `source_session_id` 或 `session.cwd` 反推出项目的极少量历史异常数据之外的额外清洗。

## 现状与根因
### 自动提炼写入路径
会话在进入 `stopped` 状态时触发后台提炼任务。提炼任务从最近消息/事件构造摘要，调用提炼模型，然后直接构造 `MemoryModel` 入库。

### 短期记忆仍走待审核流
当前自动提炼保存时没有显式覆盖状态，因而沿用模型默认值，生成 `pending + short` 记忆。这会让自动提炼结果落在“待启用”列表，而不是立即可用。

### `project_id` 缺失的原因
提炼逻辑依赖 `session.project_id` 作为记忆归属来源。但历史 session 中存在 `project_id` 为空的记录，导致自动生成的记忆也写成空项目。前端“当前项目”视图会带 `project_id` 过滤，因此这些记忆在该视图下不可见。

## 方案
### 1. 新生成短期记忆直接启用
在自动提炼保存记忆时，显式写入：
- `status = active`
- `tier = short`
- `activated_at = 当前时间`
- `updated_at = 当前时间`

这样自动提炼出的短期记忆会直接出现在已启用列表中，不再需要人工“启用”。

### 2. 写入前补齐 session 项目归属
在后台提炼任务中，为每条候选记忆解析最终 `project_id`：
1. 优先使用当前 session 的 `project_id`
2. 若为空且 session 有 `cwd`，复用现有“按 cwd 解析/创建项目”的逻辑补出项目
3. 将解析得到的 `project_id` 同时回写到 session（若此前为空）
4. 用该 `project_id` 写入新记忆

这样可以保证“由对应 session 生成的记忆”与 session 的项目归属保持一致，并避免后续同 session 再次生成空项目记忆。

### 3. 启动时执行一次性历史回填
在服务启动迁移阶段增加一段轻量数据修复逻辑，仅处理：
- `status = pending`
- `tier = short`
- `source_session_id` 非空

对每条命中的记忆：
1. 找到 `source_session_id` 对应的 session
2. 若 session 有 `project_id`，直接使用
3. 若 session 无 `project_id` 但有 `cwd`，按现有规则解析/创建项目，并回写到 session
4. 将记忆更新为：
   - `status = active`
   - `project_id = 解析结果（若有）`
   - `activated_at = 当前时间`（仅当原值为空）
   - `updated_at = 当前时间`

这段修复应保持幂等：重复启动不会反复改写已处理完成的数据。

## 组件影响
### `server/routers/agents.py`
- 调整后台提炼保存逻辑
- 在提炼前补齐 session 的项目归属
- 新记忆显式写成 `active + short`

### `server/main.py`
- 增加一次性历史修复逻辑
- 启动时与现有迁移逻辑一起执行

### `server/routers/memory.py`
- 不改接口默认行为
- 保留人工 `pending -> active` 能力，避免扩大改动面

### `mobile/app.js`
- 不要求结构性改动
- 行为上的变化是：自动提炼出的新记忆将主要出现在“已启用”列表，当前项目过滤也会恢复正常

## 数据流
### 新数据流
1. session 进入 `stopped`
2. 触发后台提炼
3. 从 session 读取项目归属；必要时按 `cwd` 补齐
4. 提炼结果写入 `active + short` 记忆
5. 前端“已启用 / 当前项目”直接可见

### 历史修复流
1. 服务启动
2. 扫描 `pending + short` 历史记忆
3. 通过 `source_session_id -> session -> project/cwd` 解析项目
4. 批量更新为 `active + short` 并回填 `project_id`

## 错误处理
- 如果历史记忆找不到对应 session，则仅将其启用，不强造错误项目归属。
- 如果 `cwd` 无法解析出有效项目，则保留 `project_id = NULL`，但不影响启用。
- 若单条数据修复失败，应记录日志并继续处理其他记录，避免阻断启动。

## 测试计划
### 后端测试
- 自动提炼保存的记忆默认是 `active + short`
- 当 session 缺 `project_id` 但有 `cwd` 时，提炼会自动补项目并写入记忆
- 启动修复会把现有 `pending + short` 记忆改成 `active + short`
- 启动修复会根据 `source_session_id` 回填 `project_id`
- 重复执行修复逻辑不会重复污染已处理记录

### 前端/集成验证
- 在“当前项目 + 已启用”过滤下能看到本项目自动提炼出的记忆
- “待启用”列表不再出现新自动提炼的短期记忆

## 风险与取舍
- 历史上无法关联到 session 或项目的记忆仍可能保留空 `project_id`，但这不会再影响新生成数据。
- 保留手工审核接口会使系统同时存在“自动直启”和“人工启用”两种入口，但这是有意的范围控制，可避免扩大到手工操作语义的调整。

## 实施建议
按最小改动顺序实施：
1. 先改后台提炼写入逻辑，保证新数据正确
2. 再补启动修复，处理历史数据
3. 最后补测试并验证当前项目视图
