from server.models import Project, Session, Event, Message, Memory

def test_models_importable():
    """确认所有 ORM 模型可导入，表结构定义无误。"""
    assert Project.__tablename__ == "projects"
    assert Session.__tablename__ == "sessions"
    assert Event.__tablename__ == "events"
    assert Message.__tablename__ == "messages"
    assert Memory.__tablename__ == "memories"
