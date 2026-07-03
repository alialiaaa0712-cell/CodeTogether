# 手机端 UI 美化设计

**日期**：2026-07-03  
**状态**：已确认

---

## 目标

在保持现有蓝灰磨砂风格基础上，精致提升界面层次感，主要改动：
1. Agent 卡片改为左侧状态条 + 右侧彩色徽章，去掉圆点指示
2. Tab 选中改为底部蓝色横线指示（取代当前深色背景块）
3. 连接状态改为绿色徽章样式
4. 概览数字加粗放大
5. 退出按钮已在上一迭代完成（低调灰色文字）

---

## 改动范围

| 文件 | 改动 |
|------|------|
| `mobile/style.css` | 修改 `.agent-card`、`.tab-btn.active`、`.conn-status`、`.tab-bar`、`.project-label`，新增 `.status-badge`、`.agent-card-left-bar` |
| `mobile/app.js` | `renderAgents()` 卡片 HTML 结构调整，新增状态徽章；`renderAgentOverview()` 数字样式增强 |
| `mobile/index.html` | 更新 `style.css` 版本号，更新 `app.js` 版本号 |

---

## 第一节：Agent 卡片

### 当前结构
```html
<button class="agent-card">
  <div class="agent-card-row">
    <span class="status-dot active"></span>
    <span class="agent-id">xxx</span>
    <span class="agent-status-label active">active</span>
    <span class="agent-delete-btn">✕</span>
  </div>
  <div class="hint">时间</div>
</button>
```

### 新结构
```html
<button class="agent-card agent-card--active">  <!-- 状态 class 加在卡片上 -->
  <div class="agent-card-row">
    <div class="agent-card-info">
      <span class="agent-name">项目名/会话 ID 前8位</span>
      <span class="agent-time">时间</span>
    </div>
    <div class="agent-card-right">
      <span class="status-badge status-badge--active">运行中</span>
      <span class="agent-delete-btn" role="button" data-delete-id="..." title="删除">✕</span>
    </div>
  </div>
</button>
```

### CSS 关键变化

- `.agent-card`：移除 border-radius 右侧圆角为 14px，左侧加 `border-left: 4px solid` 色条
- `.agent-card--active`：左侧 `border-left-color: var(--success)`
- `.agent-card--stopped`：左侧 `border-left-color: var(--line)`
- `.status-badge`：圆角药片徽章，`font-size: 10px`，`padding: 2px 8px`
- `.status-badge--active`：`background: rgba(31,138,98,0.12); color: var(--success)`
- `.status-badge--stopped`：`background: var(--bg); color: var(--text-faint)`
- `.agent-name`：`font-size: 13px; font-weight: 600`，截断显示会话 cwd 最后两段（项目/目录）
- `.agent-time`：`font-size: 11px; color: var(--text-faint); margin-top: 2px`

---

## 第二节：Tab 选中样式

### 当前
`.tab-btn.active`：深色背景（`rgba(22,32,51,0.94)`）白字

### 新样式
```css
.tab-btn {
  flex: 1;
  background: none;
  color: var(--text-soft);
  box-shadow: none;
  border: none;
  padding: 8px 12px 6px;
  font-size: 12px;
  font-weight: 500;
  position: relative;
}

.tab-btn.active {
  background: none;
  color: var(--accent);
  font-weight: 600;
  border: none;
}

.tab-btn.active::after {
  content: "";
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 3px;
  background: var(--accent);
  border-radius: 2px;
}
```

Tab-bar 布局改为 `grid-template-columns: repeat(3, 1fr)`（支持三个 tab）。

---

## 第三节：连接状态徽章

### 当前
`.conn-status.connected`：绿底绿字，padding 较大

### 新样式

```css
.conn-status {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  border: none;
}

.conn-status.connected {
  background: #dcfce7;
  color: #16a34a;
}

.conn-status.disconnected {
  background: rgba(204, 90, 67, 0.10);
  color: var(--danger);
}
```

已连接时文字改为「● 已连接」（JS 里 `setConnectionStatus` 改文字）。

---

## 第四节：概览卡数字

`.overview-value` 字号从当前大小增加到 `font-size: 24px; font-weight: 800`，颜色活跃数用 `var(--accent)`，其余用 `var(--text)`。

---

## 兼容性说明

- tab-bar `grid-template-columns` 从 `repeat(2, 1fr)` 改为 `repeat(3, 1fr)`（配合设置 tab）
- `.status-dot` 样式保留（聊天页里还有用到），不删除
- `agent-card-left-bar` 通过 CSS border-left 实现，不需要额外 DOM 元素
