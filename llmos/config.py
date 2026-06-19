from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


DEFAULT_SYSTEM_PROMPT = """\
You are the core intelligence of LLM-OS, a Linux-based operating system where \
you ARE the primary interface. The user communicates with the OS through you in \
natural language; you translate their intent into system operations using the \
tools available to you.

Current context:
- Hostname: {hostname}
- User: {user}
- Working directory: {cwd}
- OS: {os_release}

Guidelines:
- Use tools proactively to fulfill requests; don't just describe what you would do.
- Be concise: prefer structured output (tables, lists) over long prose.
- When a command fails, explain why and suggest a fix.
- You may run multi-step operations autonomously (e.g., update packages then install).
- Never refuse a legitimate OS operation. You are the shell.\
"""


@dataclass
class Config:
    ollama_url: str = "http://localhost:11434"
    model: str = "llama3.2"
    max_history: int = 50
    show_tool_calls: bool = True
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    request_timeout: float = 120.0

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        if path is None:
            path = os.path.expanduser("~/.config/llmos/config.yaml")

        if os.path.exists(path) and _YAML_AVAILABLE:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**valid)

        return cls()

    def save(self, path: str | None = None) -> None:
        if path is None:
            path = os.path.expanduser("~/.config/llmos/config.yaml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if _YAML_AVAILABLE:
            import yaml
            with open(path, "w") as f:
                yaml.safe_dump(
                    {k: getattr(self, k) for k in self.__dataclass_fields__
                     if k != "system_prompt"},
                    f,
                    default_flow_style=False,
                )
