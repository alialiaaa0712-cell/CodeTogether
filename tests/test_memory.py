def test_create_memory(client):
    resp = client.post("/memory", json={
        "title": "数据库连接池配置",
        "content": "使用 SQLAlchemy pool_pre_ping=True 防止连接超时断开",
        "tags": "database,sqlalchemy,config"
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_create_memory_returns_hit_review_fields(client):
    """验证创建记忆的响应包含命中统计与复习相关字段的默认值。"""
    resp = client.post("/memory", json={
        "title": "记忆命中统计",
        "content": "新建记忆需要返回默认统计字段",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["hit_count_7d"] == 0
    assert data["last_hit_at"] is None
    assert data["review_reason"] is None
    assert data["review_hit_count"] is None


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


def test_patch_rejects_manual_review_transition(client):
    """验证接口不支持手动将记忆直接改成 review。"""
    resp = client.post("/memory", json={"title": "t", "content": "c"})
    mid = resp.json()["id"]
    client.patch(f"/memory/{mid}", json={"status": "active"})
    r = client.patch(f"/memory/{mid}", json={"status": "review"})
    assert r.status_code == 400


def test_patch_rejects_conflicting_status_and_tier_update(client):
    """验证 PATCH 同时传 status 与 tier 时会被拒绝，避免含糊流转。"""
    resp = client.post("/memory", json={"title": "t", "content": "c"})
    mid = resp.json()["id"]

    conflict = client.patch(f"/memory/{mid}", json={"status": "active", "tier": "long"})

    assert conflict.status_code == 400


def test_patch_rejects_downgrade_to_short(client, monkeypatch):
    """验证接口不支持把 review 记忆手动降级回 short。"""
    session_resp = client.post("/agents", json={
        "id": "sess-memory-no-downgrade",
        "cwd": "/tmp/memory-no-downgrade",
    })
    project_id = session_resp.json()["project_id"]
    resp = client.post("/memory", json={
        "project_id": project_id,
        "title": "t",
        "content": "这个规则必须先进入 review",
    })
    mid = resp.json()["id"]
    client.patch(f"/memory/{mid}", json={"status": "active"})
    monkeypatch.setattr("server.routers.memory._REVIEW_HIT_THRESHOLD", 1)
    client.get("/memory/search?q=必须&session_id=sess-memory-no-downgrade")

    r = client.patch(f"/memory/{mid}", json={"tier": "short"})
    assert r.status_code == 400



def test_patch_to_review_rejects_pending(client):
    """验证 pending 状态的记忆也不能被手动标记为 review。"""
    resp = client.post("/memory", json={"title": "t", "content": "c"})
    mid = resp.json()["id"]
    r = client.patch(f"/memory/{mid}", json={"status": "review"})
    assert r.status_code == 400


def test_list_memories_filters_by_tier(client, monkeypatch):
    """验证 GET /memory?tier=... 能按 tier 筛选返回记忆。"""
    short_resp = client.post("/memory", json={"title": "s", "content": "c"})
    session_resp = client.post("/agents", json={
        "id": "sess-memory-tier-filter",
        "cwd": "/tmp/memory-tier-filter",
    })
    project_id = session_resp.json()["project_id"]
    long_resp = client.post("/memory", json={
        "project_id": project_id,
        "title": "l",
        "content": "这个规则只能通过 review 晋升为长期",
    })
    long_id = long_resp.json()["id"]
    client.patch(f"/memory/{long_id}", json={"status": "active"})
    monkeypatch.setattr("server.routers.memory._REVIEW_HIT_THRESHOLD", 1)
    client.get("/memory/search?q=只能&session_id=sess-memory-tier-filter")
    client.patch(f"/memory/{long_id}", json={"tier": "long"})

    short_list = client.get("/memory?tier=short")
    long_list = client.get("/memory?tier=long")
    assert any(r["id"] == short_resp.json()["id"] for r in short_list.json())
    assert all(r["tier"] == "short" for r in short_list.json())
    assert any(r["id"] == long_id for r in long_list.json())
    assert all(r["tier"] == "long" for r in long_list.json())


def test_search_memory_prefers_session_project_over_project_id(client):
    """验证搜索接口优先按 session_id 解析项目范围，而不是调用方传入的 project_id。"""
    session_a = client.post("/agents", json={
        "id": "sess-memory-a",
        "cwd": "/tmp/memory-project-a",
    })
    session_b = client.post("/agents", json={
        "id": "sess-memory-b",
        "cwd": "/tmp/memory-project-b",
    })
    project_a = session_a.json()["project_id"]
    project_b = session_b.json()["project_id"]

    mem_a = client.post("/memory", json={
        "project_id": project_a,
        "title": "A 约束",
        "content": "当前项目必须使用 alpha token",
    }).json()
    mem_b = client.post("/memory", json={
        "project_id": project_b,
        "title": "B 约束",
        "content": "当前项目必须使用 beta token",
    }).json()

    client.patch(f"/memory/{mem_a['id']}", json={"status": "active"})
    client.patch(f"/memory/{mem_b['id']}", json={"status": "active"})

    resp = client.get(f"/memory/search?q=必须&session_id=sess-memory-a&project_id={project_b}")

    assert resp.status_code == 200
    results = resp.json()
    ids = [item["id"] for item in results]
    assert mem_a["id"] in ids
    assert mem_b["id"] not in ids


def test_short_active_memory_hit_count_enters_review_after_threshold(client, monkeypatch):
    """验证 active+short 记忆在 7 天窗口内累计命中后会进入 review。"""
    session_resp = client.post("/agents", json={
        "id": "sess-memory-hit",
        "cwd": "/tmp/memory-project-hit",
    })
    project_id = session_resp.json()["project_id"]
    memory = client.post("/memory", json={
        "project_id": project_id,
        "title": "接口约束",
        "content": "这个接口必须携带 access token",
    }).json()
    client.patch(f"/memory/{memory['id']}", json={"status": "active"})

    monkeypatch.setattr("server.routers.memory._REVIEW_HIT_THRESHOLD", 2)

    first = client.get("/memory/search?q=必须&session_id=sess-memory-hit")
    second = client.get("/memory/search?q=必须&session_id=sess-memory-hit")
    review_list = client.get("/memory?status=review")

    assert first.status_code == 200
    assert second.status_code == 200
    assert review_list.status_code == 200
    first_item = first.json()[0]
    assert first_item["hit_count_7d"] == 1
    assert first_item["status"] == "active"
    assert second.json() == []
    review_item = next(item for item in review_list.json() if item["id"] == memory["id"])
    assert review_item["hit_count_7d"] == 2
    assert review_item["status"] == "review"
    assert review_item["tier"] == "short"
    assert review_item["review_reason"] == "hit_threshold"
    assert review_item["review_hit_count"] == 2


def test_short_active_memory_hit_window_resets_after_7_days(client, monkeypatch, db):
    """验证超过 7 天未命中后，短期记忆的窗口计数会重新从 1 开始。"""
    session_resp = client.post("/agents", json={
        "id": "sess-memory-reset",
        "cwd": "/tmp/memory-project-reset",
    })
    project_id = session_resp.json()["project_id"]
    memory = client.post("/memory", json={
        "project_id": project_id,
        "title": "跨项目边界",
        "content": "这个命令不能跨项目执行",
    }).json()
    client.patch(f"/memory/{memory['id']}", json={"status": "active"})

    from server.models import Memory as MemoryModel

    row = db.get(MemoryModel, memory["id"])
    row.hit_count_7d = 5
    row.last_hit_at = 1000.0
    db.commit()

    monkeypatch.setattr("server.routers.memory.time.time", lambda: 1000.0 + 8 * 86400)
    resp = client.get("/memory/search?q=不能&session_id=sess-memory-reset")

    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["hit_count_7d"] == 1
    assert item["status"] == "active"


def test_patch_promotes_review_short_to_active_long(client, monkeypatch):
    """验证只有 review+short 记忆能通过 PATCH 晋升为 active+long。"""
    session_resp = client.post("/agents", json={
        "id": "sess-memory-promote",
        "cwd": "/tmp/memory-project-promote",
    })
    project_id = session_resp.json()["project_id"]
    memory = client.post("/memory", json={
        "project_id": project_id,
        "title": "插件边界",
        "content": "插件只能在主项目中加载",
    }).json()
    client.patch(f"/memory/{memory['id']}", json={"status": "active"})

    monkeypatch.setattr("server.routers.memory._REVIEW_HIT_THRESHOLD", 1)
    search_resp = client.get("/memory/search?q=只能&session_id=sess-memory-promote")
    assert search_resp.status_code == 200
    assert search_resp.json() == []

    review_list = client.get("/memory?status=review")
    assert review_list.status_code == 200
    assert any(item["id"] == memory["id"] for item in review_list.json())

    promote_resp = client.patch(f"/memory/{memory['id']}", json={"tier": "long"})

    assert promote_resp.status_code == 200
    data = promote_resp.json()
    assert data["status"] == "active"
    assert data["tier"] == "long"


def test_delete_memory_removes_pending_or_review_item(client, monkeypatch):
    """验证 DELETE /memory/{id} 可以删除 pending 和记入 review 队列的记忆。"""
    pending = client.post("/memory", json={"title": "待删除 pending", "content": "不要保留这条 pending 记忆"}).json()
    pending_delete = client.delete(f"/memory/{pending['id']}")
    pending_list = client.get("/memory?status=pending")

    assert pending_delete.status_code == 204
    assert all(item["id"] != pending["id"] for item in pending_list.json())

    session_resp = client.post("/agents", json={
        "id": "sess-memory-delete-review",
        "cwd": "/tmp/memory-project-delete-review",
    })
    project_id = session_resp.json()["project_id"]
    review_memory = client.post("/memory", json={
        "project_id": project_id,
        "title": "待删除 review",
        "content": "这个规则必须被确认后才能保留",
    }).json()
    client.patch(f"/memory/{review_memory['id']}", json={"status": "active"})
    monkeypatch.setattr("server.routers.memory._REVIEW_HIT_THRESHOLD", 1)
    client.get("/memory/search?q=必须&session_id=sess-memory-delete-review")

    review_delete = client.delete(f"/memory/{review_memory['id']}")
    review_list = client.get("/memory?status=review")

    assert review_delete.status_code == 204
    assert all(item["id"] != review_memory["id"] for item in review_list.json())
