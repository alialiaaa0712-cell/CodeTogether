def test_post_and_list_event(client):
    """上报事件后，GET /events 应返回该事件。"""
    client.post("/agents", json={"id": "sess-evt-001"})
    resp = client.post("/events", json={
        "session_id": "sess-evt-001",
        "type": "pre_tool",
        "tool_name": "Bash",
        "input": {"command": "ls"}
    })
    assert resp.status_code == 200
    event_id = resp.json()["id"]

    resp = client.get("/events?session_id=sess-evt-001")
    assert resp.status_code == 200
    ids = [e["id"] for e in resp.json()]
    assert event_id in ids

def test_event_auto_creates_session(client):
    """上报不存在会话的事件时，自动创建会话。"""
    resp = client.post("/events", json={
        "session_id": "auto-created-sess",
        "type": "pre_tool",
        "tool_name": "Read"
    })
    assert resp.status_code == 200
