def test_root_still_returns_healthcheck(client):
    """
    验证根路径仍返回健康检查结果。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言根路径响应状态码与返回内容符合预期。
    """
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "CodeTogether"}


def test_mobile_index_is_served(client):
    """
    验证移动端首页静态文件可以正常访问。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言移动端首页响应成功且包含预期页面内容。
    """
    resp = client.get("/mobile/index.html")
    assert resp.status_code == 200
    assert "CodeTogether Mobile" in resp.text


def test_mobile_mount_root_is_served(client):
    """
    验证挂载根路径 /mobile 会返回移动端首页内容。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言 /mobile 响应成功且包含预期页面内容。
    """
    resp = client.get("/mobile")
    assert resp.status_code == 200
    assert "CodeTogether Mobile" in resp.text


def test_mobile_assets_are_served(client):
    """
    验证移动端静态资源文件可以正常访问。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言样式与脚本资源响应成功且内容符合预期。
    """
    css = client.get("/mobile/style.css")
    js = client.get("/mobile/app.js")
    assert css.status_code == 200
    assert js.status_code == 200
    assert ".topbar" in css.text
    assert 'console.log("CodeTogether mobile ready")' in js.text


def test_mobile_shell_contains_core_views_and_tabs(client):
    """
    验证移动端页面骨架包含三个视图容器与三个标签按钮的契约。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言页面 HTML 中包含视图与标签按钮的关键标识。
    """
    html = client.get("/mobile/index.html").text
    assert 'id="view-status"' in html
    assert 'id="view-chat"' in html
    assert 'id="view-memory"' in html
    assert 'id="tab-status"' in html
    assert 'id="tab-chat"' in html
    assert 'id="tab-memory"' in html


def test_mobile_shell_uses_status_view_as_default_active_tab(client):
    """
    验证移动端页面默认激活状态页，并为三个标签按钮声明正确的 data-tab。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言默认视图与标签按钮的静态骨架契约符合预期。
    """
    html = client.get("/mobile/index.html").text
    assert 'id="view-status" class="view active"' in html
    assert 'id="tab-status" class="tab-btn active" data-tab="status"' in html
    assert 'id="tab-chat" class="tab-btn" data-tab="chat"' in html
    assert 'id="tab-memory" class="tab-btn" data-tab="memory"' in html


def test_mobile_shell_contains_connection_and_feedback_controls(client):
    """
    验证移动端页面骨架包含连接状态、提示气泡以及聊天与记忆审核的关键控件。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言页面 HTML 中包含关键交互区域所需的静态元素。
    """
    html = client.get("/mobile/index.html").text
    assert 'id="conn-status"' in html
    assert 'id="toast"' in html
    assert 'id="chat-session-select"' in html
    assert 'id="chat-form"' in html
    assert 'id="memory-list"' in html
    assert 'id="memory-filter-pending"' in html


def test_mobile_css_contains_mobile_layout_rules(client):
    """
    验证移动端样式文件包含标签栏、视图切换、卡片布局与底部安全区留白规则。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言样式文本中包含关键布局类名与一致的安全区处理策略。
    """
    css = client.get("/mobile/style.css").text
    assert ".tab-bar" in css
    assert ".view.active" in css
    assert ".card" in css
    assert "padding-bottom: calc(72px + env(safe-area-inset-bottom));" in css
