"""LLM-callable tool wrappers for the persistent memory store."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .registry import tool

if TYPE_CHECKING:
    from llmos.memory import MemoryStore

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        from llmos.memory import MemoryStore

        _store = MemoryStore()
    return _store


# ---------------------------------------------------------------------------
# remember
# ---------------------------------------------------------------------------
@tool(
    name="remember",
    description=(
        "Save a piece of information to persistent memory. "
        "Use category='simulation' for sim configs, 'result' for outputs, "
        "'fact' for scientific facts, 'code' for code snippets, 'note' for general notes."
    ),
    properties={
        "content": {
            "type": "string",
            "description": "The text content to remember.",
        },
        "category": {
            "type": "string",
            "description": "Memory category: simulation, result, fact, code, note.",
            "enum": ["simulation", "result", "fact", "code", "note", "conversation", "file"],
        },
        "metadata": {
            "type": "object",
            "description": 'Optional metadata key-value pairs (e.g. {"source": "gpt4", "run_id": "..."})',
        },
    },
    required=["content"],
)
def remember(
    content: str,
    category: str = "note",
    metadata: dict | None = None,
) -> str:
    store = _get_store()
    memory_id = store.add_memory(content, category=category, metadata=metadata or {})
    return f"Remembered (id={memory_id}, category={category}): {content[:80]}{'...' if len(content) > 80 else ''}"


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------
@tool(
    name="recall",
    description=(
        "Search persistent memory for information related to a query. "
        "Returns the most relevant stored memories using semantic or keyword search."
    ),
    properties={
        "query": {
            "type": "string",
            "description": "Search query — describe what you are looking for.",
        },
        "category": {
            "type": "string",
            "description": "Optional filter by category: simulation, result, fact, code, note.",
        },
        "n_results": {
            "type": "integer",
            "description": "Number of results to return (default 5).",
        },
    },
    required=["query"],
)
def recall(
    query: str,
    category: str | None = None,
    n_results: int = 5,
) -> str:
    store = _get_store()
    results = store.search_memory(query, n_results=n_results, category=category or None)
    if not results:
        return "No memories found matching your query."
    lines = [f"Found {len(results)} memory/memories:\n"]
    for i, mem in enumerate(results, 1):
        meta_str = ""
        if mem.get("metadata"):
            meta_str = f"  metadata: {json.dumps(mem['metadata'])}\n"
        lines.append(
            f"{i}. [{mem.get('category', 'unknown')}] id={mem['id']}\n"
            f"   {mem['content']}\n"
            f"   created: {mem.get('created_at', 'unknown')}\n"
            f"{meta_str}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# list_memories
# ---------------------------------------------------------------------------
@tool(
    name="list_memories",
    description="List recently stored memories, optionally filtered by category.",
    properties={
        "category": {
            "type": "string",
            "description": "Filter by category: simulation, result, fact, code, note. Leave empty for all.",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of entries to return (default 20).",
        },
    },
    required=[],
)
def list_memories(category: str | None = None, limit: int = 20) -> str:
    store = _get_store()
    memories = store.list_memories(category=category or None, limit=limit)
    if not memories:
        label = f"category='{category}'" if category else "any category"
        return f"No memories found for {label}."
    lines = [f"Listing {len(memories)} memories:\n"]
    for mem in memories:
        preview = mem["content"][:100].replace("\n", " ")
        if len(mem["content"]) > 100:
            preview += "..."
        lines.append(
            f"• [{mem.get('category', '?')}] {mem['id']}\n"
            f"  {preview}\n"
            f"  created: {mem.get('created_at', '?')}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# forget
# ---------------------------------------------------------------------------
@tool(
    name="forget",
    description="Delete a specific memory by its ID.",
    properties={
        "memory_id": {
            "type": "string",
            "description": "The UUID of the memory to delete (obtained from recall or list_memories).",
        },
    },
    required=["memory_id"],
)
def forget(memory_id: str) -> str:
    store = _get_store()
    deleted = store.delete_memory(memory_id)
    if deleted:
        return f"Memory {memory_id} has been deleted."
    return f"Memory {memory_id} not found."
