from __future__ import annotations

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# 默认连接本地 MySQL，生产环境通过环境变量覆盖
DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:root@localhost:3306/codetogether")

# 模块导入时创建 engine；测试环境通过 conftest.py 的 dependency_overrides 绕过，
# 但 Task 10 的 Base.metadata.create_all(bind=engine) 需要 DATABASE_URL 指向 SQLite 或真实 MySQL。
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 依赖注入：提供数据库会话，请求结束后自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
