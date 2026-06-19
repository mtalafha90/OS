from .registry import get_tool_schemas, dispatch_tool
from . import filesystem, process, network, packages, gpu, scientific

# Optional feature modules — loaded only if their deps are present
_OPTIONAL_TOOLS = [
    "memory_tools",
    "scheduler_tools",
    "agent_tools",
    "voice_tools",
    "versioning_tools",
    "remote_tools",
    "container_tools",
    "report_tools",
    "visualization_tools",
    "plugin_tools",
]

for _mod in _OPTIONAL_TOOLS:
    try:
        __import__(f"llmos.tools.{_mod}")
    except Exception:
        pass  # silently skip if deps missing

__all__ = ["get_tool_schemas", "dispatch_tool"]

