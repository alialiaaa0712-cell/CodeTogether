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


def test_extractor_reads_db_config(client, engine):
    """extractor 应从数据库读取配置，优先于环境变量。"""
    from server.services import extractor as _extractor
    from unittest.mock import patch
    from sqlalchemy.orm import sessionmaker
    from server.models import ServerConfig as ServerConfigModel

    # 向数据库写入测试配置
    Session = sessionmaker(bind=engine)
    db = Session()
    db.merge(ServerConfigModel(key="extractor_api_key", value="db-api-key"))
    db.merge(ServerConfigModel(key="extractor_base_url", value="https://db.example.com/v1"))
    db.merge(ServerConfigModel(key="extractor_model", value="db-model"))
    db.commit()
    db.close()

    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop here")

    # 将 SessionLocal patch 为测试引擎的 session，确保 extract_memories 读到测试数据库
    TestSession = sessionmaker(bind=engine)
    with patch("server.services.extractor.SessionLocal", TestSession), \
         patch("server.services.extractor.OpenAI", side_effect=fake_openai):
        try:
            _extractor.extract_memories("test summary")
        except Exception:
            pass

    assert captured.get("api_key") == "db-api-key"
    assert captured.get("base_url") == "https://db.example.com/v1"


def test_put_config_requires_admin(client):
    """非 admin key 调用 PUT /config 应返回 403。"""
    resp = client.put("/config", json={"extractor_model": "new-model"})
    assert resp.status_code == 403


def test_put_config_admin_success(client_no_auth):
    """admin key 调用 PUT /config 应成功。"""
    import hashlib
    from server.database import get_db
    from server.models import ApiKey
    from server.main import app

    admin_key = "ct-testadminkey00000000000000000000000000000000000000000000000000000"
    key_hash = hashlib.sha256(admin_key.encode()).hexdigest()

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    if not db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first():
        db.add(ApiKey(key_hash=key_hash, label="admin", is_admin=1, is_active=1))
        db.commit()

    resp = client_no_auth.put(
        "/config",
        json={"extractor_model": "test-model"},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
