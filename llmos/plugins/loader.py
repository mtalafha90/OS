"""Dynamic plugin loader for LLM-OS.

Loads Python files from ~/.config/llmos/tools/ and registers any functions
decorated with @tool(...) from llmos.tools.registry into the global tool
registry.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Example plugin template written to the directory when it is empty
# ---------------------------------------------------------------------------

_EXAMPLE_PLUGIN = '''\
"""Example LLM-OS plugin.

Copy this file or add new functions here to register custom tools.
Each function decorated with @tool(...) will be available to the LLM.
"""
from llmos.tools.registry import tool


@tool(
    name="hello_world",
    description="A simple example tool that returns a greeting.",
    properties={
        "name": {
            "type": "string",
            "description": "Name to greet (default: 'World').",
        },
    },
    required=[],
)
def hello_world(name: str = "World") -> str:
    """Return a greeting string."""
    return f"Hello, {name}! This tool was loaded from a plugin."
'''


# ---------------------------------------------------------------------------
# PluginLoader
# ---------------------------------------------------------------------------


class PluginLoader:
    """Manage dynamic plugins stored in ~/.config/llmos/tools/.

    Usage::

        loader = PluginLoader()
        names  = loader.load_all()   # loads every .py in the plugin directory
    """

    def __init__(self, plugin_dir: str = "~/.config/llmos/tools") -> None:
        self._plugin_dir = Path(plugin_dir).expanduser()
        # plugin_name → {"path": Path, "module": module, "tools": [str]}
        self._loaded: dict[str, dict[str, Any]] = {}

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _ensure_dir(self) -> None:
        """Create the plugin directory (and an example file) if needed."""
        self._plugin_dir.mkdir(parents=True, exist_ok=True)
        example = self._plugin_dir / "example_plugin.py"
        if not any(self._plugin_dir.glob("*.py")):
            example.write_text(_EXAMPLE_PLUGIN, encoding="utf-8")

    @staticmethod
    def _tool_names_before() -> set[str]:
        from llmos.tools.registry import _REGISTRY

        return set(_REGISTRY.keys())

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def load_all(self) -> list[str]:
        """Load every .py file from the plugin directory.

        Returns:
            Sorted list of tool names registered by the loaded plugins.
        """
        self._ensure_dir()
        all_tools: list[str] = []
        for path in sorted(self._plugin_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            all_tools.extend(self.load_file(str(path)))
        return all_tools

    def load_file(self, path: str) -> list[str]:
        """Load a specific plugin file and return its registered tool names.

        Args:
            path: Absolute or expanduser path to a .py plugin file.

        Returns:
            List of tool names that were newly registered by the file.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        fpath = Path(path).expanduser().resolve()
        if not fpath.exists():
            raise FileNotFoundError(f"Plugin file not found: {path}")

        plugin_name = fpath.stem

        # Snapshot the registry before import
        before = self._tool_names_before()

        # Build module name ensuring uniqueness
        mod_name = f"llmos_plugin_{plugin_name}"

        # If already loaded, reload to pick up changes
        if mod_name in sys.modules:
            sys.modules.pop(mod_name)
            # Also remove from our tracking so we refresh
            self._loaded.pop(plugin_name, None)

        spec = importlib.util.spec_from_file_location(mod_name, str(fpath))
        if spec is None or spec.loader is None:
            return []

        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except Exception as exc:
            sys.modules.pop(mod_name, None)
            raise RuntimeError(f"Error loading plugin '{fpath.name}': {exc}") from exc

        after = self._tool_names_before()
        new_tools = sorted(after - before)

        self._loaded[plugin_name] = {
            "path": fpath,
            "module": mod,
            "tools": new_tools,
        }

        return new_tools

    def list_plugins(self) -> list[dict]:
        """Return info about all currently loaded plugins.

        Returns:
            List of dicts, each with keys:
                name (str), path (str), tools (list[str]).
        """
        return [
            {
                "name": name,
                "path": str(info["path"]),
                "tools": info["tools"],
            }
            for name, info in self._loaded.items()
        ]

    def unload(self, plugin_name: str) -> bool:
        """Unload a plugin and de-register its tools.

        Args:
            plugin_name: The stem name of the plugin file (without .py).

        Returns:
            True if the plugin was found and unloaded, False otherwise.
        """
        info = self._loaded.pop(plugin_name, None)
        if info is None:
            return False

        # Remove tools from the global registry
        from llmos.tools.registry import _REGISTRY

        for tool_name in info["tools"]:
            _REGISTRY.pop(tool_name, None)

        # Remove the module
        mod_name = f"llmos_plugin_{plugin_name}"
        sys.modules.pop(mod_name, None)

        return True
