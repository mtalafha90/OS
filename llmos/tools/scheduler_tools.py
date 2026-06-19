"""LLM-callable tool wrappers for the job scheduler."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .registry import tool

if TYPE_CHECKING:
    from llmos.scheduler import JobQueue

_queue: "JobQueue | None" = None


def _get_queue() -> "JobQueue":
    global _queue
    if _queue is None:
        from llmos.scheduler import JobQueue
        _queue = JobQueue()
    return _queue


# ---------------------------------------------------------------------------
# submit_job
# ---------------------------------------------------------------------------
@tool(
    name="submit_job",
    description=(
        "Submit a simulation or compute job to the job queue. "
        "The job will be executed in the background by the JobRunner. "
        "Returns a job_id that can be used to check status or cancel the job."
    ),
    properties={
        "name": {
            "type": "string",
            "description": "Human-readable name for the job.",
        },
        "command": {
            "type": "string",
            "description": "Shell command to execute (e.g. 'python run_sim.py --steps 1000').",
        },
        "priority": {
            "type": "integer",
            "description": "Job priority 1 (lowest) to 10 (highest), default 5.",
        },
        "gpu_ids": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "List of GPU indices to use (e.g. [0, 1]). Empty for CPU-only.",
        },
        "mpi_ranks": {
            "type": "integer",
            "description": "Number of MPI ranks. If >1, mpirun -n <ranks> is prepended to the command.",
        },
        "workdir": {
            "type": "string",
            "description": "Working directory for the job. Defaults to current directory.",
        },
    },
    required=["name", "command"],
)
def submit_job(
    name: str,
    command: str,
    priority: int = 5,
    gpu_ids: list[int] | None = None,
    mpi_ranks: int = 1,
    workdir: str | None = None,
) -> str:
    queue = _get_queue()
    job_id = queue.submit(
        name=name,
        command=command,
        priority=priority,
        gpu_ids=gpu_ids,
        mpi_ranks=mpi_ranks,
        workdir=workdir,
    )
    gpu_str = f", gpus={gpu_ids}" if gpu_ids else ""
    mpi_str = f", mpi_ranks={mpi_ranks}" if mpi_ranks > 1 else ""
    return (
        f"Job submitted successfully.\n"
        f"  id:       {job_id}\n"
        f"  name:     {name}\n"
        f"  command:  {command}\n"
        f"  priority: {priority}{gpu_str}{mpi_str}\n"
        f"  status:   pending"
    )


# ---------------------------------------------------------------------------
# list_jobs
# ---------------------------------------------------------------------------
@tool(
    name="list_jobs",
    description="List jobs in the queue, optionally filtered by status.",
    properties={
        "status": {
            "type": "string",
            "description": "Filter by status: pending, running, done, failed, cancelled. Leave empty for all.",
            "enum": ["pending", "running", "done", "failed", "cancelled", ""],
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of jobs to return (default 20).",
        },
    },
    required=[],
)
def list_jobs(status: str | None = None, limit: int = 20) -> str:
    queue = _get_queue()
    jobs = queue.list_jobs(status=status or None, limit=limit)
    if not jobs:
        label = f"status='{status}'" if status else "any status"
        return f"No jobs found with {label}."
    lines = [f"Listing {len(jobs)} job(s):\n"]
    for job in jobs:
        gpu_str = f", gpus={job['gpu_ids']}" if job.get("gpu_ids") else ""
        mpi_str = f", mpi={job['mpi_ranks']}" if job.get("mpi_ranks", 1) > 1 else ""
        lines.append(
            f"• [{job['status'].upper():10}] {job['id']}\n"
            f"  name:    {job['name']}\n"
            f"  cmd:     {job['command'][:80]}{'...' if len(job['command']) > 80 else ''}\n"
            f"  priority:{job['priority']}{gpu_str}{mpi_str}\n"
            f"  submitted:{job['submit_time']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# get_job_status
# ---------------------------------------------------------------------------
@tool(
    name="get_job_status",
    description="Get detailed information about a specific job.",
    properties={
        "job_id": {
            "type": "string",
            "description": "UUID of the job to inspect.",
        },
    },
    required=["job_id"],
)
def get_job_status(job_id: str) -> str:
    queue = _get_queue()
    job = queue.get_job(job_id)
    if job is None:
        return f"Job {job_id} not found."
    lines = [f"Job {job_id}:"]
    for key, val in job.items():
        if key == "metadata" and isinstance(val, dict):
            val = json.dumps(val)
        lines.append(f"  {key:<14}: {val}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# cancel_job
# ---------------------------------------------------------------------------
@tool(
    name="cancel_job",
    description="Cancel a pending or running job. Running jobs receive SIGTERM.",
    properties={
        "job_id": {
            "type": "string",
            "description": "UUID of the job to cancel.",
        },
    },
    required=["job_id"],
)
def cancel_job(job_id: str) -> str:
    queue = _get_queue()
    cancelled = queue.cancel_job(job_id)
    if cancelled:
        return f"Job {job_id} has been cancelled."
    job = queue.get_job(job_id)
    if job is None:
        return f"Job {job_id} not found."
    return f"Cannot cancel job {job_id} — current status is '{job['status']}'."


# ---------------------------------------------------------------------------
# get_job_log
# ---------------------------------------------------------------------------
@tool(
    name="get_job_log",
    description="Read the stdout/stderr log of a job.",
    properties={
        "job_id": {
            "type": "string",
            "description": "UUID of the job.",
        },
        "last_n_lines": {
            "type": "integer",
            "description": "Number of lines to return from the end of the log (default 50, 0 = all).",
        },
    },
    required=["job_id"],
)
def get_job_log(job_id: str, last_n_lines: int = 50) -> str:
    queue = _get_queue()
    job = queue.get_job(job_id)
    if job is None:
        return f"Job {job_id} not found."
    log_file = job.get("log_file")
    if not log_file:
        return f"No log file available for job {job_id} (status: {job['status']})."
    p = Path(log_file)
    if not p.exists():
        return f"Log file not found: {log_file}"
    try:
        lines = p.read_text(errors="replace").splitlines()
    except Exception as exc:
        return f"Error reading log: {exc}"
    if last_n_lines and len(lines) > last_n_lines:
        lines = lines[-last_n_lines:]
        header = f"=== Last {last_n_lines} lines of {log_file} ===\n"
    else:
        header = f"=== {log_file} ===\n"
    return header + "\n".join(lines)


# ---------------------------------------------------------------------------
# get_job_stats
# ---------------------------------------------------------------------------
@tool(
    name="get_job_stats",
    description="Get summary statistics for the job queue (counts by status).",
    properties={},
    required=[],
)
def get_job_stats() -> str:
    queue = _get_queue()
    stats = queue.get_stats()
    counts = stats.get("counts_by_status", {})
    lines = [
        f"Job queue statistics:",
        f"  db: {stats.get('db_path', 'unknown')}",
        f"  total jobs: {stats.get('total', 0)}",
    ]
    for status, count in sorted(counts.items()):
        lines.append(f"  {status:<12}: {count}")
    return "\n".join(lines)
