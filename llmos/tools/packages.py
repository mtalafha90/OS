from __future__ import annotations

import subprocess
import sys

from .registry import tool


def _run(cmd: list[str], timeout: int = 120) -> str:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**__import__("os").environ, "DEBIAN_FRONTEND": "noninteractive"},
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        parts = []
        if out:
            parts.append(out)
        if err and result.returncode != 0:
            parts.append(f"[stderr] {err}")
        if result.returncode != 0:
            parts.append(f"[exit code: {result.returncode}]")
        return "\n".join(parts) if parts else "Done."
    except FileNotFoundError as e:
        return f"Error: command not found — {e}"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"


@tool(
    name="apt_install",
    description="Install one or more packages using apt-get.",
    properties={
        "packages": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of package names to install",
        },
    },
    required=["packages"],
)
def apt_install(packages: list[str]) -> str:
    return _run(["apt-get", "install", "-y", "--no-install-recommends"] + packages, timeout=300)


@tool(
    name="apt_remove",
    description="Remove one or more packages using apt-get.",
    properties={
        "packages": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of package names to remove",
        },
        "purge": {"type": "boolean", "description": "Also remove config files (default: false)"},
    },
    required=["packages"],
)
def apt_remove(packages: list[str], purge: bool = False) -> str:
    action = "purge" if purge else "remove"
    return _run(["apt-get", action, "-y"] + packages, timeout=120)


@tool(
    name="apt_update",
    description="Update the apt package index (run before installing new packages).",
    properties={},
    required=[],
)
def apt_update() -> str:
    return _run(["apt-get", "update"], timeout=120)


@tool(
    name="apt_upgrade",
    description="Upgrade all installed packages to their latest versions.",
    properties={
        "dist_upgrade": {
            "type": "boolean",
            "description": "Use dist-upgrade (handles dependency changes)",
        },
    },
    required=[],
)
def apt_upgrade(dist_upgrade: bool = False) -> str:
    action = "dist-upgrade" if dist_upgrade else "upgrade"
    return _run(["apt-get", action, "-y"], timeout=600)


@tool(
    name="apt_search",
    description="Search for packages in the apt repository.",
    properties={
        "query": {"type": "string", "description": "Search term"},
    },
    required=["query"],
)
def apt_search(query: str) -> str:
    return _run(["apt-cache", "search", query], timeout=30)


@tool(
    name="apt_show",
    description="Show detailed information about a package.",
    properties={
        "package": {"type": "string", "description": "Package name"},
    },
    required=["package"],
)
def apt_show(package: str) -> str:
    return _run(["apt-cache", "show", package], timeout=10)


@tool(
    name="list_installed_packages",
    description="List installed packages for apt or pip.",
    properties={
        "manager": {
            "type": "string",
            "description": "Package manager: 'apt' or 'pip' (default: apt)",
        },
        "filter_name": {
            "type": "string",
            "description": "Filter packages by name containing this string",
        },
    },
    required=[],
)
def list_installed_packages(manager: str = "apt", filter_name: str | None = None) -> str:
    if manager == "pip":
        result = _run([sys.executable, "-m", "pip", "list", "--format=columns"], timeout=30)
    else:
        result = _run(["dpkg", "--list"], timeout=30)

    if filter_name:
        lines = result.splitlines()
        filtered = [ln for ln in lines if filter_name.lower() in ln.lower()]
        return "\n".join(filtered) if filtered else f"No packages matching '{filter_name}'"
    return result


@tool(
    name="pip_install",
    description="Install Python packages using pip.",
    properties={
        "packages": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of Python package names or requirements (e.g. 'requests>=2.28')",
        },
        "upgrade": {"type": "boolean", "description": "Upgrade existing packages (default: false)"},
    },
    required=["packages"],
)
def pip_install(packages: list[str], upgrade: bool = False) -> str:
    cmd = [sys.executable, "-m", "pip", "install"] + packages
    if upgrade:
        cmd.append("--upgrade")
    return _run(cmd, timeout=300)


@tool(
    name="pip_uninstall",
    description="Uninstall Python packages using pip.",
    properties={
        "packages": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of Python package names to uninstall",
        },
    },
    required=["packages"],
)
def pip_uninstall(packages: list[str]) -> str:
    return _run([sys.executable, "-m", "pip", "uninstall", "-y"] + packages, timeout=60)
