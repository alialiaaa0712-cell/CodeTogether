# 手机端设置页与记忆提取配置设计

**日期**：2026-07-03  
**状态**：已确认

---

## 目标

1. 手机端新增「设置」tab，admin 用户可在页面上配置记忆提取的 API Key / Base URL / 模型名，保存后服务端实时生效（无需重启）。
2. topbar 退出按钮缩小为低调的文字链接风格，不再有边框。

---

## 整体改动范围

| 组件 | 改动 |
|------|------|
| `server/models.py` | 新增 `ServerConfig` 表（key/value 键值对） |
| `server/schemas.py` | 新增 `ConfigItemOut`、`ConfigUpdate` |
| `server/routers/config.py` | 新建：`GET /config`、`PUT /config`（admin 专属） |
| `server/main.py` | 注册 config router；启动时从数据库加载配置，写入运行时变量 |
| `server/services/extractor.py` | 改为从运行时模块变量读取配置（优先于环境变量） |
| `mobile/index.html` | 新增 `#view-settings` 视图，tab 导航加「设置」按钮 |
| `mobile/style.css` | 设置页样式，退出按钮样式调整 |
| `mobile/app.js` | 设置 tab 逻辑：读取配置、保存配置、admin 判断、退出按钮显示控制 |

---

## 第一节：数据模型

### ServerConfig 表

```python
class ServerConfig(Base):
    __tablename__ = "server_config"
    key   = Column(String(64), primary_key=True)
    value = Column(Text, nullable=True)
```

主键为 `key`，使用字符串主键（无 UUID），简单直接。

启动时若表为空，自动写入三条默认记录：

| key | 默认值 |
|-----|--------|
| `extractor_api_key` | `""` |
| `extractor_base_url` | `https://oneapi-comate.baidu-int.com/v1` |
| `extractor_model` | `gpt-5.4` |

---

## 第二节：服务端 API

### Schema

```python
class ConfigItemOut(BaseModel):
    key: str
    value: str  # api_key 值脱敏：非空时返回 "****" + 后 4 位

class ConfigUpdate(BaseModel):
    extractor_api_key: Optional[str] = None
    extractor_base_url: Optional[str] = None
    extractor_model: Optional[str] = None
```

### 端点

- `GET /config` — 返回全部配置，需要有效 Bearer Token（非 admin 也可读），api_key 脱敏
- `PUT /config` — 更新配置，**仅 admin key** 可调用；更新后同步写入 extractor 运行时变量

### extractor 运行时变量

在 `server/services/extractor.py` 顶部增加三个模块变量：

```python
_api_key: str = ""
_base_url: str = "https://oneapi-comate.baidu-int.com/v1"
_model: str = "gpt-5.4"
```

`extract_memories()` 优先读这三个变量，为空时回退到环境变量，保持向后兼容：

```python
api_key = _api_key or os.getenv("CT_EXTRACTOR_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN", "")
base_url = _base_url or os.getenv("CT_EXTRACTOR_BASE_URL", "https://oneapi-comate.baidu-int.com/v1")
model = _model or os.getenv("CT_EXTRACTOR_MODEL", "gpt-5.4")
```

服务启动时（`_run_startup_migrations`）从数据库加载配置并写入这三个变量。

---

## 第三节：手机端设置页

### tab 导航

在 tab-bar 加第三个按钮：

```html
<button class="tab-btn" data-tab="settings" type="button">设置</button>
```

### `#view-settings` 视图

```html
<section id="view-settings" class="view">
  <section class="view-section-head compact-head">
    <h2>设置</h2>
  </section>
  <div class="card settings-card">
    <div id="settings-readonly-hint" class="settings-hint" style="display:none">
      仅 Admin 可修改配置
    </div>
    <label class="settings-label">记忆提取 API Key</label>
    <input id="settings-api-key" class="settings-input" type="password" placeholder="留空使用服务端环境变量">
    <label class="settings-label">Base URL</label>
    <input id="settings-base-url" class="settings-input" type="text" placeholder="https://...">
    <label class="settings-label">模型名</label>
    <input id="settings-model" class="settings-input" type="text" placeholder="gpt-5.4">
    <button id="settings-save" class="settings-save" type="button" style="display:none">保存</button>
    <p id="settings-msg" class="settings-msg" style="display:none"></p>
  </div>
</section>
```

### admin 判断

登录成功后，调用 `GET /config` 检测响应状态：
- 同时调用 `GET /admin/keys` —— 返回 200 表示当前是 admin，显示保存按钮；403 则只读显示。

### 保存逻辑

点击保存 → `PUT /config` → 成功显示"已保存"，失败显示错误信息。

---

## 第四节：退出按钮样式调整

将 `.logout-btn` 改为无边框文字链接风格：

```css
.logout-btn {
  background: none;
  border: none;
  padding: .1rem .3rem;
  font-size: .75rem;
  color: var(--text-secondary, #999);
  cursor: pointer;
  opacity: 0.7;
}
.logout-btn:hover { opacity: 1; }
```

文字保留"退出"，字号更小，颜色更低调。

---

## 兼容性说明

- 旧部署无 `server_config` 表时，`_run_startup_migrations` 会自动建表并写入默认值
- `extractor.py` 运行时变量默认为空，回退环境变量，不影响现有部署
- 非 admin 用户只读配置，无法修改
