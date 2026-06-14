import os
os.environ["TESTING"] = "1"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from server.database import Base, get_db
from server.main import app
from server.routers.auth import get_current_key
from fastapi.testclient import TestClient

# 使用 SQLite 内存数据库，避免依赖 MySQL
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(scope="session")
def engine():
    eng = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng

@pytest.fixture
def db(engine):
    TestingSessionLocal = sessionmaker(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def client(engine):
    from server.models import ApiKey
    TestingSessionLocal = sessionmaker(bind=engine)
    # 清空 ApiKey 表，防止其他测试遗留的活跃 key 影响 WS 认证逻辑
    with TestingSessionLocal() as s:
        s.query(ApiKey).delete()
        s.commit()
    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()
    app.dependency_overrides[get_db] = override_get_db
    # 测试中跳过 auth 验证，返回 None 表示已认证（非 admin 路由可接受）
    app.dependency_overrides[get_current_key] = lambda: None
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """返回空认证头，测试中已通过 dependency_overrides 跳过 auth 验证。"""
    return {}


