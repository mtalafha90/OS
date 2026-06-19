"""Simulation run tracker using SQLite.

Each run record captures the full provenance of a simulation: name, command,
parameters, status, timing, output directory, result files, metrics, tags,
and freeform notes.

Storage location: ~/.config/llmos/simulations.db
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_DB_DIR = Path.home() / ".config" / "llmos"
_DB_PATH = _DB_DIR / "simulations.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    command      TEXT NOT NULL DEFAULT '',
    parameters   TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'running',
    start_time   TEXT NOT NULL,
    end_time     TEXT,
    output_dir   TEXT,
    result_files TEXT NOT NULL DEFAULT '[]',
    metrics      TEXT NOT NULL DEFAULT '{}',
    tags         TEXT NOT NULL DEFAULT '[]',
    notes        TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs (status);
CREATE INDEX IF NOT EXISTS idx_runs_start  ON runs (start_time DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS runs_fts USING fts5(
    id UNINDEXED,
    name,
    description,
    notes,
    tags,
    content='runs',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS runs_ai AFTER INSERT ON runs BEGIN
    INSERT INTO runs_fts(rowid, id, name, description, notes, tags)
    VALUES (new.rowid, new.id, new.name, new.description, new.notes, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS runs_ad AFTER DELETE ON runs BEGIN
    INSERT INTO runs_fts(runs_fts, rowid, id, name, description, notes, tags)
    VALUES ('delete', old.rowid, old.id, old.name, old.description, old.notes, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS runs_au AFTER UPDATE ON runs BEGIN
    INSERT INTO runs_fts(runs_fts, rowid, id, name, description, notes, tags)
    VALUES ('delete', old.rowid, old.id, old.name, old.description, old.notes, old.tags);
    INSERT INTO runs_fts(rowid, id, name, description, notes, tags)
    VALUES (new.rowid, new.id, new.name, new.description, new.notes, new.tags);
END;
"""


def _now() -> str:
    return datetime.utcnow().isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for field in ("parameters", "metrics"):
        d[field] = json.loads(d.get(field) or "{}")
    for field in ("result_files", "tags"):
        d[field] = json.loads(d.get(field) or "[]")
    return d


class SimulationTracker:
    """SQLite-backed tracker for simulation runs.

    Provides full CRUD plus text search and side-by-side comparison.
    """

    def __init__(self, db_path: Path | None = None):
        self._db_path = Path(db_path) if db_path else _DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Start / finish / fail
    # ------------------------------------------------------------------
    def start_run(
        self,
        name: str,
        command: str = "",
        parameters: dict | None = None,
        description: str = "",
        tags: list[str] | None = None,
        output_dir: str | None = None,
    ) -> str:
        """Record the start of a simulation run.

        Returns the run_id (UUID string).
        """
        run_id = str(uuid.uuid4())
        self._conn.execute(
            """
            INSERT INTO runs
                (id, name, description, command, parameters, status,
                 start_time, output_dir, tags)
            VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?)
            """,
            (
                run_id,
                name,
                description,
                command,
                json.dumps(parameters or {}),
                _now(),
                output_dir,
                json.dumps(tags or []),
            ),
        )
        self._conn.commit()
        return run_id

    def finish_run(
        self,
        run_id: str,
        metrics: dict | None = None,
        result_files: list[str] | None = None,
        notes: str = "",
    ) -> bool:
        """Mark a run as completed and record its outputs.

        Returns True if the run was found and updated.
        """
        cursor = self._conn.execute(
            """
            UPDATE runs
               SET status='done', end_time=?, metrics=?, result_files=?, notes=?
             WHERE id=?
            """,
            (
                _now(),
                json.dumps(metrics or {}),
                json.dumps(result_files or []),
                notes,
                run_id,
            ),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def fail_run(self, run_id: str, error: str = "") -> bool:
        """Mark a run as failed and record the error in notes.

        Returns True if the run was found and updated.
        """
        cursor = self._conn.execute(
            "UPDATE runs SET status='failed', end_time=?, notes=? WHERE id=?",
            (_now(), error, run_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Return a single run record or None."""
        row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def list_runs(
        self,
        tag: str | None = None,
        limit: int = 20,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List runs, optionally filtered by tag and/or status.

        Results are sorted newest-first by start_time.
        """
        conditions = []
        params: list[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status)

        if tag:
            # tags is a JSON array — use LIKE for simple containment check
            conditions.append("tags LIKE ?")
            params.append(f'%"{tag}"%')

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)

        rows = self._conn.execute(
            f"SELECT * FROM runs {where} ORDER BY start_time DESC LIMIT ?",
            params,
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def search_runs(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Full-text search over name, description, notes, and tags."""
        try:
            rows = self._conn.execute(
                """
                SELECT r.*
                  FROM runs_fts
                  JOIN runs r ON r.rowid = runs_fts.rowid
                 WHERE runs_fts MATCH ?
                 ORDER BY bm25(runs_fts)
                 LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # FTS might fail on special chars — fall back to LIKE
            rows = self._conn.execute(
                """
                SELECT * FROM runs
                 WHERE name LIKE ? OR description LIKE ? OR notes LIKE ?
                 ORDER BY start_time DESC
                 LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", f"%{query}%", limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Compare
    # ------------------------------------------------------------------
    def compare_runs(self, run_ids: list[str]) -> dict[str, Any]:
        """Side-by-side comparison of parameters and metrics.

        Returns a dict with keys:
          - ``runs``: list of lightweight run dicts (id, name, status, start_time, end_time)
          - ``parameters``: {param_key: {run_id: value, ...}, ...}
          - ``metrics``:    {metric_key: {run_id: value, ...}, ...}
        """
        records = []
        for rid in run_ids:
            rec = self.get_run(rid)
            if rec:
                records.append(rec)

        if not records:
            return {
                "error": "No runs found for the given IDs.",
                "runs": [],
                "parameters": {},
                "metrics": {},
            }

        # Collect all parameter / metric keys across runs
        all_param_keys: set[str] = set()
        all_metric_keys: set[str] = set()
        for rec in records:
            all_param_keys.update(rec.get("parameters", {}).keys())
            all_metric_keys.update(rec.get("metrics", {}).keys())

        parameters: dict[str, dict[str, Any]] = {}
        for key in sorted(all_param_keys):
            parameters[key] = {
                rec["id"]: rec.get("parameters", {}).get(key, None) for rec in records
            }

        metrics: dict[str, dict[str, Any]] = {}
        for key in sorted(all_metric_keys):
            metrics[key] = {rec["id"]: rec.get("metrics", {}).get(key, None) for rec in records}

        run_summaries = [
            {
                "id": rec["id"],
                "name": rec["name"],
                "status": rec["status"],
                "start_time": rec.get("start_time"),
                "end_time": rec.get("end_time"),
                "tags": rec.get("tags", []),
            }
            for rec in records
        ]

        return {
            "runs": run_summaries,
            "parameters": parameters,
            "metrics": metrics,
        }
