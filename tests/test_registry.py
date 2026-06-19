"""Tests for the tool registry (@tool decorator + dispatch)."""
from __future__ import annotations

import pytest

from llmos.tools.registry import _REGISTRY, dispatch_tool, get_tool_schemas, tool


def test_tool_decorator_registers():
    initial = set(_REGISTRY.keys())

    @tool(
        name="_t_greet",
        description="Test greeting",
        properties={"name": {"type": "string", "description": "name"}},
        required=["name"],
    )
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    assert "_t_greet" in _REGISTRY
    _REGISTRY.pop("_t_greet", None)


def test_tool_decorator_schema_shape():
    @tool(
        name="_t_shape",
        description="Schema shape test",
        properties={"x": {"type": "integer", "description": "x"}},
        required=["x"],
    )
    def fn(x: int) -> int:
        return x

    entry = _REGISTRY["_t_shape"]
    schema = entry["schema"]
    assert schema["type"] == "function"
    func = schema["function"]
    assert func["name"] == "_t_shape"
    assert func["description"] == "Schema shape test"
    assert "parameters" in func
    assert func["parameters"]["required"] == ["x"]
    _REGISTRY.pop("_t_shape", None)


def test_dispatch_success():
    @tool(
        name="_t_add",
        description="Add two ints",
        properties={
            "a": {"type": "integer", "description": "a"},
            "b": {"type": "integer", "description": "b"},
        },
        required=["a", "b"],
    )
    def add(a: int, b: int) -> int:
        return a + b

    result = dispatch_tool("_t_add", {"a": 3, "b": 4})
    assert result == "7"
    _REGISTRY.pop("_t_add", None)


def test_dispatch_unknown_tool():
    result = dispatch_tool("_nonexistent_tool_xyz_", {})
    assert "Error" in result
    assert "_nonexistent_tool_xyz_" in result


def test_dispatch_exception_returns_error_string():
    @tool(
        name="_t_raise",
        description="Always raises",
        properties={},
        required=[],
    )
    def always_raise() -> str:
        raise ValueError("intentional error")

    result = dispatch_tool("_t_raise", {})
    assert "Error" in result
    _REGISTRY.pop("_t_raise", None)


def test_dispatch_returns_none_as_done():
    @tool(
        name="_t_none",
        description="Returns None",
        properties={},
        required=[],
    )
    def returns_none() -> None:
        return None

    result = dispatch_tool("_t_none", {})
    assert result == "Done."
    _REGISTRY.pop("_t_none", None)


def test_get_tool_schemas_returns_list():
    schemas = get_tool_schemas()
    assert isinstance(schemas, list)
    for s in schemas:
        assert s["type"] == "function"
        assert "name" in s["function"]
        assert "description" in s["function"]
        assert "parameters" in s["function"]


def test_get_tool_schemas_includes_core_tools():
    import llmos.tools  # noqa: F401 — ensure core tools are loaded

    schemas = get_tool_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert "list_directory" in names
    assert "read_file" in names
    assert "write_file" in names
    assert "run_command" in names
