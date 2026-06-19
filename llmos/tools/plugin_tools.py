"""LLM-callable tool wrappers for the plugin system."""
from __future__ import annotations

from .registry import tool

_loader = None


def _get_loader():
    global _loader
    if _loader is None:
        from llmos.plugins import PluginLoader
        _loader = PluginLoader()
    return _loader


@tool(
    name="load_plugin",
    description=(
        "Load a Python plugin file and register its tools with the LLM. "
        "The file must contain functions decorated with @tool from llmos.tools.registry."
    ),
    properties={
        "path": {
            "type": "string",
            "description": "Absolute path to the plugin .py file to load.",
        },
    },
    required=["path"],
)
def load_plugin(path: str) -> str:
    loader = _get_loader()
    try:
        new_tools = loader.load_file(path)
        if new_tools:
            return (
                f"Loaded plugin from {path}. "
                f"Registered {len(new_tools)} tool(s): {', '.join(new_tools)}"
            )
        return f"Loaded plugin from {path} but no new tools were registered."
    except FileNotFoundError:
        return f"Error: plugin file not found: {path}"
    except RuntimeError as e:
        return f"Error loading plugin: {e}"


@tool(
    name="unload_plugin",
    description="Unload a previously loaded plugin and de-register its tools.",
    properties={
        "plugin_name": {
            "type": "string",
            "description": "Stem name of the plugin to unload (filename without .py extension).",
        },
    },
    required=["plugin_name"],
)
def unload_plugin(plugin_name: str) -> str:
    loader = _get_loader()
    if loader.unload(plugin_name):
        return f"Plugin '{plugin_name}' unloaded and its tools de-registered."
    return f"Plugin '{plugin_name}' was not loaded."


@tool(
    name="list_plugins",
    description="List all currently loaded plugins and the tools they provide.",
    properties={},
    required=[],
)
def list_plugins() -> str:
    loader = _get_loader()
    plugins = loader.list_plugins()
    if not plugins:
        return "No plugins currently loaded."
    lines = [f"Loaded plugins ({len(plugins)}):"]
    for p in plugins:
        tools_str = ", ".join(p["tools"]) if p["tools"] else "(no tools registered)"
        lines.append(f"  {p['name']}  ({p['path']})\n    Tools: {tools_str}")
    return "\n".join(lines)


@tool(
    name="reload_plugins",
    description=(
        "Reload all plugins from the plugin directory (~/.config/llmos/tools/). "
        "Picks up new or modified plugin files without restarting LLM-OS."
    ),
    properties={},
    required=[],
)
def reload_plugins() -> str:
    loader = _get_loader()
    try:
        all_tools = loader.load_all()
        if all_tools:
            return (
                f"Loaded {len(all_tools)} tool(s) from plugin directory: "
                + ", ".join(all_tools)
            )
        return (
            "Plugin directory scanned. No tools registered "
            "(directory may be empty or contain only example_plugin.py)."
        )
    except Exception as e:
        return f"Error reloading plugins: {e}"
