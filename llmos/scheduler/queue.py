"""SQLite-backed job queue for simulation workloads."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_DB_DIR = Path.home() / ".config" / "llmos"
_DB_PATH = _DB_DIR / "jobs.db"

VALID_STATUSES = {"pending", "running", "done", "failed", "cancelled"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    command      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    priority     INTEGER NOT NULL DEFAULT 5,
    gpu_ids      TEXT NOT NULL DEFAULT '[]',
    mpi_ranks    INTEGER NOT NULL DEFAULT 1,
    workdir      TEXT,
    submit_time  TEXT NOT NULL,
    start_time   TEXT,
    end_time     TEXT,
    pid          INTEGER,
    log_file     TEXT,
    metadata     TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_priority ON jobs (priority DESC, submit_time ASC);
"""


def _now() -> str:
    return datetime.utcnow().isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["gpu_ids"] = json.loads(d.get("gpu_ids") or "[]")
    d["metadata"] = json.loads(d.get("metadata") or "{}")
    return d


class JobQueue:
    """Persistent SQLite-backed job queue.

    Thread-safe via ``check_same_thread=False`` + explicit commit.
    """

    def __init__(self, db_path: Path | None = None):
        self._db_path = Path(db_path) if db_path else _DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------
    def submit(
        self,
        name: str,
        command: str,
        priority: int = 5,
        gpu_ids: list[int] | None = None,
        mpi_ranks: int = 1,
        workdir: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Enqueue a new job.

        Parameters
        ----------
        name:      Human-readable job name.
        command:   Shell command to execute.
        priority:  1 (lowest) … 10 (highest), default 5.
        gpu_ids:   List of GPU indices (e.g. [0, 1]).
        mpi_ranks: Number of MPI ranks (1 = no MPI wrapper).
        workdir:   Working directory for the job.
        metadata:  Arbitrary JSON-serialisable metadata.

        Returns
        -------
        job_id: str — UUID assigned to this job.
        """
        job_id = str(uuid.uuid4())
        priority = max(1, min(10, int(priority)))
        self._conn.execute(
            """
            INSERT INTO jobs
                (id, name, command, status, priority, gpu_ids, mpi_ranks,
                 workdir, submit_time, metadata)
            VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                name,
                command,
                priority,
                json.dumps(gpu_ids or []),
                max(1, int(mpi_ranks)),
                workdir,
                _now(),
                json.dumps(metadata or {}),
            ),
        )
        self._conn.commit()
        return job_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Return a single job record or None if not found."""
        row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def list_jobs(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List jobs, optionally filtered by status.

        Returns most-recently submitted jobs first.
        """
        if status and status in VALID_STATUSES:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY submit_time DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY submit_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def next_pending(self) -> dict[str, Any] | None:
        """Return the highest-priority pending job (for the runner)."""
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE status = 'pending' ORDER BY priority DESC, submit_time ASC LIMIT 1"
        ).fetchone()
        return _row_to_dict(row) if row else None

    # ------------------------------------------------------------------
    # Update (called by runner)
    # ------------------------------------------------------------------
    def mark_running(self, job_id: str, pid: int, log_file: str) -> None:
        self._conn.execute(
            "UPDATE jobs SET status='running', start_time=?, pid=?, log_file=? WHERE id=?",
            (_now(), pid, log_file, job_id),
        )
        self._conn.commit()

    def mark_done(self, job_id: str, success: bool = True) -> None:
        status = "done" if success else "failed"
        self._conn.execute(
            "UPDATE jobs SET status=?, end_time=? WHERE id=?",
            (status, _now(), job_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a pending or running job.

        Returns True if the job was found and its status updated.
        """
        row = self._conn.execute("SELECT status, pid FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return False
        if row["status"] not in ("pending", "running"):
            return False

        self._conn.execute(
            "UPDATE jobs SET status='cancelled', end_time=? WHERE id=?",
            (_now(), job_id),
        )
        self._conn.commit()

        # Best-effort process kill for running jobs
        if row["status"] == "running" and row["pid"]:
            try:
                import os
                import signal

                os.kill(row["pid"], signal.SIGTERM)
            except Exception:
                pass
        return True

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    def get_stats(self) -> dict[str, Any]:
        """Return count of jobs per status plus total."""
        rows = self._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
        ).fetchall()
        counts = {r["status"]: r["cnt"] for r in rows}
        return {
            "db_path": str(self._db_path),
            "counts_by_status": counts,
            "total": sum(counts.values()),
        }
