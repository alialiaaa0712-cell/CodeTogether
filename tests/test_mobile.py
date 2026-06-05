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


def test_mobile_shell_contains_three_tabs(client):
    """
    验证移动端页面骨架包含状态、聊天、记忆三个标签按钮。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言页面 HTML 中包含三个标签按钮的唯一标识。
    """
    html = client.get("/mobile/index.html").text
    assert 'id="tab-status"' in html
    assert 'id="tab-chat"' in html
    assert 'id="tab-memory"' in html


def test_mobile_shell_contains_chat_and_memory_controls(client):
    """
    验证移动端页面骨架包含聊天与记忆审核所需的控件。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言页面 HTML 中包含聊天与记忆区域的关键控件。
    """
    html = client.get("/mobile/index.html").text
    assert 'id="chat-session-select"' in html
    assert 'id="chat-form"' in html
    assert 'id="memory-list"' in html
    assert 'id="memory-filter-pending"' in html


def test_mobile_css_contains_mobile_layout_rules(client):
    """
    验证移动端样式文件包含标签栏、视图切换与卡片布局规则。

    参数:
        client: FastAPI 测试客户端，用于向应用发起 HTTP 请求。

    返回值:
        无返回值；断言样式文本中包含关键布局类名。
    """
    css = client.get("/mobile/style.css").text
    assert ".tab-bar" in css
    assert ".view.active" in css
    assert ".card" in css
