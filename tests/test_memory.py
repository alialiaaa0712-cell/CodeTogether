def test_create_memory(client):
    resp = client.post("/memory", json={
        "title": "数据库连接池配置",
        "content": "使用 SQLAlchemy pool_pre_ping=True 防止连接超时断开",
        "tags": "database,sqlalchemy,config"
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


from sqlalchemy import inspect


def test_create_memory_returns_score_fields(client):
    """验证创建记忆响应切换到 score 字段，并且不再暴露旧 hit 字段。

    参数:
        client: FastAPI 测试客户端，用于发起创建记忆请求。

    返回值:
        无返回值；通过断言响应结构验证新旧字段切换。
    """
    resp = client.post("/memory", json={
        "title": "记忆评分统计",
        "content": "新建记忆需要返回默认评分字段",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["score_total"] == 0
    assert data["feedback_count"] == 0
    assert data["last_feedback_at"] is None
    assert data["review_score"] is None
    assert "hit_count_7d" not in data
    assert "last_hit_at" not in data
    assert "review_hit_count" not in data


def test_memory_feedback_logs_and_search_exposures_tables_exist(engine):
    """验证测试库已创建反馈日志与搜索曝光表。

    参数:
        engine: 测试数据库引擎，用于检查表结构。

    返回值:
        无返回值；通过断言表名存在验证新增模型已被建表。
    """
    table_names = set(inspect(engine).get_table_names())

    assert "memory_feedback_logs" in table_names
    assert "memory_search_exposures" in table_names


def test_activate_memory(client):
    resp = client.post("/memory", json={"title": "测试知识", "content": "内容"})
    mem_id = resp.json()["id"]

    resp = client.patch(f"/memory/{mem_id}", json={"status": "active"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


def test_manual_post_memory_keeps_pending_after_startup_auto_activation(client):
    """验证手工创建记忆仍保持 pending，未被自动提炼启用逻辑改写。"""
    resp = client.post("/memory", json={
        "title": "手工记忆",
        "content": "这条记忆由人工创建，仍应保持 pending",
    })

    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    assert resp.json()["source_session_id"] is None


def test_manual_patch_activate_memory_sets_activated_at(client):
    """验证手工 pending->active 流转仍会写入 activated_at。"""
    created = client.post("/memory", json={
        "title": "手工激活",
        "content": "这条记忆通过人工确认启用",
    }).json()

    updated = client.patch(f"/memory/{created['id']}", json={"status": "active"})

    assert updated.status_code == 200
    assert updated.json()["status"] == "active"
    assert updated.json()["activated_at"] is not None


def test_get_memory_search_is_unavailable(client):
    """验证 GET /memory/search 已下线，避免继续暴露旧搜索入口。

    参数:
        client: FastAPI 测试客户端，用于请求旧搜索接口。

    返回值:
        无返回值；通过断言状态码验证接口不可用。
    """
    mem_resp = client.post("/memory", json={
        "title": "FastAPI 路由注册",
        "content": "使用 include_router 注册子路由",
        "tags": "fastapi"
    })
    client.patch(f"/memory/{mem_resp.json()['id']}", json={"status": "active"})

    resp = client.get("/memory/search?q=include_router")
    assert resp.status_code in (404, 405)


def test_post_search_returns_active_memories_without_mutating_score(client, db):
    """验证 POST /memory/search 只返回结果并记录曝光，不会直接改写积分字段。

    参数:
        client: FastAPI 测试客户端，用于构造会话、记忆与搜索请求。
        db: 测试数据库会话，用于准备长期记忆状态。

    返回值:
        无返回值；通过断言排序与 score 字段保持不变验证搜索语义。
    """
    from server.models import Memory as MemoryModel

    session = client.post("/agents", json={"id": "sess-search-score", "cwd": "/tmp/search-score"}).json()
    long_mem = client.post("/memory", json={
        "project_id": session["project_id"],
        "title": "长期规则",
        "content": "数据库连接池必须开启 pool_pre_ping",
    }).json()
    short_mem = client.post("/memory", json={
        "project_id": session["project_id"],
        "title": "短期规则",
        "content": "数据库 timeout 需要调大",
    }).json()
    client.patch(f"/memory/{long_mem['id']}", json={"status": "active"})
    client.patch(f"/memory/{short_mem['id']}", json={"status": "active"})

    long_row = db.get(MemoryModel, long_mem["id"])
    long_row.tier = "long"
    db.commit()

    resp = client.post("/memory/search", json={
        "query": "数据库",
        "session_id": "sess-search-score",
        "limit": 3,
    })

    assert resp.status_code == 200
    results = resp.json()
    assert [item["id"] for item in results] == [long_mem["id"], short_mem["id"]]
    assert [item["tier"] for item in results] == ["long", "short"]
    assert all(item["score_total"] == 0 for item in results)
    assert all(item["feedback_count"] == 0 for item in results)


def test_feedback_promotes_short_memory_to_review_at_positive_threshold(client, monkeypatch):
    """验证正向反馈累计达到阈值后，短期记忆会进入 review。"""
    monkeypatch.setattr("server.routers.memory._REVIEW_SCORE_THRESHOLD", 3, raising=False)
    session = client.post("/agents", json={"id": "sess-feedback-up", "cwd": "/tmp/feedback-up"}).json()
    memory = client.post("/memory", json={
        "project_id": session["project_id"],
        "title": "DDL 规则",
        "content": "MySQL 5.7 不支持该 DDL",
    }).json()
    client.patch(f"/memory/{memory['id']}", json={"status": "active"})

    search_resp = client.post("/memory/search", json={
        "query": "DDL",
        "session_id": "sess-feedback-up",
        "limit": 3,
    })
    assert search_resp.status_code == 200

    first = client.post(f"/memory/{memory['id']}/feedback", json={
        "session_id": "sess-feedback-up",
        "score": 2,
        "reason": "第一次确认了兼容性边界",
    })
    assert first.status_code == 200
    assert first.json()["status"] == "active"
    assert first.json()["score_total"] == 2

    second = client.post(f"/memory/{memory['id']}/feedback", json={
        "session_id": "sess-feedback-up",
        "score": 1,
        "reason": "再次帮助排除了错误方案",
    })

    assert second.status_code == 200
    assert second.json()["status"] == "review"
    assert second.json()["tier"] == "short"
    assert second.json()["review_reason"] == "score_threshold"
    assert second.json()["review_score"] == 3
    assert second.json()["score_total"] == 3
    assert second.json()["feedback_count"] == 2


def test_feedback_deletes_short_memory_at_negative_threshold(client, monkeypatch):
    """验证负向反馈累计达到阈值后，短期记忆会被直接删除。"""
    monkeypatch.setattr("server.routers.memory._DELETE_SCORE_THRESHOLD", -3, raising=False)
    session = client.post("/agents", json={"id": "sess-feedback-down", "cwd": "/tmp/feedback-down"}).json()
    memory = client.post("/memory", json={
        "project_id": session["project_id"],
        "title": "无效经验",
        "content": "这个结论后续被证明不成立",
    }).json()
    client.patch(f"/memory/{memory['id']}", json={"status": "active"})

    search_resp = client.post("/memory/search", json={
        "query": "结论",
        "session_id": "sess-feedback-down",
        "limit": 3,
    })
    assert search_resp.status_code == 200

    first = client.post(f"/memory/{memory['id']}/feedback", json={
        "session_id": "sess-feedback-down",
        "score": -2,
        "reason": "误导了定位",
    })
    assert first.status_code == 200
    assert first.json()["score_total"] == -2

    second = client.post(f"/memory/{memory['id']}/feedback", json={
        "session_id": "sess-feedback-down",
        "score": -1,
        "reason": "再次验证无用",
    })

    assert second.status_code == 200
    assert second.json()["id"] == memory["id"]
    listed = client.get("/memory?status=active").json()
    assert all(item["id"] != memory["id"] for item in listed)


def test_feedback_rejects_memory_not_exposed_to_session(client):
    """验证未被当前会话搜索曝光过的记忆不能直接提交反馈。"""
    session = client.post("/agents", json={"id": "sess-feedback-guard", "cwd": "/tmp/feedback-guard"}).json()
    memory = client.post("/memory", json={
        "project_id": session["project_id"],
        "title": "规则",
        "content": "只有搜索过的记忆才能反馈",
    }).json()
    client.patch(f"/memory/{memory['id']}", json={"status": "active"})

    resp = client.post(f"/memory/{memory['id']}/feedback", json={
        "session_id": "sess-feedback-guard",
        "score": 1,
        "reason": "不应该允许凭空评分",
    })

    assert resp.status_code == 400


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


def test_patch_to_review_rejects_pending(client):
    """验证 pending 状态的记忆也不能被手动标记为 review。"""
    resp = client.post("/memory", json={"title": "t", "content": "c"})
    mid = resp.json()["id"]
    r = client.patch(f"/memory/{mid}", json={"status": "review"})
    assert r.status_code == 400


def test_list_memories_filters_by_tier(client):
    """验证 GET /memory?tier=... 能按 tier 筛选返回记忆。

    参数:
        client: FastAPI 测试客户端，用于创建短期与长期记忆。

    返回值:
        无返回值；断言短期与长期列表过滤结果正确。
    """
    short_resp = client.post("/memory", json={"title": "s", "content": "c"})
    long_resp = client.post("/memory", json={"title": "l", "content": "长期记忆"})
    long_id = long_resp.json()["id"]
    client.patch(f"/memory/{short_resp.json()['id']}", json={"status": "active"})
    client.patch(f"/memory/{long_id}", json={"status": "active"})

    promote_resp = client.patch(f"/memory/{long_id}", json={"tier": "long"})
    assert promote_resp.status_code == 422

    short_list = client.get("/memory?tier=short")
    long_list = client.get("/memory?tier=long")
    assert any(r["id"] == short_resp.json()["id"] for r in short_list.json())
    assert all(r["tier"] == "short" for r in short_list.json())
    assert all(r["id"] != long_id for r in long_list.json())


def test_search_orders_by_score_total_then_feedback_count_then_updated_at(client, db):
    """验证搜索结果按 score_total desc, feedback_count desc, updated_at desc 排序。"""
    import time
    from server.models import Memory as MemoryModel

    session = client.post("/agents", json={"id": "sess-sort-order", "cwd": "/tmp/sort-order"}).json()
    project_id = session["project_id"]

    def make_mem(title):
        resp = client.post("/memory", json={"project_id": project_id, "title": title, "content": "数据库排序测试"}).json()
        client.patch(f"/memory/{resp['id']}", json={"status": "active"})
        return resp["id"]

    low_id = make_mem("低分记忆")
    mid_id = make_mem("中分记忆")
    high_id = make_mem("高分记忆")

    # 给高分记忆设置最旧的 updated_at，确保旧排序（只按 updated_at）会把它排最后
    # 新排序（score_total desc first）应把高分记忆排最前
    now = time.time()
    for mid, score, fc, ts in [
        (low_id, 0, 1, now),
        (mid_id, 1, 2, now - 10),
        (high_id, 3, 5, now - 100),
    ]:
        row = db.get(MemoryModel, mid)
        row.score_total = score
        row.feedback_count = fc
        row.updated_at = ts
        db.commit()

    resp = client.post("/memory/search", json={"query": "数据库排序测试", "session_id": "sess-sort-order", "limit": 10})
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert ids.index(high_id) < ids.index(mid_id) < ids.index(low_id)


def test_delete_memory_removes_pending_item(client):
    """验证 DELETE /memory/{id} 仍可删除 pending 记忆。

    参数:
        client: FastAPI 测试客户端，用于创建并删除待处理记忆。

    返回值:
        无返回值；断言删除后 pending 列表中不再包含目标记忆。
    """
    pending = client.post("/memory", json={"title": "待删除 pending", "content": "不要保留这条 pending 记忆"}).json()
    pending_delete = client.delete(f"/memory/{pending['id']}")
    pending_list = client.get("/memory?status=pending")

    assert pending_delete.status_code == 204
    assert all(item["id"] != pending["id"] for item in pending_list.json())
