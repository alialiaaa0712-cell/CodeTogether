import os
os.environ["TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient
from server.main import app
from server.routers.auth import get_current_key


def test_post_events_requires_auth(client_no_auth):
    """数据库存在活跃 key 时，无 Bearer Token 的写请求应返回 401。"""
    import hashlib
    from server.database import get_db
    from server.models import ApiKey

    sentinel_hash = hashlib.sha256(b"ct-sentinel-events-auth").hexdigest()
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    inserted = False
    if not db.query(ApiKey).filter(ApiKey.key_hash == sentinel_hash).first():
        sentinel = ApiKey(key_hash=sentinel_hash, label="test-sentinel", is_admin=0, is_active=1)
        db.add(sentinel)
        db.commit()
        db.refresh(sentinel)
        inserted = True

    try:
        resp = client_no_auth.post("/events", json={"session_id": "s1", "type": "pre_tool"})
        assert resp.status_code == 401
    finally:
        if inserted:
            db.query(ApiKey).filter(ApiKey.key_hash == sentinel_hash).delete()
            db.commit()


def test_admin_create_key(client_no_auth):
    """admin key 可创建新 key。"""
    import hashlib
    from server.database import get_db
    from server.models import ApiKey

    admin_key = "ct-testadminkey00000000000000000000000000000000000000000000000000000"
    key_hash = hashlib.sha256(admin_key.encode()).hexdigest()

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    existing = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if not existing:
        db.add(ApiKey(key_hash=key_hash, label="admin", is_admin=1, is_active=1))
        db.commit()

    resp = client_no_auth.post(
        "/admin/keys",
        json={"label": "alice"},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "key" in data
    assert data["key"].startswith("ct-")


def test_non_admin_cannot_create_key(client_no_auth):
    """普通 key 调用 /admin/keys 应返回 403。"""
    import hashlib
    from server.database import get_db
    from server.models import ApiKey

    plain = "ct-regularkey000000000000000000000000000000000000000000000000000000"
    key_hash = hashlib.sha256(plain.encode()).hexdigest()

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    existing = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if not existing:
        db.add(ApiKey(key_hash=key_hash, label="regular", is_admin=0, is_active=1))
        db.commit()

    resp = client_no_auth.post(
        "/admin/keys",
        json={"label": "bob"},
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert resp.status_code == 403


def test_invalid_key_returns_401(client_no_auth):
    """不存在于数据库的 key 应返回 401。"""
    resp = client_no_auth.post("/events", json={
        "session_id": "s1", "type": "pre_tool"
    }, headers={"Authorization": "Bearer ct-nonexistent000000000000000000000000000000000000000000000000000000"})
    assert resp.status_code == 401


def test_revoked_key_returns_401(client_no_auth):
    """已吊销（is_active=0）的 key 应返回 401。"""
    import hashlib
    from server.database import get_db
    from server.models import ApiKey

    plain = "ct-revokedkey000000000000000000000000000000000000000000000000000000"
    key_hash = hashlib.sha256(plain.encode()).hexdigest()

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    db.add(ApiKey(key_hash=key_hash, label="revoked", is_admin=0, is_active=0))
    db.commit()

    resp = client_no_auth.post("/events", json={
        "session_id": "s1", "type": "pre_tool"
    }, headers={"Authorization": f"Bearer {plain}"})
    assert resp.status_code == 401


def test_get_agents_requires_auth(client_no_auth):
    """无 key 时 GET /agents 应返回 401。"""
    resp = client_no_auth.get("/agents")
    assert resp.status_code == 401


def test_get_chat_history_requires_auth(client_no_auth):
    """无 key 时 GET /chat/{id}/history 应返回 401。"""
    resp = client_no_auth.get("/chat/nonexistent/history")
    assert resp.status_code == 401


def test_get_events_requires_auth(client_no_auth):
    """无 key 时 GET /events 应返回 401。"""
    resp = client_no_auth.get("/events")
    assert resp.status_code == 401


def test_get_memories_requires_auth(client_no_auth):
    """无 key 时 GET /memory/ 应返回 401。"""
    resp = client_no_auth.get("/memory/")
    assert resp.status_code == 401


def test_ws_invalid_key_rejected(client_no_auth):
    """
    携带无效 api_key 的 WebSocket 握手应被拒绝。
    数据库中需存在活跃 key，才会触发认证逻辑。

    参数:
        client_no_auth: 不跳过 get_current_key 的测试客户端 fixture。

    返回值:
        无；断言 rejected 为 True。
    """
    from starlette.testclient import WebSocketDisconnect
    import hashlib
    from server.database import get_db
    from server.models import ApiKey

    # 插入一条活跃 key，触发认证逻辑
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    sentinel_hash = hashlib.sha256(b"ct-sentinel-ws-test").hexdigest()
    sentinel_key = db.query(ApiKey).filter(ApiKey.key_hash == sentinel_hash).first()
    inserted = False
    if not sentinel_key:
        sentinel_key = ApiKey(key_hash=sentinel_hash, label="ws-test", is_admin=0, is_active=1)
        db.add(sentinel_key)
        db.commit()
        db.refresh(sentinel_key)
        inserted = True

    try:
        rejected = False
        try:
            with client_no_auth.websocket_connect("/ws?api_key=ct-invalid") as ws:
                data = ws.receive()
                # 服务端发送关闭帧
                if isinstance(data, dict) and data.get("type") == "websocket.close":
                    rejected = True
        except WebSocketDisconnect:
            rejected = True  # 服务端关闭连接时 TestClient 抛出此异常

        assert rejected, "无效 api_key 应被拒绝，但连接成功建立"
    finally:
        # 清理 sentinel key，避免污染后续测试
        if inserted:
            db.delete(db.merge(sentinel_key))
            db.commit()
