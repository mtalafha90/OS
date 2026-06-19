"""Persistent memory and RAG knowledge base.

Uses ChromaDB with sentence-transformers embeddings when available;
falls back to SQLite FTS5 with keyword matching otherwise.
Storage location: ~/.config/llmos/memory/
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Storage directory
# ---------------------------------------------------------------------------
_STORE_DIR = Path.home() / ".config" / "llmos" / "memory"

VALID_CATEGORIES = {"conversation", "simulation", "result", "fact", "code", "note", "file"}


def _now() -> str:
    return datetime.utcnow().isoformat()


# ---------------------------------------------------------------------------
# Optional heavy dependencies
# ---------------------------------------------------------------------------
def _try_import_chromadb():
    try:
        import chromadb  # noqa: F401

        return chromadb
    except ImportError:
        return None


def _try_import_sentence_transformers():
    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401

        return SentenceTransformer
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# SQLite FTS5 backend (fallback)
# ---------------------------------------------------------------------------
_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'note',
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    id UNINDEXED,
    content,
    category,
    content='memories',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, id, content, category)
    VALUES (new.rowid, new.id, new.content, new.category);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, id, content, category)
    VALUES ('delete', old.rowid, old.id, old.content, old.category);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, id, content, category)
    VALUES ('delete', old.rowid, old.id, old.content, old.category);
    INSERT INTO memories_fts(rowid, id, content, category)
    VALUES (new.rowid, new.id, new.content, new.category);
END;
"""


class _SQLiteBackend:
    """FTS5-backed memory store (no vector search)."""

    def __init__(self, store_dir: Path):
        store_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = store_dir / "memories.db"
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript(_SQLITE_SCHEMA)
        self._conn.commit()

    def add(self, memory_id: str, content: str, category: str, metadata: dict) -> str:
        self._conn.execute(
            "INSERT INTO memories (id, content, category, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
            (memory_id, content, category, json.dumps(metadata), _now()),
        )
        self._conn.commit()
        return memory_id

    def search(self, query: str, n_results: int, category: str | None) -> list[dict]:
        if category:
            rows = self._conn.execute(
                """
                SELECT m.id, m.content, m.category, m.metadata, m.created_at,
                       bm25(memories_fts) AS score
                  FROM memories_fts
                  JOIN memories m ON m.rowid = memories_fts.rowid
                 WHERE memories_fts MATCH ?
                   AND m.category = ?
                 ORDER BY score
                 LIMIT ?
                """,
                (query, category, n_results),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT m.id, m.content, m.category, m.metadata, m.created_at,
                       bm25(memories_fts) AS score
                  FROM memories_fts
                  JOIN memories m ON m.rowid = memories_fts.rowid
                 WHERE memories_fts MATCH ?
                 ORDER BY score
                 LIMIT ?
                """,
                (query, n_results),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_recent(self, category: str | None, limit: int) -> list[dict]:
        if category:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE category = ? ORDER BY created_at DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete(self, memory_id: str) -> bool:
        cursor = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def stats(self) -> dict:
        rows = self._conn.execute(
            "SELECT category, COUNT(*) as cnt FROM memories GROUP BY category"
        ).fetchall()
        return {r["category"]: r["cnt"] for r in rows}

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        return d


# ---------------------------------------------------------------------------
# ChromaDB backend (preferred)
# ---------------------------------------------------------------------------
class _ChromaBackend:
    """Vector-search memory store using ChromaDB + optional sentence-transformers."""

    def __init__(self, store_dir: Path):
        import chromadb  # already checked it's available

        store_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(store_dir))

        SentenceTransformer = _try_import_sentence_transformers()
        if SentenceTransformer is not None:
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

            ef = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        else:
            ef = None  # ChromaDB will use its default embedding function

        self._collection = self._client.get_or_create_collection(
            name="llmos_memories",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, memory_id: str, content: str, category: str, metadata: dict) -> str:
        meta = {**metadata, "category": category, "created_at": _now()}
        self._collection.add(
            ids=[memory_id],
            documents=[content],
            metadatas=[meta],
        )
        return memory_id

    def search(self, query: str, n_results: int, category: str | None) -> list[dict]:
        where = {"category": category} if category else None
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where,
            )
        except Exception:
            return []

        out = []
        if not results["ids"] or not results["ids"][0]:
            return out
        for i, mid in enumerate(results["ids"][0]):
            doc = results["documents"][0][i]
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i] if results.get("distances") else None
            out.append(
                {
                    "id": mid,
                    "content": doc,
                    "category": meta.get("category", ""),
                    "metadata": {
                        k: v for k, v in meta.items() if k not in ("category", "created_at")
                    },
                    "created_at": meta.get("created_at", ""),
                    "distance": distance,
                }
            )
        return out

    def list_recent(self, category: str | None, limit: int) -> list[dict]:
        where = {"category": category} if category else None
        try:
            results = self._collection.get(where=where, limit=limit)
        except Exception:
            return []

        out = []
        for i, mid in enumerate(results["ids"]):
            doc = results["documents"][i]
            meta = results["metadatas"][i]
            out.append(
                {
                    "id": mid,
                    "content": doc,
                    "category": meta.get("category", ""),
                    "metadata": {
                        k: v for k, v in meta.items() if k not in ("category", "created_at")
                    },
                    "created_at": meta.get("created_at", ""),
                }
            )
        # Sort by created_at descending
        out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return out[:limit]

    def delete(self, memory_id: str) -> bool:
        try:
            self._collection.delete(ids=[memory_id])
            return True
        except Exception:
            return False

    def stats(self) -> dict:
        try:
            results = self._collection.get()
        except Exception:
            return {}
        counts: dict[str, int] = {}
        for meta in results["metadatas"]:
            cat = meta.get("category", "unknown")
            counts[cat] = counts.get(cat, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Public MemoryStore
# ---------------------------------------------------------------------------
class MemoryStore:
    """Unified persistent memory store.

    Automatically selects ChromaDB (vector search) when available,
    otherwise falls back to SQLite FTS5 (keyword search).
    """

    def __init__(self, store_dir: Path | None = None):
        self._dir = Path(store_dir) if store_dir else _STORE_DIR
        chromadb = _try_import_chromadb()
        if chromadb is not None:
            self._backend = _ChromaBackend(self._dir)
            self._backend_name = "chromadb"
        else:
            self._backend = _SQLiteBackend(self._dir)
            self._backend_name = "sqlite_fts5"

    # ------------------------------------------------------------------
    def add_memory(
        self,
        content: str,
        category: str = "note",
        metadata: dict | None = None,
    ) -> str:
        """Store a memory entry.

        Parameters
        ----------
        content:  The text to remember.
        category: One of conversation/simulation/result/fact/code/note/file.
        metadata: Optional dict of extra key/value pairs.

        Returns
        -------
        memory_id: str — the UUID assigned to this entry.
        """
        if category not in VALID_CATEGORIES:
            category = "note"
        memory_id = str(uuid.uuid4())
        self._backend.add(memory_id, content, category, metadata or {})
        return memory_id

    def search_memory(
        self,
        query: str,
        n_results: int = 5,
        category: str | None = None,
    ) -> list[dict]:
        """Semantic (or keyword) search.

        Parameters
        ----------
        query:    Natural-language search string.
        n_results: How many results to return.
        category: Optional filter by category.

        Returns
        -------
        List of dicts with keys: id, content, category, metadata, created_at.
        """
        return self._backend.search(query, n_results, category)

    def list_memories(
        self,
        category: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """List recent memories, optionally filtered by category."""
        return self._backend.list_recent(category, limit)

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory by its ID. Returns True if deleted."""
        return self._backend.delete(memory_id)

    def get_stats(self) -> dict[str, Any]:
        """Return count of memories per category plus backend info."""
        counts = self._backend.stats()
        return {
            "backend": self._backend_name,
            "store_dir": str(self._dir),
            "counts_by_category": counts,
            "total": sum(counts.values()),
        }
