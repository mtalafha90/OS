from __future__ import annotations

import os
import subprocess

from .registry import tool


@tool(
    name="list_processes",
    description="List running processes. Optionally filter by name.",
    properties={
        "filter_name": {
            "type": "string",
            "description": "Filter processes whose name contains this string",
        },
        "show_all": {
            "type": "boolean",
            "description": "Show all users' processes (default: current user only)",
        },
    },
    required=[],
)
def list_processes(filter_name: str | None = None, show_all: bool = False) -> str:
    try:
        import psutil

        procs = []
        for p in psutil.process_iter(
            ["pid", "name", "username", "cpu_percent", "memory_info", "status", "cmdline"]
        ):
            try:
                info = p.info
                if not show_all and info["username"] != os.environ.get("USER"):
                    pass  # still show all by default
                if filter_name and filter_name.lower() not in (info["name"] or "").lower():
                    continue
                cmd = " ".join(info["cmdline"] or [info["name"] or ""])[:60]
                mem = (info["memory_info"].rss // 1024 // 1024) if info["memory_info"] else 0
                procs.append(
                    f"{info['pid']:>6}  {info['name']:<20}  {info['cpu_percent']:>5.1f}%  "
                    f"{mem:>5}MB  {info['status']:<10}  {cmd}"
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        header = f"{'PID':>6}  {'NAME':<20}  {'CPU':>6}  {'MEM':>7}  {'STATUS':<10}  COMMAND"
        sep = "-" * 80
        return "\n".join([header, sep] + procs) if procs else "No processes found."

    except ImportError:
        result = subprocess.run(
            ["ps", "aux" if show_all else "ux"], capture_output=True, text=True, timeout=10
        )
        if filter_name:
            lines = result.stdout.splitlines()
            filtered = [lines[0]] + [ln for ln in lines[1:] if filter_name.lower() in ln.lower()]
            return "\n".join(filtered)
        return result.stdout


@tool(
    name="kill_process",
    description="Send a signal to a process by PID. Default signal is SIGTERM (15).",
    properties={
        "pid": {"type": "integer", "description": "Process ID to signal"},
        "signal_num": {
            "type": "integer",
            "description": "Signal number (default: 15=SIGTERM, 9=SIGKILL)",
        },
    },
    required=["pid"],
)
def kill_process(pid: int, signal_num: int = 15) -> str:
    try:
        os.kill(pid, signal_num)
        sig_name = {15: "SIGTERM", 9: "SIGKILL", 1: "SIGHUP", 2: "SIGINT"}.get(
            signal_num, str(signal_num)
        )
        return f"Sent {sig_name} to process {pid}"
    except ProcessLookupError:
        return f"Error: no process with PID {pid}"
    except PermissionError:
        return f"Error: permission denied to signal PID {pid}"


@tool(
    name="run_command",
    description=(
        "Execute a shell command and return stdout, stderr, and exit code. "
        "Use this for any system operation not covered by other tools."
    ),
    properties={
        "command": {"type": "string", "description": "Shell command to execute"},
        "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30)"},
        "working_dir": {"type": "string", "description": "Working directory for the command"},
    },
    required=["command"],
)
def run_command(command: str, timeout: int = 30, working_dir: str | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir,
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        parts = []
        if out:
            parts.append(out)
        if err:
            parts.append(f"[stderr]\n{err}")
        if result.returncode != 0:
            parts.append(f"[exit code: {result.returncode}]")
        return "\n".join(parts) if parts else "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="systemctl_action",
    description="Control systemd services (start, stop, restart, status, enable, disable).",
    properties={
        "action": {
            "type": "string",
            "description": "Action: start | stop | restart | status | enable | disable | list",
        },
        "service": {
            "type": "string",
            "description": "Service name (e.g. 'nginx'). Not needed for 'list'.",
        },
    },
    required=["action"],
)
def systemctl_action(action: str, service: str | None = None) -> str:
    valid_actions = {"start", "stop", "restart", "status", "enable", "disable", "list"}
    if action not in valid_actions:
        return f"Error: unknown action '{action}'. Valid: {', '.join(sorted(valid_actions))}"

    if action == "list":
        cmd = ["systemctl", "list-units", "--type=service", "--no-pager", "--no-legend"]
    elif service:
        cmd = ["systemctl", action, service]
    else:
        return "Error: 'service' is required for this action"

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = result.stdout.strip() or result.stderr.strip()
        return out if out else f"systemctl {action} {service or ''}: completed (no output)"
    except FileNotFoundError:
        return "Error: systemctl not found (is this a systemd system?)"
    except subprocess.TimeoutExpired:
        return "Error: systemctl timed out"


@tool(
    name="get_system_info",
    description="Get system information: CPU, memory, uptime, OS version.",
    properties={},
    required=[],
)
def get_system_info() -> str:
    lines = []

    try:
        import platform

        import psutil

        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        boot = psutil.boot_time()
        import datetime

        uptime = datetime.datetime.now() - datetime.datetime.fromtimestamp(boot)

        lines += [
            f"OS:      {platform.system()} {platform.release()} ({platform.machine()})",
            f"Kernel:  {platform.version()[:60]}",
            f"Uptime:  {str(uptime).split('.')[0]}",
            f"CPU:     {psutil.cpu_count()} cores @ {cpu:.1f}% usage",
            f"Memory:  {mem.used // 1024**2}MB / {mem.total // 1024**2}MB ({mem.percent:.1f}% used)",
            f"Disk /:  {disk.used // 1024**3}GB / {disk.total // 1024**3}GB ({disk.percent:.1f}% used)",
        ]
    except ImportError:
        for cmd, label in [
            (["uname", "-a"], "OS"),
            (["uptime", "-p"], "Uptime"),
            (["free", "-h"], "Memory"),
        ]:
            r = subprocess.run(cmd, capture_output=True, text=True)
            lines.append(f"{label}: {r.stdout.strip()}")

    return "\n".join(lines)
