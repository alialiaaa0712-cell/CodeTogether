#!/usr/bin/env python3
"""codetogether init — 一键注册 Claude Code hooks，并启动本地服务。"""
import json
import os
import subprocess
import sys
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
HOOKS_DIR = Path(__file__).resolve().parent / "hooks"
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


def _hook_command(script: str) -> str:
    return f"python3 {HOOKS_DIR / script}"


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


def cmd_init(args):
    print("=== CodeTogether Init ===")
    print(f"\n[1/2] Registering hooks in {SETTINGS_PATH}")
    _register_hooks()

    print(f"\n[2/2] Starting server on port {DEFAULT_PORT}")
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
    sub.add_parser("init", help="Register hooks and start server")
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
