import os
os.environ["TESTING"] = "1"


def test_server_config_table_exists(engine):
    """server_config 表应在数据库中存在。"""
    from sqlalchemy import inspect
    inspector = inspect(engine)
    assert "server_config" in inspector.get_table_names()
