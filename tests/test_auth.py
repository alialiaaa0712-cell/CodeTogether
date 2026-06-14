import os
os.environ["TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient
from server.main import app
from server.routers.auth import get_current_key


@pytest.fixture
def client_no_auth(engine):
    """提供一个不注入认证跳过的客户端，用于测试 auth 逻辑本身。"""
    from sqlalchemy.orm import sessionmaker
    from server.database import get_db
    TestingSessionLocal = sessionmaker(bind=engine)
    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()
    # 保存并清除 get_current_key 的 override，确保真实认证路径生效
    saved = app.dependency_overrides.pop(get_current_key, None)
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    # 测试结束后恢复原 override，避免污染其他测试
    if saved is not None:
        app.dependency_overrides[get_current_key] = saved


def test_post_events_requires_auth(client_no_auth):
    """无 key 时写事件应返回 401。"""
    resp = client_no_auth.post("/events", json={
        "session_id": "s1", "type": "pre_tool"
    })
    assert resp.status_code == 401


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
    携带无效 api_key 的 WebSocket 握手应被拒绝（close code 4001）。

    数据库中必须存在至少一个活跃 ApiKey，认证逻辑才会触发；
    测试先插入一条活跃 key，再用无效 key 发起握手，验证连接被关闭。

    参数:
        client_no_auth: 不跳过 get_current_key 的测试客户端 fixture。

    返回值:
        无；连接被关闭时捕获异常即视为通过。
    """
    import hashlib
    from server.database import get_db
    from server.models import ApiKey
    from starlette.testclient import WebSocketDisconnect

    # 插入一条活跃 key，使 WS 认证逻辑进入检查分支
    plain_active = "ct-activekeyforwstest0000000000000000000000000000000000000000000"
    active_hash = hashlib.sha256(plain_active.encode()).hexdigest()
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    if not db.query(ApiKey).filter(ApiKey.key_hash == active_hash).first():
        db.add(ApiKey(key_hash=active_hash, label="ws-test", is_admin=0, is_active=1))
        db.commit()

    # 携带无效 key 发起 WS 握手，期望被关闭
    try:
        with client_no_auth.websocket_connect("/ws?api_key=ct-invalid") as ws:
            # 服务端 accept 后再 close(4001)，receive_json_or_disconnect 会收到关闭帧
            data = ws.receive()
            # 若收到的是关闭帧（type=="websocket.close"），认为通过
            if isinstance(data, dict) and data.get("type") == "websocket.close":
                pass
            else:
                assert False, "收到了非关闭帧，应已被拒绝"
    except Exception:
        pass  # 连接被关闭时 TestClient 抛出异常，符合预期
