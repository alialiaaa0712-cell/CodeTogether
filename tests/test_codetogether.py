import importlib
import json
from pathlib import Path



def import_codetogether():
    """
    重新加载命令行入口模块，确保每个用例拿到最新的 monkeypatch 状态。

    参数:
        无。

    返回值:
        重新加载后的模块对象。
    """
    import codetogether as m
    importlib.reload(m)
    return m



def test_register_mcp_server_writes_claude_json(monkeypatch, tmp_path):
    """
    验证注册 MCP server 会把 stdio 配置写入 Claude 用户级配置文件。

    参数:
        monkeypatch: pytest 提供的补丁工具。
        tmp_path: pytest 提供的临时目录。

    返回值:
        无返回值；通过断言配置文件中的 mcpServers 结构来验证行为。
    """
    claude_json = tmp_path / ".claude.json"
    m = import_codetogether()
    monkeypatch.setattr(m, "CLAUDE_CONFIG_PATH", claude_json)

    m._register_mcp_server()

    data = json.loads(claude_json.read_text())
    assert "codetogether-memory" in data["mcpServers"]
    server = data["mcpServers"]["codetogether-memory"]
    assert server["type"] == "stdio"
    assert server["command"]
    assert server["args"]
    assert server["env"]["CODETOGETHER_SERVER"] == "http://127.0.0.1:7879"



def test_register_mcp_server_is_idempotent(monkeypatch, tmp_path):
    """
    验证重复注册不会生成重复 server 条目。

    参数:
        monkeypatch: pytest 提供的补丁工具。
        tmp_path: pytest 提供的临时目录。

    返回值:
        无返回值；通过断言重复执行前后配置内容稳定来验证幂等性。
    """
    claude_json = tmp_path / ".claude.json"
    m = import_codetogether()
    monkeypatch.setattr(m, "CLAUDE_CONFIG_PATH", claude_json)

    m._register_mcp_server()
    first = json.loads(claude_json.read_text())
    m._register_mcp_server()
    second = json.loads(claude_json.read_text())

    assert list(first["mcpServers"].keys()) == ["codetogether-memory"]
    assert second == first



def test_register_mcp_server_preserves_existing_settings(monkeypatch, tmp_path):
    """
    验证注册 MCP 时会保留已有的 hooks、env 与其他 MCP server 配置。

    参数:
        monkeypatch: pytest 提供的补丁工具。
        tmp_path: pytest 提供的临时目录。

    返回值:
        无返回值；通过断言已有配置未被覆盖来验证增量写入策略。
    """
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps({
        "env": {"EXISTING": "1"},
        "hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "echo stop"}]}]},
        "mcpServers": {
            "existing-server": {
                "type": "stdio",
                "command": "python3",
                "args": ["/tmp/existing.py"],
            }
        },
    }, ensure_ascii=False))

    m = import_codetogether()
    monkeypatch.setattr(m, "CLAUDE_CONFIG_PATH", claude_json)

    m._register_mcp_server()

    data = json.loads(claude_json.read_text())
    assert data["env"]["EXISTING"] == "1"
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo stop"
    assert "existing-server" in data["mcpServers"]
    assert "codetogether-memory" in data["mcpServers"]
