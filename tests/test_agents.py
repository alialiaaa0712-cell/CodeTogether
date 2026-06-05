def test_create_and_list_session(client):
    resp = client.post("/agents", json={"id": "sess-001", "cwd": "/home/user/project"})
    assert resp.status_code == 200

    resp = client.get("/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert any(a["id"] == "sess-001" for a in agents)

def test_update_session_status(client):
    client.post("/agents", json={"id": "sess-002"})
    resp = client.patch("/agents/sess-002/status", json={"status": "stopped"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"

def test_update_parent(client):
    client.post("/agents", json={"id": "parent-001"})
    client.post("/agents", json={"id": "child-001"})
    resp = client.patch("/agents/child-001/parent", json={"parent_id": "parent-001"})
    assert resp.status_code == 200
    assert resp.json()["parent_id"] == "parent-001"

def test_update_model(client):
    """SessionStart hook 上报模型名称。"""
    client.post("/agents", json={"id": "sess-model-001"})
    resp = client.patch("/agents/sess-model-001/model", json={"model": "claude-opus-4-7"})
    assert resp.status_code == 200
    assert resp.json()["model"] == "claude-opus-4-7"

def test_update_notes(client):
    """用户添加备注。"""
    client.post("/agents", json={"id": "sess-notes-001"})
    resp = client.patch("/agents/sess-notes-001/notes", json={"notes": "这个 Agent 处理了登录模块重构"})
    assert resp.status_code == 200
    assert resp.json()["notes"] == "这个 Agent 处理了登录模块重构"
