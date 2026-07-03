import os
os.environ["TESTING"] = "1"


def test_server_config_table_exists(engine):
    """server_config 表应在数据库中存在。"""
    from sqlalchemy import inspect
    inspector = inspect(engine)
    assert "server_config" in inspector.get_table_names()


def test_get_config_requires_auth(client_no_auth):
    """无 key 时 GET /config 应返回 401（数据库需存在活跃 key 才触发认证逻辑）。"""
    import hashlib
    from server.database import get_db
    from server.models import ApiKey
    from server.main import app

    sentinel_hash = hashlib.sha256(b"ct-sentinel-config-auth").hexdigest()
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    inserted = False
    if not db.query(ApiKey).filter(ApiKey.key_hash == sentinel_hash).first():
        db.add(ApiKey(key_hash=sentinel_hash, label="test-config-sentinel", is_admin=0, is_active=1))
        db.commit()
        inserted = True

    try:
        resp = client_no_auth.get("/config")
        assert resp.status_code == 401
    finally:
        if inserted:
            db.query(ApiKey).filter(ApiKey.key_hash == sentinel_hash).delete()
            db.commit()


def test_get_config_returns_three_keys(client):
    """GET /config 应返回 extractor 相关的三个配置项。"""
    from server.routers.config import seed_default_config
    from server.database import get_db
    from server.main import app
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    seed_default_config(db)

    resp = client.get("/config")
    assert resp.status_code == 200
    keys = {item["key"] for item in resp.json()}
    assert "extractor_api_key" in keys
    assert "extractor_base_url" in keys
    assert "extractor_model" in keys
