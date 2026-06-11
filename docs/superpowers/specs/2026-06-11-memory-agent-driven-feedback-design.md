# Agent 主动搜索 + 反馈积分闭环记忆系统设计

## 背景

当前记忆系统存在三个核心问题：

1. 记忆依赖 `pre_tool` 自动搜索并注入，Agent 被动接收，噪音大，且无法区分“看到了记忆”与“真正用了记忆”
2. 短期记忆依赖“命中次数 / 7 天窗口”推进 review，统计的是搜索曝光而不是实际价值
3. 前端与服务端围绕“命中次数”建模，无法形成“使用 -> 反馈 -> 晋升 / 删除”的价值闭环

本次设计直接放弃旧语义，清空当前记忆数据，全面切换到“Agent 显式搜索 + Agent 显式评分 + 分数驱动晋升”的新体系。

## 目标

1. 记忆搜索从 `pre_tool` 自动注入改为 Agent 显式调用
2. 记忆价值从“被搜到几次”改为“被实际使用后得到多少反馈分”
3. 建立完整闭环：搜索 -> 使用 -> 评分 -> 晋升 review / 删除
4. 保留人工确认长期记忆的治理方式
5. 去掉短期记忆的时间恶化、窗口重置、自动命中统计等旧机制

## 非目标

1. 不保留旧记忆数据，不做旧命中次数到新积分的迁移映射
2. 不做兼容双轨运行，不同时支持“自动注入”和“显式搜索”两种模式
3. 不做长期记忆自动降级或自动删除
4. 不做复杂排序学习或个性化推荐，先保持规则式实现

## 总体方案

新系统采用“双工具闭环”方案：

1. Agent 在需要项目规则、边界、坑点时，显式调用 `memory_search(query)` 搜索当前项目的记忆
2. Agent 在实际采用某条记忆后，再显式调用 `memory_feedback(memory_id, score, reason)` 提交反馈
3. 搜索行为本身不增加任何分数；只有反馈行为才改变记忆分值
4. 短期记忆达到正向分数阈值后进入 `review + short`
5. 你在前端确认后，`review + short` 才会转成 `active + long`
6. 短期记忆达到负向分数阈值后自动删除

这个方案的核心是把“是否有价值”的判断，从“被系统搜到”切换成“被 Agent 实际采用后打分”。

## 生命周期

### 1. 记忆创建

- 提炼链路仍会产出候选记忆
- 新记忆默认状态：`pending + short`
- 管理端人工启用后变为：`active + short`

### 2. Agent 搜索

- Agent 显式发起 `memory_search(query)`
- 服务端按当前 `session_id -> project_id` 解析项目范围
- 返回可用记忆列表
- 搜索本身不会修改任何分数、状态或统计字段

### 3. Agent 反馈

- Agent 实际采用某条记忆后，调用 `memory_feedback(memory_id, score, reason)`
- `score` 使用五档积分：`-2 / -1 / 0 / +1 / +2`
- 服务端更新该条记忆的累计积分与反馈统计

### 4. review 晋升

- 短期记忆累计积分达到正向阈值后，转为 `review + short`
- 进入 review 后，不再继续作为普通短期记忆参与搜索
- 你在管理端点击“升为长期”后，转为 `active + long`

### 5. 低价值淘汰

- 短期记忆累计积分达到负向阈值后，直接删除
- 不再保留“rejected”作为业务主路径上的中间状态

## 数据模型

## 数据清理策略

上线新系统时，直接清空当前 `memories` 表中的既有数据。

原因：

1. 旧数据基于“命中次数”语义，新数据基于“反馈积分”语义，无法无损转换
2. 若保留旧数据，需要在服务端、前端、测试里保留兼容分支，系统复杂度显著上升
3. 当前记忆本身质量已被确认需要整体重构，重新开始比兼容旧分数更干净

## `Memory` 字段调整

保留字段：

- `id`
- `project_id`
- `title`
- `content`
- `tags`
- `status`
- `tier`
- `source_session_id`
- `created_at`
- `updated_at`
- `activated_at`

删除旧字段：

- `hit_count_7d`
- `last_hit_at`
- `review_hit_count`

保留但改写语义：

- `review_reason`
  - 旧值：`hit_threshold`
  - 新值：`score_threshold`

新增字段：

- `score_total: int`
  - 当前累计积分，默认 `0`
- `feedback_count: int`
  - 被反馈的总次数，默认 `0`
- `last_feedback_at: Optional[float]`
  - 最近一次反馈时间
- `review_score: Optional[int]`
  - 进入 review 当下的累计积分快照

## 可选反馈日志表

建议新增 `memory_feedback_logs` 表，用于保留完整反馈证据链。

字段建议：

- `id`
- `memory_id`
- `session_id`
- `score`
- `reason`
- `created_at`

作用：

1. 让管理端未来能查看“这条记忆为什么升上去 / 为什么被删掉”
2. 便于后续排查 Agent 是否误评、滥评
3. 便于测试和审计

## 接口设计

## 1. Agent 主动搜索

### `POST /memory/search`

请求体：

```json
{
  "query": "数据库连接池 timeout",
  "session_id": "sess-123",
  "limit": 3
}
```

语义：

- Agent 主动搜索当前项目记忆
- 仅返回当前项目下可见的已启用记忆
- long 优先，short 补足
- 默认最多返回 3 条
- 搜索不更新分数、不更新状态、不更新任何统计

返回对象在现有 `MemoryOut` 基础上，展示新积分字段：

- `score_total`
- `feedback_count`
- `last_feedback_at`
- `review_score`

## 2. Agent 反馈记忆价值

### `POST /memory/{memory_id}/feedback`

请求体：

```json
{
  "session_id": "sess-123",
  "score": 2,
  "reason": "帮助确认 MySQL 5.7 不支持该 DDL"
}
```

语义：

- Agent 针对单条已实际使用的记忆提交反馈
- `score` 允许值固定为：`-2, -1, 0, 1, 2`
- 服务端执行：
  - `score_total += score`
  - `feedback_count += 1`
  - `last_feedback_at = now`
- 若短期记忆达到正向阈值：
  - `status = review`
  - `review_reason = score_threshold`
  - `review_score = score_total`
- 若短期记忆达到负向阈值：
  - 删除该记忆
- long 记忆允许记录反馈，但不会自动降级或自动删除

## 3. 人工治理接口

继续保留并收紧以下接口：

### `PATCH /memory/{memory_id}`

仅允许：

1. `pending -> active(short)`
2. `review + short -> active + long`

### `DELETE /memory/{memory_id}`

用途：

- 删除 pending 候选记忆
- 删除 review 记忆
- 删除人工判定不应保留的记忆

## Agent 侧触发方式

## 1. 移除自动注入

现有 `pre_tool.py` 中这段逻辑将被移除：

- 根据当前工具输入自动提取查询词
- 自动调用 `search_memory()`
- 自动把记忆内容 `print` 给 Agent

替换后，`pre_tool` 只保留：

1. 上报事件
2. 同步 transcript
3. 拉取 pending 手机消息

不再自动拉记忆内容。

## 2. 提供显式记忆能力

Agent 侧应新增两个显式可调用能力：

### `memory_search(query)`

- Agent 觉得当前任务需要项目知识时主动调用
- 服务端根据 `session_id` 自动限定项目

### `memory_feedback(memory_id, score, reason)`

- Agent 真正采用某条记忆后再调用
- 不要求每次搜索后都必须反馈所有结果
- 只对实际使用过的条目反馈

## 3. Hook / 系统提示的职责

Hook 不再注入记忆内容，但可以保留一条轻提示，告诉 Agent：

- 当需要项目规则、边界、坑点时，可以主动搜索记忆
- 当实际使用某条记忆后，应主动反馈这条记忆是否有用

这样能保留能力发现性，同时避免被动记忆噪音。

## 前端管理页改造

## 展示主指标替换

记忆页主指标从“7天命中次数”改为：

- 累计积分 `score_total`
- 反馈次数 `feedback_count`
- 最近反馈时间 `last_feedback_at`

不再展示：

- `hit_count_7d`
- `last_hit_at`
- `review_hit_count`

## 列表分区

保留三段，但语义更新：

### `pending`

- 待启用候选记忆
- 操作：启用、删除

### `review`

- 积分达到阈值、等待人工确认的短期记忆
- 展示：
  - `score_total`
  - `feedback_count`
  - `review_score`
  - 最近一次反馈时间
- 操作：升为长期、删除

### `active`

- 已启用记忆
- 支持按 `short / long` 过滤
- short 重点展示累计积分
- long 展示累计积分作为观察值，但不参与自动降级

## 界面文案

建议文案统一从“命中”改为“反馈积分”：

- 旧：`7天命中 3 次`
- 新：`累计积分 +4 · 反馈 3 次`

## 阈值规则

建议首版采用固定阈值：

- 短期记忆进入 review：`score_total >= 3`
- 短期记忆自动删除：`score_total <= -3`

原因：

1. 阈值足够简单，利于验证闭环是否成立
2. 五档评分下，`+2/+1` 两三次即可晋升，不会太慢
3. `-3` 能过滤掉多次被判无用的短期记忆

后续若使用中发现偏严或偏松，再单独调参，不在首版设计中引入更复杂规则。

## 失败保护

## 1. 搜索不改分

`memory_search` 只负责查，不负责计分，避免“曝光次数”再次被误当成价值信号。

## 2. 反馈必须针对已返回条目

服务端应保证：

- 只有当前 session 搜索结果中出现过的 `memory_id`，才允许提交 feedback
- 不能对未搜索到、未曝光给 Agent 的记忆直接评分

实现上建议在服务端记录最近一次搜索曝光，例如：

- 按 `session_id` 维护一个短期有效的 `memory_id` 集合
- 或新增轻量搜索曝光日志表

目标是防止 Agent 凭空给记忆打分。

## 3. 长期记忆不自动降级

长期记忆允许记录反馈，但：

- 不会自动变回 short
- 不会因低分自动删除

是否处理长期记忆仍由人工决定。

## 测试策略

测试要围绕“显式搜索 + 显式评分”闭环重写，不再围绕旧的 pre_hook 注入和命中窗口。

## 后端测试

### 搜索

- `POST /memory/search` 仅返回当前项目可见记忆
- long 优先、short 补足
- 搜索不会改变 `score_total`、`feedback_count`、状态

### 反馈

- 单条记忆反馈后，`score_total / feedback_count / last_feedback_at` 正确更新
- 短期记忆达到正阈值后进入 `review + short`
- 短期记忆达到负阈值后被删除
- long 记忆反馈后只更新统计，不自动降级
- 未在当前 session 搜索结果中出现的 `memory_id` 不允许直接 feedback

### 人工治理

- `pending -> active(short)` 正常
- `review + short -> active + long` 正常
- 其他 PATCH 路径继续拒绝

## Hook / Agent 侧测试

- `pre_tool` 不再自动调用 `search_memory`
- Agent 记忆搜索通过显式工具路径触发
- Agent 记忆评分通过显式反馈路径触发

## 前端测试

- 记忆页展示累计积分、反馈次数、最近反馈时间
- 不再展示命中次数字段
- review 区操作为“升为长期 / 删除”
- active 区可按 short / long 过滤

## 迁移与发布顺序

1. 停用旧的自动注入逻辑
2. 清空现有 `memories` 数据
3. 切换数据库字段和接口语义
4. 接入 Agent 显式搜索与显式反馈能力
5. 更新前端管理页展示与操作
6. 补齐新闭环测试

## 风险与取舍

### 风险 1：Agent 可能忘记反馈

后果：

- 记忆被搜索了但没有积分增长

接受原因：

- 这比“搜索即算命中”更真实
- 后续可通过提示词或工具约束强化 feedback 习惯

### 风险 2：Agent 评分可能不稳定

后果：

- 某些短期记忆可能被高估或低估

缓解：

- 保留人工 review 作为长期晋升闸门
- 记录 feedback 日志，便于排查

### 风险 3：直接清空旧记忆会丢失历史

接受原因：

- 当前旧记忆语义本身就不再可信
- 保留旧数据只会增加兼容成本，不会提高新系统质量

## 最终结论

本次记忆系统重构采用“全面置换”策略：

- 清空当前记忆数据
- 移除 `pre_tool` 自动搜索注入
- 改为 Agent 显式 `memory_search(query)`
- 改为 Agent 显式 `memory_feedback(memory_id, score, reason)`
- 用累计积分而不是命中次数驱动 short -> review
- 达到正阈值后人工确认升长期
- 达到负阈值后删除短期记忆
- 前端主指标改为积分和反馈次数

这样可以把“记忆是否真正有价值”的判断，牢牢建立在 Agent 实际使用后的反馈上，而不是搜索曝光上。