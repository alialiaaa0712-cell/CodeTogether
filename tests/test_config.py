import os
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from server.main import app


def test_server_config_table_exists(engine):
    """server_config 表应在数据库中存在。"""
    from sqlalchemy import inspect
    inspector = inspect(engine)
    assert "server_config" in inspector.get_table_names()


def test_get_config_requires_auth(client_no_auth):
    """无 key 时 GET /config 应返回 401。"""
    resp = client_no_auth.get("/config")
    assert resp.status_code == 401


def test_get_config_returns_three_keys(client):
    """GET /config 应返回 extractor 相关的三个配置项。"""
    resp = client.get("/config")
    assert resp.status_code == 200
    keys = {item["key"] for item in resp.json()}
    assert "extractor_api_key" in keys
    assert "extractor_base_url" in keys
    assert "extractor_model" in keys
