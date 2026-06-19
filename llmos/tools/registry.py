from __future__ import annotations

from typing import Any, Callable

_REGISTRY: dict[str, dict] = {}


def tool(
    name: str,
    description: str,
    properties: dict[str, dict],
    required: list[str] | None = None,
) -> Callable:
    """Decorator that registers a function as an LLM-callable tool."""
    def decorator(fn: Callable) -> Callable:
        _REGISTRY[name] = {
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required or [],
                    },
                },
            },
            "fn": fn,
        }
        return fn
    return decorator


def get_tool_schemas() -> list[dict]:
    return [entry["schema"] for entry in _REGISTRY.values()]


def dispatch_tool(name: str, args: dict[str, Any]) -> str:
    entry = _REGISTRY.get(name)
    if entry is None:
        return f"Error: unknown tool '{name}'"
    try:
        result = entry["fn"](**args)
        return str(result) if result is not None else "Done."
    except Exception as exc:
        return f"Error executing {name}: {exc}"
