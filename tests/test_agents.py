from unittest import mock

from server.models import Memory, Message, Project, Session
from server.routers.agents import _trigger_extraction


def test_create_and_list_session(client):
    resp = client.post("/agents", json={"id": "sess-001", "cwd": "/home/user/project"})
    assert resp.status_code == 200

    resp = client.get("/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert any(a["id"] == "sess-001" for a in agents)


def test_update_session_status(client):
    client.post("/agents", json={"id": "sess-002"})
    resp = client.patch("/agents/sess-002/status", json={"status": "stopped"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


def test_update_parent(client):
    client.post("/agents", json={"id": "parent-001"})
    client.post("/agents", json={"id": "child-001"})
    resp = client.patch("/agents/child-001/parent", json={"parent_id": "parent-001"})
    assert resp.status_code == 200
    assert resp.json()["parent_id"] == "parent-001"


def test_update_model(client):
    """SessionStart hook 上报模型名称。"""
    client.post("/agents", json={"id": "sess-model-001"})
    resp = client.patch("/agents/sess-model-001/model", json={"model": "claude-opus-4-7"})
    assert resp.status_code == 200
    assert resp.json()["model"] == "claude-opus-4-7"


def test_update_notes(client):
    """用户添加备注。"""
    client.post("/agents", json={"id": "sess-notes-001"})
    resp = client.patch("/agents/sess-notes-001/notes", json={"notes": "这个 Agent 处理了登录模块重构"})
    assert resp.status_code == 200
    assert resp.json()["notes"] == "这个 Agent 处理了登录模块重构"


def test_create_session_infers_project_from_cwd_and_creates_project(client, db):
    """验证未显式提供 project_id 时，会根据 cwd 自动建项目。"""
    resp = client.post("/agents", json={
        "id": "sess-project-001",
        "cwd": "/Users/qinepan/Desktop/search/CodeTogether",
    })

    assert resp.status_code == 200
    data = resp.json()
    project = db.query(Project).filter(Project.id == data["project_id"]).one()
    assert data["project_id"] is not None
    assert project.name == "CodeTogether"


def test_create_session_backfills_project_id_when_existing_session_adds_cwd(client, db):
    """验证已存在会话补上 cwd 时，会同步回填 project_id。"""
    client.post("/agents", json={"id": "sess-project-backfill"})

    resp = client.post("/agents", json={
        "id": "sess-project-backfill",
        "cwd": "/tmp/a/CodeTogether",
    })

    assert resp.status_code == 200
    data = resp.json()
    db.expire_all()
    session = db.query(Session).filter(Session.id == "sess-project-backfill").one()
    project = db.query(Project).filter(Project.id == session.project_id).one()
    assert data["project_id"] is not None
    assert session.cwd == "/tmp/a/CodeTogether"
    assert session.project_id is not None
    assert project.repo_url == "/tmp/a/CodeTogether"
    assert project.name == "CodeTogether"


def test_create_session_does_not_merge_projects_with_same_basename_under_different_paths(client, db):
    """验证不同路径下同名目录不会错误复用同一个项目。"""
    first = client.post("/agents", json={
        "id": "sess-project-path-a",
        "cwd": "/tmp/a/CodeTogether",
    })
    second = client.post("/agents", json={
        "id": "sess-project-path-b",
        "cwd": "/tmp/b/CodeTogether",
    })

    assert first.status_code == 200
    assert second.status_code == 200

    first_data = first.json()
    second_data = second.json()
    assert first_data["project_id"] != second_data["project_id"]

    first_project = db.query(Project).filter(Project.id == first_data["project_id"]).one()
    second_project = db.query(Project).filter(Project.id == second_data["project_id"]).one()
    assert first_project.name == "CodeTogether"
    assert second_project.name == "CodeTogether"
    assert first_project.repo_url == "/tmp/a/CodeTogether"
    assert second_project.repo_url == "/tmp/b/CodeTogether"


def test_create_session_backfills_project_id_when_existing_session_already_has_cwd(client, db):
    """
    验证已存在会话已有 cwd 但缺 project_id 时，重复上报也会回填项目归属。

    参数:
        client: FastAPI 测试客户端，用于重复上报同一会话。
        db: 测试数据库会话，用于预置旧会话并校验回填结果。

    返回值:
        无返回值；通过断言 session 与 project 绑定关系验证回填逻辑。
    """
    db.add(Session(id="sess-project-existing-cwd", cwd="/tmp/existing/CodeTogether", project_id=None))
    db.commit()

    resp = client.post("/agents", json={
        "id": "sess-project-existing-cwd",
        "cwd": "/tmp/existing/CodeTogether",
    })

    assert resp.status_code == 200
    data = resp.json()
    db.expire_all()
    session = db.query(Session).filter(Session.id == "sess-project-existing-cwd").one()
    project = db.query(Project).filter(Project.id == session.project_id).one()
    assert data["project_id"] is not None
    assert session.project_id is not None
    assert project.repo_url == "/tmp/existing/CodeTogether"


def test_trigger_extraction_saves_active_short_memories_with_activation_time(db):
    """
    验证自动提炼出的短期记忆会直接启用，并保留积分零值。

    参数:
        db: 测试数据库会话，用于准备消息与校验记忆落库结果。

    返回值:
        无返回值；通过断言状态、层级、激活时间和积分字段验证行为。
    """
    session = Session(id="sess-extract-score", project_id="proj-1")
    db.add(session)
    db.add(Message(
        session_id="sess-extract-score",
        role="assistant",
        content="MySQL 5.7 不能使用该 DDL，否则会导致迁移失败",
        status="delivered",
    ))
    db.commit()

    returned_items = [
        {"project_id": "proj-1", "title": "DDL 约束", "content": "MySQL 5.7 不能使用该 DDL，否则会导致迁移失败", "tags": "mysql"},
    ]

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    with mock.patch("server.routers.agents.extract_memories", return_value=returned_items), \
         mock.patch("server.routers.agents.SessionLocal", return_value=db), \
         mock.patch("server.routers.agents.threading.Thread", ImmediateThread):
        _trigger_extraction("sess-extract-score", "proj-1")

    saved = db.query(Memory).filter(Memory.source_session_id == "sess-extract-score").one()
    assert saved.status == "active"
    assert saved.tier == "short"
    assert saved.activated_at is not None
    assert saved.project_id == "proj-1"
    assert saved.score_total == 0
    assert saved.feedback_count == 0


def test_trigger_extraction_backfills_project_from_session_cwd(db):
    """
    验证 session 缺 project_id 时，会按 cwd 补齐项目归属并写入记忆。

    参数:
        db: 测试数据库会话，用于准备缺项目归属的 session 和校验回填结果。

    返回值:
        无返回值；通过断言 session 与记忆共享同一 project_id 验证行为。
    """
    session = Session(
        id="sess-extract-cwd",
        project_id=None,
        cwd="/tmp/demo/CodeTogether",
    )
    db.add(session)
    db.add(Message(
        session_id="sess-extract-cwd",
        role="assistant",
        content="后续必须携带 access token，否则会导致接口失败",
        status="delivered",
    ))
    db.commit()

    returned_items = [
        {"project_id": None, "title": "鉴权约束", "content": "后续必须携带 access token，否则会导致接口失败", "tags": "auth"},
    ]

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    with mock.patch("server.routers.agents.extract_memories", return_value=returned_items), \
         mock.patch("server.routers.agents.SessionLocal", return_value=db), \
         mock.patch("server.routers.agents.threading.Thread", ImmediateThread):
        _trigger_extraction("sess-extract-cwd", None)

    db.expire_all()
    saved = db.query(Memory).filter(Memory.source_session_id == "sess-extract-cwd").one()
    refreshed_session = db.query(Session).filter(Session.id == "sess-extract-cwd").one()

    assert refreshed_session.project_id is not None
    assert saved.project_id == refreshed_session.project_id
    assert saved.status == "active"


def test_trigger_extraction_prefers_explicit_project_id_over_cwd(db):
    """
    验证调用方显式传入 project_id 时，不会被 session.cwd 推导结果覆盖。

    参数:
        db: 测试数据库会话，用于准备带 cwd 的 session 和校验最终归属。

    返回值:
        无返回值；通过断言记忆归属优先采用显式 project_id 验证优先级。
    """
    session = Session(
        id="sess-extract-explicit-project",
        project_id=None,
        cwd="/tmp/demo/CodeTogether",
    )
    db.add(session)
    db.add(Message(
        session_id="sess-extract-explicit-project",
        role="assistant",
        content="这里必须沿用显式项目归属，否则会导致跨项目串写",
        status="delivered",
    ))
    db.commit()

    returned_items = [
        {"project_id": None, "title": "项目归属", "content": "这里必须沿用显式项目归属，否则会导致跨项目串写", "tags": "project"},
    ]

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    with mock.patch("server.routers.agents.extract_memories", return_value=returned_items), \
         mock.patch("server.routers.agents.SessionLocal", return_value=db), \
         mock.patch("server.routers.agents.threading.Thread", ImmediateThread):
        _trigger_extraction("sess-extract-explicit-project", "proj-explicit")

    db.expire_all()
    saved = db.query(Memory).filter(Memory.source_session_id == "sess-extract-explicit-project").one()
    refreshed_session = db.query(Session).filter(Session.id == "sess-extract-explicit-project").one()

    assert saved.project_id == "proj-explicit"
    assert refreshed_session.project_id is None


def test_trigger_extraction_prefers_messages_and_limits_saved_memories(db):
    """验证提炼入口优先使用聊天消息摘要，并且最多落 3 条记忆。"""
    session = Session(id="sess-extract", project_id="proj-1")
    db.add(session)
    db.add_all([
        Message(session_id="sess-extract", role="user", content="这个项目不能跨项目执行命令", status="delivered"),
        Message(session_id="sess-extract", role="assistant", content="后续必须携带 access token", status="delivered"),
    ])
    db.commit()

    captured = {}
    returned_items = [
        {"project_id": "proj-1", "title": "A", "content": "规则 A", "tags": "a"},
        {"project_id": "proj-1", "title": "B", "content": "规则 B", "tags": "b"},
        {"project_id": "proj-1", "title": "C", "content": "规则 C", "tags": "c"},
        {"project_id": "proj-1", "title": "D", "content": "规则 D", "tags": "d"},
    ]

    def fake_extract(summary, project_id=None):
        captured["summary"] = summary
        captured["project_id"] = project_id
        return returned_items

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    with mock.patch("server.routers.agents.extract_memories", side_effect=fake_extract), \
         mock.patch("server.routers.agents.SessionLocal", return_value=db), \
         mock.patch("server.routers.agents.threading.Thread", ImmediateThread):
        _trigger_extraction("sess-extract", "proj-1")

    db.expire_all()
    saved = db.query(Memory).filter(Memory.source_session_id == "sess-extract").order_by(Memory.created_at.asc()).all()
    assert "user: 这个项目不能跨项目执行命令" in captured["summary"]
    assert "assistant: 后续必须携带 access token" in captured["summary"]
    assert captured["project_id"] == "proj-1"
    assert len(saved) == 3
    assert [item.title for item in saved] == ["A", "B", "C"]
