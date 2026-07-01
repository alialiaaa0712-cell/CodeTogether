#!/usr/bin/env python3
"""codetogether init — 一键注册 Claude Code hooks，并启动本地服务。"""
import json
import os
import subprocess
import sys
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CLAUDE_CONFIG_PATH = Path.home() / ".claude.json"
HOOKS_DIR = Path(__file__).resolve().parent / "hooks"
MCP_SERVER_PATH = Path(__file__).resolve().parent / "mcp_server" / "server.py"
SERVER_MODULE = "server.main:app"
DEFAULT_PORT = 7879


def _load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text())
        except Exception:
            pass
    return {}



def _save_settings(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))



def _load_claude_config() -> dict:
    """
    读取 Claude 用户级配置文件，供 MCP server 注册使用。

    参数:
        无。

    返回值:
        已解析的配置字典；若文件不存在或损坏则返回空字典。
    """
    if CLAUDE_CONFIG_PATH.exists():
        try:
            return json.loads(CLAUDE_CONFIG_PATH.read_text())
        except Exception:
            pass
    return {}



def _save_claude_config(data: dict) -> None:
    """
    写回 Claude 用户级配置文件，保留其他顶层字段。

    参数:
        data: 要持久化的 Claude 配置字典。

    返回值:
        无。
    """
    CLAUDE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _hook_command(script: str) -> str:
    return f"python3 {HOOKS_DIR / script}"



def _mcp_server_config() -> dict:
    """
    生成 CodeTogether 记忆 MCP server 的 Claude 配置片段。

    参数:
        无。

    返回值:
        可直接写入 `mcpServers.codetogether-memory` 的配置字典。
    """
    import os
    env: dict = {
        "CODETOGETHER_SERVER": f"http://127.0.0.1:{DEFAULT_PORT}",
    }
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if session_id:
        env["CLAUDE_SESSION_ID"] = session_id
    return {
        "type": "stdio",
        "command": sys.executable,
        "args": [str(MCP_SERVER_PATH)],
        "env": env,
    }



def _register_hooks() -> None:
    data = _load_settings()
    hooks = data.setdefault("hooks", {})

    for event, script in [
        ("PreToolUse", "pre_tool.py"),
        ("PostToolUse", "post_tool.py"),
        ("Stop", "stop.py"),
    ]:
        cmd = _hook_command(script)
        entries = hooks.setdefault(event, [])
        # 已注册则跳过
        if any(
            h.get("command") == cmd
            for entry in entries
            for h in entry.get("hooks", [])
        ):
            print(f"  {event}: already registered")
            continue
        entries.append({"matcher": "", "hooks": [{"type": "command", "command": cmd}]})
        print(f"  {event}: registered")

    data.setdefault("env", {})["CODETOGETHER_SERVER"] = f"http://127.0.0.1:{DEFAULT_PORT}"
    _save_settings(data)



def _register_mcp_server() -> None:
    """
    将 CodeTogether 记忆 MCP server 注册到 Claude 用户级配置中。

    参数:
        无。

    返回值:
        无。
    """
    data = _load_claude_config()
    mcp_servers = data.setdefault("mcpServers", {})
    server_name = "codetogether-memory"
    existing = mcp_servers.get(server_name)
    desired = _mcp_server_config()

    if existing == desired:
        print("  MCP: already registered")
        return

    mcp_servers[server_name] = desired
    _save_claude_config(data)
    print("  MCP: registered")


def cmd_init(args):
    print("=== CodeTogether Init ===")
    print(f"\n[1/2] Registering hooks in {SETTINGS_PATH}")
    _register_hooks()

    print(f"\n[2/2] Registering MCP server in {CLAUDE_CONFIG_PATH}")
    _register_mcp_server()

    # --no-start: VSCode 插件模式，只注册不启动 server（server 由插件管理）
    if getattr(args, "no_start", False):
        print("\nInit complete (server not started, managed by VSCode extension).")
        return

    print(f"\n[3/3] Starting server on port {DEFAULT_PORT}")
    print("      Press Ctrl+C to stop.\n")
    try:
        subprocess.run(
            [sys.executable, "-m", "uvicorn", SERVER_MODULE, "--port", str(DEFAULT_PORT)],
            cwd=Path(__file__).resolve().parent,
        )
    except KeyboardInterrupt:
        print("\nServer stopped.")


LAUNCHD_PLIST_TEMPLATE = Path(__file__).resolve().parent / "com.codetogether.server.plist"
LAUNCHD_PLIST_DST = Path.home() / "Library" / "LaunchAgents" / "com.codetogether.server.plist"


def cmd_install_service(args):
    """将 launchd plist 安装到 ~/Library/LaunchAgents，开机自动启动服务。"""
    project_dir = str(Path(__file__).resolve().parent)
    content = LAUNCHD_PLIST_TEMPLATE.read_text().replace("CODETOGETHER_DIR", project_dir)
    LAUNCHD_PLIST_DST.parent.mkdir(parents=True, exist_ok=True)
    LAUNCHD_PLIST_DST.write_text(content)
    subprocess.run(["launchctl", "load", str(LAUNCHD_PLIST_DST)], check=False)
    print(f"Service installed. Log: /tmp/codetogether.log")


def cmd_uninstall_service(args):
    """卸载 launchd 服务。"""
    if LAUNCHD_PLIST_DST.exists():
        subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST_DST)], check=False)
        LAUNCHD_PLIST_DST.unlink()
        print("Service uninstalled.")
    else:
        print("Service not installed.")


def cmd_start(args):
    subprocess.run(
        [sys.executable, "-m", "uvicorn", SERVER_MODULE, "--port", str(DEFAULT_PORT)],
        cwd=Path(__file__).resolve().parent,
    )


def main():
    import argparse
    parser = argparse.ArgumentParser(prog="codetogether")
    sub = parser.add_subparsers(dest="cmd")
    init_parser = sub.add_parser("init", help="Register hooks and start server")
    init_parser.add_argument("--no-start", action="store_true", help="Only register hooks/MCP, do not start server")
    sub.add_parser("start", help="Start server only")
    sub.add_parser("install-service", help="Install launchd service (auto-start on login)")
    sub.add_parser("uninstall-service", help="Uninstall launchd service")

    args = parser.parse_args()
    if args.cmd == "init" or args.cmd is None:
        cmd_init(args)
    elif args.cmd == "start":
        cmd_start(args)
    elif args.cmd == "install-service":
        cmd_install_service(args)
    elif args.cmd == "uninstall-service":
        cmd_uninstall_service(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
