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
