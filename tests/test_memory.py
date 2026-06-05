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
