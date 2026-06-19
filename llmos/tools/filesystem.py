from __future__ import annotations

import os
import shutil
import stat
import fnmatch
from datetime import datetime
from pathlib import Path

from .registry import tool


def _fmt_size(n: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}P"


def _fmt_mode(mode: int) -> str:
    return stat.filemode(mode)


@tool(
    name="list_directory",
    description="List files and directories at a given path. Returns name, size, permissions, and modification time.",
    properties={
        "path": {"type": "string", "description": "Directory to list (default: current directory)"},
        "show_hidden": {"type": "boolean", "description": "Include hidden files (starting with '.')"},
    },
    required=[],
)
def list_directory(path: str = ".", show_hidden: bool = False) -> str:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"Error: '{path}' does not exist"
    if not p.is_dir():
        return f"Error: '{path}' is not a directory"

    entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    lines = [f"{'Permissions':<12} {'Size':>6}  {'Modified':<18}  Name"]
    lines.append("-" * 60)
    for entry in entries:
        if not show_hidden and entry.name.startswith("."):
            continue
        try:
            s = entry.stat()
            mode = _fmt_mode(s.st_mode)
            size = _fmt_size(s.st_size) if entry.is_file() else "-"
            mtime = datetime.fromtimestamp(s.st_mtime).strftime("%Y-%m-%d %H:%M")
            name = entry.name + ("/" if entry.is_dir() else "")
            lines.append(f"{mode:<12} {size:>6}  {mtime:<18}  {name}")
        except PermissionError:
            lines.append(f"{'?':<12} {'?':>6}  {'?':<18}  {entry.name}")
    return "\n".join(lines)


@tool(
    name="read_file",
    description="Read the contents of a text file. Optionally specify line range.",
    properties={
        "path": {"type": "string", "description": "File path to read"},
        "start_line": {"type": "integer", "description": "First line to read (1-indexed, default 1)"},
        "end_line": {"type": "integer", "description": "Last line to read (inclusive, default: all)"},
    },
    required=["path"],
)
def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"Error: '{path}' not found"
    if not p.is_file():
        return f"Error: '{path}' is not a file"
    try:
        lines = p.read_text(errors="replace").splitlines()
        total = len(lines)
        s = max(0, start_line - 1)
        e = end_line if end_line else total
        selected = lines[s:e]
        header = f"=== {path} ({total} lines total, showing {s+1}-{min(e,total)}) ===\n"
        return header + "\n".join(f"{s+i+1:4}: {l}" for i, l in enumerate(selected))
    except PermissionError:
        return f"Error: permission denied reading '{path}'"


@tool(
    name="write_file",
    description="Write or overwrite a text file with the given content.",
    properties={
        "path": {"type": "string", "description": "Destination file path"},
        "content": {"type": "string", "description": "Text content to write"},
        "append": {"type": "boolean", "description": "Append instead of overwrite (default: false)"},
    },
    required=["path", "content"],
)
def write_file(path: str, content: str, append: bool = False) -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    p.write_text(content) if not append else open(p, "a").write(content)
    action = "Appended to" if append else "Wrote"
    return f"{action} {p} ({len(content)} bytes)"


@tool(
    name="create_directory",
    description="Create a directory (and any missing parents).",
    properties={
        "path": {"type": "string", "description": "Directory path to create"},
    },
    required=["path"],
)
def create_directory(path: str) -> str:
    p = Path(path).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return f"Created directory: {p}"


@tool(
    name="delete_path",
    description="Delete a file or directory.",
    properties={
        "path": {"type": "string", "description": "Path to delete"},
        "recursive": {"type": "boolean", "description": "Recursively delete directories (default: false)"},
    },
    required=["path"],
)
def delete_path(path: str, recursive: bool = False) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"Error: '{path}' does not exist"
    if p.is_dir():
        if not recursive:
            return f"Error: '{path}' is a directory. Set recursive=true to delete it."
        shutil.rmtree(p)
    else:
        p.unlink()
    return f"Deleted: {path}"


@tool(
    name="move_path",
    description="Move or rename a file or directory.",
    properties={
        "source": {"type": "string", "description": "Source path"},
        "destination": {"type": "string", "description": "Destination path"},
    },
    required=["source", "destination"],
)
def move_path(source: str, destination: str) -> str:
    src = Path(source).expanduser()
    dst = Path(destination).expanduser()
    if not src.exists():
        return f"Error: '{source}' not found"
    shutil.move(str(src), str(dst))
    return f"Moved: {source} -> {destination}"


@tool(
    name="copy_path",
    description="Copy a file or directory to a new location.",
    properties={
        "source": {"type": "string", "description": "Source path"},
        "destination": {"type": "string", "description": "Destination path"},
    },
    required=["source", "destination"],
)
def copy_path(source: str, destination: str) -> str:
    src = Path(source).expanduser()
    dst = Path(destination).expanduser()
    if not src.exists():
        return f"Error: '{source}' not found"
    if src.is_dir():
        shutil.copytree(str(src), str(dst))
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
    return f"Copied: {source} -> {destination}"


@tool(
    name="search_files",
    description="Search for files by name pattern or containing specific text content.",
    properties={
        "directory": {"type": "string", "description": "Directory to search in"},
        "name_pattern": {"type": "string", "description": "Filename glob pattern (e.g. '*.py')"},
        "content_pattern": {"type": "string", "description": "Text to search inside files"},
        "max_results": {"type": "integer", "description": "Maximum number of results (default 50)"},
    },
    required=["directory"],
)
def search_files(
    directory: str,
    name_pattern: str | None = None,
    content_pattern: str | None = None,
    max_results: int = 50,
) -> str:
    base = Path(directory).expanduser()
    if not base.exists():
        return f"Error: '{directory}' not found"

    results = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if name_pattern and not fnmatch.fnmatch(fname, name_pattern):
                continue
            fpath = Path(root) / fname
            if content_pattern:
                try:
                    text = fpath.read_text(errors="replace")
                    if content_pattern not in text:
                        continue
                    matches = [
                        f"  line {i+1}: {l.strip()}"
                        for i, l in enumerate(text.splitlines())
                        if content_pattern in l
                    ]
                    results.append(f"{fpath}\n" + "\n".join(matches[:5]))
                except Exception:
                    continue
            else:
                results.append(str(fpath))
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break

    if not results:
        return "No matches found."
    return f"Found {len(results)} result(s):\n" + "\n".join(results)


@tool(
    name="get_disk_usage",
    description="Show disk usage for a path or all mounted filesystems.",
    properties={
        "path": {"type": "string", "description": "Path to check (default: all filesystems)"},
    },
    required=[],
)
def get_disk_usage(path: str = "/") -> str:
    usage = shutil.disk_usage(path)
    total = _fmt_size(usage.total)
    used = _fmt_size(usage.used)
    free = _fmt_size(usage.free)
    pct = usage.used / usage.total * 100
    return (
        f"Disk usage for {path}:\n"
        f"  Total: {total}\n"
        f"  Used:  {used} ({pct:.1f}%)\n"
        f"  Free:  {free}"
    )
