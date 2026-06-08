def test_create_memory(client):
    resp = client.post("/memory", json={
        "title": "数据库连接池配置",
        "content": "使用 SQLAlchemy pool_pre_ping=True 防止连接超时断开",
        "tags": "database,sqlalchemy,config"
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_activate_memory(client):
    resp = client.post("/memory", json={"title": "测试知识", "content": "内容"})
    mem_id = resp.json()["id"]

    resp = client.patch(f"/memory/{mem_id}", json={"status": "active"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


def test_search_memory(client):
    mem_resp = client.post("/memory", json={
        "title": "FastAPI 路由注册",
        "content": "使用 include_router 注册子路由",
        "tags": "fastapi"
    })
    client.patch(f"/memory/{mem_resp.json()['id']}", json={"status": "active"})

    resp = client.get("/memory/search?q=include_router")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) >= 1
    assert all(r["status"] == "active" for r in results)


def test_list_memories_filters_by_status(client):
    """
    验证记忆列表接口会按状态筛选返回结果，支撑 mobile 待审核与已启用列表。

    参数:
        client: FastAPI 测试客户端，用于创建并更新记忆条目。

    返回值:
        无返回值；断言 pending 与 active 查询结果只包含对应状态条目。
    """
    pending_resp = client.post("/memory", json={
        "title": "待审核记忆",
        "content": "这条记忆应留在 pending 列表",
    })
    active_resp = client.post("/memory", json={
        "title": "已启用记忆",
        "content": "这条记忆应出现在 active 列表",
    })
    client.patch(f"/memory/{active_resp.json()['id']}", json={"status": "active"})

    pending_list = client.get("/memory?status=pending")
    active_list = client.get("/memory?status=active")

    assert pending_list.status_code == 200
    assert active_list.status_code == 200
    assert any(item["id"] == pending_resp.json()["id"] for item in pending_list.json())
    assert all(item["status"] == "pending" for item in pending_list.json())
    assert any(item["id"] == active_resp.json()["id"] for item in active_list.json())
    assert all(item["status"] == "active" for item in active_list.json())


def test_memory_has_tier_and_updated_at(client):
    """验证记忆创建时默认 tier 为 short，且 updated_at 已被正确设置。"""
    resp = client.post("/memory", json={"title": "t", "content": "c"})
    data = resp.json()
    assert data["tier"] == "short"
    assert data["updated_at"] > 0


def test_search_prefers_long(client):
    """长期记忆应排在短期记忆前面返回。"""
    short_resp = client.post("/memory", json={"title": "short knowledge", "content": "pytest short"})
    long_resp = client.post("/memory", json={"title": "long knowledge", "content": "pytest long"})
    client.patch(f"/memory/{short_resp.json()['id']}", json={"status": "active"})
    client.patch(f"/memory/{long_resp.json()['id']}", json={"status": "active"})
    client.patch(f"/memory/{long_resp.json()['id']}", json={"tier": "long"})

    resp = client.get("/memory/search?q=pytest")
    results = resp.json()
    assert len(results) >= 1
    long_ids = [r["id"] for r in results if r["tier"] == "long"]
    short_ids = [r["id"] for r in results if r["tier"] == "short"]
    if long_ids and short_ids:
        long_pos = next(i for i, r in enumerate(results) if r["tier"] == "long")
        short_pos = next(i for i, r in enumerate(results) if r["tier"] == "short")
        assert long_pos < short_pos


def test_patch_to_review(client):
    """验证可以将 active/long 记忆标记为 review 状态。"""
    resp = client.post("/memory", json={"title": "t", "content": "c"})
    mid = resp.json()["id"]
    client.patch(f"/memory/{mid}", json={"status": "active"})
    client.patch(f"/memory/{mid}", json={"tier": "long"})
    r = client.patch(f"/memory/{mid}", json={"status": "review"})
    assert r.status_code == 200
    assert r.json()["status"] == "review"


def test_patch_downgrade(client):
    """验证将 review/long 记忆降级为 short/active 的操作。"""
    resp = client.post("/memory", json={"title": "t", "content": "c"})
    mid = resp.json()["id"]
    client.patch(f"/memory/{mid}", json={"status": "active"})
    client.patch(f"/memory/{mid}", json={"tier": "long"})
    client.patch(f"/memory/{mid}", json={"status": "review"})
    r = client.patch(f"/memory/{mid}", json={"tier": "short"})
    assert r.status_code == 200
    assert r.json()["tier"] == "short"
    assert r.json()["status"] == "active"


def test_list_filter_by_tier(client):
    """验证 GET /memory?tier=... 能按 tier 筛选返回记忆。"""
    short_resp = client.post("/memory", json={"title": "s", "content": "c"})
    long_resp = client.post("/memory", json={"title": "l", "content": "c"})
    client.patch(f"/memory/{long_resp.json()['id']}", json={"tier": "long"})

    short_list = client.get("/memory?tier=short")
    long_list = client.get("/memory?tier=long")
    assert all(r["tier"] == "short" for r in short_list.json())
    assert all(r["tier"] == "long" for r in long_list.json())
