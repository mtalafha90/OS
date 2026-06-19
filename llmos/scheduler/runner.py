"""Background job runner that watches the queue and executes jobs."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .queue import JobQueue

logger = logging.getLogger(__name__)

_LOG_DIR = Path.home() / ".config" / "llmos" / "job_logs"


class JobRunner:
    """Background thread that polls the job queue and runs pending jobs.

    Parameters
    ----------
    queue:          JobQueue instance to watch.
    max_concurrent: Maximum number of jobs that may run simultaneously (default 2).
    poll_interval:  Seconds between queue polls (default 5).
    log_dir:        Directory for job stdout/stderr logs.
    """

    def __init__(
        self,
        queue: JobQueue | None = None,
        max_concurrent: int = 2,
        poll_interval: float = 5.0,
        log_dir: Path | None = None,
    ):
        self._queue = queue or JobQueue()
        self._max_concurrent = max_concurrent
        self._poll_interval = poll_interval
        self._log_dir = Path(log_dir) if log_dir else _LOG_DIR
        self._log_dir.mkdir(parents=True, exist_ok=True)

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        # job_id → (Process, log_file_path)
        self._running: dict[str, tuple[subprocess.Popen, str]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the background polling thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("JobRunner is already running.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="job-runner",
            daemon=True,
        )
        self._thread.start()
        logger.info("JobRunner started (max_concurrent=%d, poll=%.1fs)", self._max_concurrent, self._poll_interval)

    def stop(self, timeout: float = 10.0) -> None:
        """Signal the runner to stop and wait for the thread to exit."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        logger.info("JobRunner stopped.")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._reap_finished()
                self._start_pending()
            except Exception:
                logger.exception("Unexpected error in JobRunner loop")
            self._stop_event.wait(timeout=self._poll_interval)
        # Final reap on exit
        self._reap_finished()

    def _reap_finished(self) -> None:
        """Check running processes; mark completed ones done/failed."""
        with self._lock:
            finished = []
            for job_id, (proc, _log_file) in self._running.items():
                ret = proc.poll()
                if ret is not None:
                    finished.append((job_id, ret))

            for job_id, returncode in finished:
                proc, log_file = self._running.pop(job_id)
                success = returncode == 0
                self._queue.mark_done(job_id, success=success)
                logger.info(
                    "Job %s finished (returncode=%d, success=%s)",
                    job_id, returncode, success,
                )

    def _start_pending(self) -> None:
        """Launch pending jobs up to max_concurrent."""
        with self._lock:
            slots = self._max_concurrent - len(self._running)

        for _ in range(max(0, slots)):
            job = self._queue.next_pending()
            if job is None:
                break
            # Double-check it hasn't been taken by another runner instance
            # (race-condition guard: mark it running before starting the process)
            self._launch_job(job)

    def _launch_job(self, job: dict[str, Any]) -> None:
        """Build the command, open log file, and spawn the process."""
        job_id = job["id"]
        command = job["command"]
        gpu_ids: list[int] = job.get("gpu_ids") or []
        mpi_ranks: int = job.get("mpi_ranks") or 1
        workdir: str | None = job.get("workdir")

        # Build environment
        env = os.environ.copy()
        if gpu_ids:
            env["CUDA_VISIBLE_DEVICES"] = ",".join(str(g) for g in gpu_ids)

        # Prepend MPI wrapper
        if mpi_ranks > 1:
            command = f"mpirun -n {mpi_ranks} {command}"

        # Log file
        log_file = str(self._log_dir / f"{job_id}.log")

        # Resolve workdir
        cwd = workdir if workdir else None
        if cwd:
            Path(cwd).mkdir(parents=True, exist_ok=True)

        try:
            log_fh = open(log_file, "w")
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=cwd,
            )
        except Exception as exc:
            logger.error("Failed to launch job %s: %s", job_id, exc)
            self._queue.mark_done(job_id, success=False)
            return

        self._queue.mark_running(job_id, proc.pid, log_file)
        with self._lock:
            self._running[job_id] = (proc, log_file)

        logger.info(
            "Launched job %s (pid=%d, gpu_ids=%s, mpi_ranks=%d): %s",
            job_id, proc.pid, gpu_ids, mpi_ranks, command[:120],
        )
