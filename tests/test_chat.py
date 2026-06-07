def test_send_message_session_not_found(client):
    """发送消息到不存在的会话应返回 404。"""
    resp = client.post("/chat", json={"session_id": "nonexistent-sess", "content": "hello"})
    assert resp.status_code == 404


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


def test_message_history_returns_recent_messages_in_desc_order(client):
    """
    验证聊天历史接口会按创建时间倒序返回指定会话最近的消息。

    参数:
        client: FastAPI 测试客户端，用于创建会话、发送消息并读取历史记录。

    返回值:
        无返回值；断言历史接口只返回目标会话消息，且最新消息排在最前面。
    """
    client.post("/agents", json={"id": "sess-chat-003"})
    client.post("/agents", json={"id": "sess-chat-004"})

    client.post("/chat", json={"session_id": "sess-chat-003", "content": "第一条消息"})
    client.post("/chat", json={"session_id": "sess-chat-003", "content": "第二条消息"})
    client.post("/chat", json={"session_id": "sess-chat-004", "content": "其他会话消息"})

    resp = client.get("/chat/sess-chat-003/history")
    assert resp.status_code == 200

    messages = resp.json()
    assert [message["content"] for message in messages[:2]] == ["第二条消息", "第一条消息"]
    assert all(message["session_id"] == "sess-chat-003" for message in messages)
