from __future__ import annotations

import json
import os
from pathlib import Path

from .executor import RemoteExecutor

_CLUSTERS_FILE = Path(os.path.expanduser("~/.config/llmos/clusters.json"))

__all__ = ["RemoteExecutor", "add_cluster", "get_cluster", "list_clusters"]


def _load() -> dict:
    if _CLUSTERS_FILE.exists():
        return json.loads(_CLUSTERS_FILE.read_text())
    return {}


def _save(data: dict) -> None:
    _CLUSTERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CLUSTERS_FILE.write_text(json.dumps(data, indent=2))


def add_cluster(name: str, host: str, username: str, key_file: str, port: int = 22) -> None:
    data = _load()
    data[name] = {"host": host, "username": username, "key_file": key_file, "port": port}
    _save(data)


def get_cluster(name: str) -> RemoteExecutor:
    data = _load()
    if name not in data:
        raise KeyError(f"Cluster '{name}' not found. Register with add_cluster().")
    c = data[name]
    return RemoteExecutor(c["host"], c["username"], c.get("key_file"), c.get("port", 22))


def list_clusters() -> list[str]:
    return list(_load().keys())
