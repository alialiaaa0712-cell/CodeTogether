def test_send_and_poll_message(client):
    """手机发消息后，hook 轮询应取到该消息并标记为 delivered。"""
    client.post("/agents", json={"id": "sess-chat-001"})

    resp = client.post("/chat", json={"session_id": "sess-chat-001", "content": "请检查一下测试状态"})
    assert resp.status_code == 200
    msg_id = resp.json()["id"]
    assert resp.json()["status"] == "pending"

    resp = client.get("/chat/sess-chat-001/poll")
    assert resp.status_code == 200
    messages = resp.json()
    assert any(m["id"] == msg_id for m in messages)
    assert all(m["status"] == "delivered" for m in messages)


def test_poll_returns_empty_after_consumed(client):
    """消息取走后，再次轮询应返回空列表。"""
    client.post("/agents", json={"id": "sess-chat-002"})
    client.post("/chat", json={"session_id": "sess-chat-002", "content": "hello"})
    client.get("/chat/sess-chat-002/poll")

    resp = client.get("/chat/sess-chat-002/poll")
    assert resp.json() == []
