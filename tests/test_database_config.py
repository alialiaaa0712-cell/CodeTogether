import importlib
import sys


def test_database_url_can_be_loaded_from_dotenv(tmp_path, monkeypatch):
    """
    验证数据库模块在未显式 export 环境变量时，也能从项目根目录 .env 读取 DATABASE_URL。

    参数:
        tmp_path: pytest 提供的临时目录，用于构造隔离项目结构。
        monkeypatch: pytest 提供的环境与工作目录修改工具。

    返回值:
        无返回值；断言重新导入模块后 DATABASE_URL 与 engine.url 都来自 .env。
    """
    project_root = tmp_path / "project"
    server_dir = project_root / "server"
    server_dir.mkdir(parents=True)
    (server_dir / "__init__.py").write_text("", encoding="utf-8")
    (project_root / ".env").write_text(
        "DATABASE_URL=sqlite:///./dotenv-test.db\n",
        encoding="utf-8",
    )
    (server_dir / "database.py").write_text(
        (
            "from __future__ import annotations\n\n"
            "import os\n"
            "from pathlib import Path\n\n"
            "from dotenv import load_dotenv\n"
            "from sqlalchemy import create_engine\n"
            "from sqlalchemy.orm import DeclarativeBase, sessionmaker\n\n"
            "load_dotenv(Path(__file__).resolve().parent.parent / '.env')\n\n"
            "DATABASE_URL = os.getenv('DATABASE_URL', 'mysql+pymysql://root:root@localhost:3306/codetogether')\n"
            "engine = create_engine(DATABASE_URL, pool_pre_ping=True)\n"
            "SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)\n\n"
            "class Base(DeclarativeBase):\n"
            "    pass\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(project_root)
    monkeypatch.syspath_prepend(str(project_root))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sys.modules.pop("server.database", None)
    sys.modules.pop("server", None)

    module = importlib.import_module("server.database")

    assert module.DATABASE_URL == "sqlite:///./dotenv-test.db"
    assert str(module.engine.url) == "sqlite:///./dotenv-test.db"
