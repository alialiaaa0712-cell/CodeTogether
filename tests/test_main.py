from sqlalchemy import create_engine, inspect, text



def test_migrate_memories_adds_missing_review_reason_column(monkeypatch, tmp_path):
    """
    验证旧 memories 表缺少 review_reason 时，启动迁移会自动补齐该列。

    参数:
        monkeypatch: pytest 提供的补丁工具，用于替换 main 模块中的 engine。
        tmp_path: pytest 提供的临时目录，用于创建隔离数据库文件。

    返回值:
        无返回值；通过断言迁移后列集合包含 review_reason 来验证行为。
    """
    import server.main as main

    db_path = tmp_path / "migrate-memories.db"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE memories (
                id VARCHAR(36) PRIMARY KEY,
                project_id VARCHAR(36) NULL,
                title VARCHAR(512) NOT NULL,
                content TEXT NOT NULL,
                tags VARCHAR(512) NULL,
                status VARCHAR(32) NULL,
                tier VARCHAR(32) NOT NULL,
                updated_at DOUBLE NULL,
                source_session_id VARCHAR(36) NULL,
                created_at DOUBLE NULL,
                activated_at DOUBLE NULL,
                score_total INT NOT NULL DEFAULT 0,
                feedback_count INT NOT NULL DEFAULT 0,
                last_feedback_at DOUBLE NULL,
                review_score INT NULL
            )
            """
        ))

    monkeypatch.setattr(main, "engine", engine)

    main._migrate_memories_to_score_fields()

    columns = {column["name"] for column in inspect(engine).get_columns("memories")}
    assert "review_reason" in columns


def test_activate_short_pending_memories_backfills_project_id(monkeypatch, tmp_path):
    """
    验证启动修复会启用短期 pending 记忆，并补齐项目归属。

    参数:
        monkeypatch: pytest 提供的补丁工具，用于替换 main 模块中的 engine。
        tmp_path: pytest 提供的临时目录，用于构造隔离数据库文件。

    返回值:
        无返回值；通过断言记忆状态、项目归属与激活时间验证修复结果。
    """
    import server.main as main

    db_path = tmp_path / "repair-memories.db"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE projects (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255),
                repo_url VARCHAR(512),
                created_at DOUBLE
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE sessions (
                id VARCHAR(36) PRIMARY KEY,
                project_id VARCHAR(36) NULL,
                parent_id VARCHAR(36) NULL,
                status VARCHAR(32),
                cwd VARCHAR(512),
                model VARCHAR(128),
                notes TEXT,
                started_at DOUBLE,
                ended_at DOUBLE NULL
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE memories (
                id VARCHAR(36) PRIMARY KEY,
                project_id VARCHAR(36) NULL,
                title VARCHAR(512) NOT NULL,
                content TEXT NOT NULL,
                tags VARCHAR(512) NULL,
                status VARCHAR(32) NULL,
                tier VARCHAR(32) NOT NULL,
                updated_at DOUBLE NULL,
                source_session_id VARCHAR(36) NULL,
                created_at DOUBLE NULL,
                activated_at DOUBLE NULL,
                score_total INT NOT NULL DEFAULT 0,
                feedback_count INT NOT NULL DEFAULT 0,
                last_feedback_at DOUBLE NULL,
                review_score INT NULL,
                review_reason VARCHAR(255) NULL
            )
            """
        ))
        conn.execute(text(
            "INSERT INTO sessions (id, project_id, status, cwd, started_at) VALUES ('sess-1', NULL, 'stopped', '/tmp/demo/CodeTogether', 1)"
        ))
        conn.execute(text(
            "INSERT INTO memories (id, project_id, title, content, status, tier, source_session_id, created_at, updated_at, score_total, feedback_count) VALUES ('mem-1', NULL, '规则', '这里不能跳过 access token，否则会导致失败', 'pending', 'short', 'sess-1', 1, 1, 0, 0)"
        ))

    monkeypatch.setattr(main, "engine", engine)

    main._activate_short_pending_memories()

    with engine.connect() as conn:
        memory_row = conn.execute(text("SELECT status, tier, project_id, activated_at FROM memories WHERE id='mem-1'")) .fetchone()
        session_row = conn.execute(text("SELECT project_id FROM sessions WHERE id='sess-1'")) .fetchone()

    assert memory_row[0] == "active"
    assert memory_row[1] == "short"
    assert memory_row[2] is not None
    assert memory_row[2] == session_row[0]
    assert memory_row[3] is not None


def test_activate_short_pending_memories_keeps_active_without_project_when_session_cannot_resolve(monkeypatch, tmp_path):
    """
    验证无法反推出项目时，历史短期 pending 记忆仍会被启用。

    参数:
        monkeypatch: pytest 提供的补丁工具，用于替换 main 模块中的 engine。
        tmp_path: pytest 提供的临时目录，用于构造隔离数据库文件。

    返回值:
        无返回值；通过断言状态变为 active 且 project_id 保持为空验证降级行为。
    """
    import server.main as main

    db_path = tmp_path / "repair-memories-no-project.db"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE projects (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255),
                repo_url VARCHAR(512),
                created_at DOUBLE
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE sessions (
                id VARCHAR(36) PRIMARY KEY,
                project_id VARCHAR(36) NULL,
                parent_id VARCHAR(36) NULL,
                status VARCHAR(32),
                cwd VARCHAR(512),
                model VARCHAR(128),
                notes TEXT,
                started_at DOUBLE,
                ended_at DOUBLE NULL
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE memories (
                id VARCHAR(36) PRIMARY KEY,
                project_id VARCHAR(36) NULL,
                title VARCHAR(512) NOT NULL,
                content TEXT NOT NULL,
                tags VARCHAR(512) NULL,
                status VARCHAR(32) NULL,
                tier VARCHAR(32) NOT NULL,
                updated_at DOUBLE NULL,
                source_session_id VARCHAR(36) NULL,
                created_at DOUBLE NULL,
                activated_at DOUBLE NULL,
                score_total INT NOT NULL DEFAULT 0,
                feedback_count INT NOT NULL DEFAULT 0,
                last_feedback_at DOUBLE NULL,
                review_score INT NULL,
                review_reason VARCHAR(255) NULL
            )
            """
        ))
        conn.execute(text(
            "INSERT INTO sessions (id, project_id, status, cwd, started_at) VALUES ('sess-2', NULL, 'stopped', NULL, 1)"
        ))
        conn.execute(text(
            "INSERT INTO memories (id, project_id, title, content, status, tier, source_session_id, created_at, updated_at, score_total, feedback_count) VALUES ('mem-2', NULL, '规则', '这里不能跳过 access token，否则会导致失败', 'pending', 'short', 'sess-2', 1, 1, 0, 0)"
        ))

    monkeypatch.setattr(main, "engine", engine)

    main._activate_short_pending_memories()

    with engine.connect() as conn:
        memory_row = conn.execute(text("SELECT status, project_id, activated_at FROM memories WHERE id='mem-2'")) .fetchone()

    assert memory_row[0] == "active"
    assert memory_row[1] is None
    assert memory_row[2] is not None


def test_activate_short_pending_memories_is_idempotent(monkeypatch, tmp_path):
    """
    验证启动修复可重复执行，不会污染已处理数据。

    参数:
        monkeypatch: pytest 提供的补丁工具，用于替换 main 模块中的 engine。
        tmp_path: pytest 提供的临时目录，用于构造隔离数据库文件。

    返回值:
        无返回值；通过断言记录数量和状态保持稳定验证幂等性。
    """
    import server.main as main

    db_path = tmp_path / "repair-memories-idempotent.db"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE projects (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255),
                repo_url VARCHAR(512),
                created_at DOUBLE
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE sessions (
                id VARCHAR(36) PRIMARY KEY,
                project_id VARCHAR(36) NULL,
                parent_id VARCHAR(36) NULL,
                status VARCHAR(32),
                cwd VARCHAR(512),
                model VARCHAR(128),
                notes TEXT,
                started_at DOUBLE,
                ended_at DOUBLE NULL
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE memories (
                id VARCHAR(36) PRIMARY KEY,
                project_id VARCHAR(36) NULL,
                title VARCHAR(512) NOT NULL,
                content TEXT NOT NULL,
                tags VARCHAR(512) NULL,
                status VARCHAR(32) NULL,
                tier VARCHAR(32) NOT NULL,
                updated_at DOUBLE NULL,
                source_session_id VARCHAR(36) NULL,
                created_at DOUBLE NULL,
                activated_at DOUBLE NULL,
                score_total INT NOT NULL DEFAULT 0,
                feedback_count INT NOT NULL DEFAULT 0,
                last_feedback_at DOUBLE NULL,
                review_score INT NULL,
                review_reason VARCHAR(255) NULL
            )
            """
        ))
        conn.execute(text(
            "INSERT INTO sessions (id, project_id, status, cwd, started_at) VALUES ('sess-1', 'proj-1', 'stopped', '/tmp/demo/CodeTogether', 1)"
        ))
        conn.execute(text(
            "INSERT INTO memories (id, project_id, title, content, status, tier, source_session_id, created_at, updated_at, activated_at, score_total, feedback_count) VALUES ('mem-1', 'proj-1', '规则', '这里不能跳过 access token，否则会导致失败', 'active', 'short', 'sess-1', 1, 1, 2, 0, 0)"
        ))

    monkeypatch.setattr(main, "engine", engine)

    main._activate_short_pending_memories()
    main._activate_short_pending_memories()

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT COUNT(*) FROM memories WHERE id='mem-1'")) .fetchone()
        status = conn.execute(text("SELECT status FROM memories WHERE id='mem-1'")) .fetchone()

    assert rows[0] == 1
    assert status[0] == "active"
