"""Tests for the SQLite-backed job queue."""
from __future__ import annotations

import pytest

from llmos.scheduler.queue import JobQueue


@pytest.fixture
def queue(tmp_path):
    return JobQueue(db_path=str(tmp_path / "jobs.db"))


def test_submit_returns_uuid(queue):
    job_id = queue.submit(name="myjob", command="echo hi", workdir="/tmp")
    assert isinstance(job_id, str)
    assert len(job_id) == 36  # UUID format


def test_get_job_after_submit(queue):
    job_id = queue.submit(name="testjob", command="sleep 1", workdir="/tmp", priority=7)
    job = queue.get_job(job_id)
    assert job is not None
    assert job["name"] == "testjob"
    assert job["command"] == "sleep 1"
    assert job["status"] == "pending"
    assert job["priority"] == 7


def test_get_job_nonexistent(queue):
    result = queue.get_job("00000000-0000-0000-0000-000000000000")
    assert result is None


def test_list_jobs_empty(queue):
    assert queue.list_jobs() == []


def test_list_jobs_returns_all(queue):
    queue.submit(name="j1", command="echo 1", workdir="/tmp")
    queue.submit(name="j2", command="echo 2", workdir="/tmp")
    jobs = queue.list_jobs()
    assert len(jobs) == 2
    names = {j["name"] for j in jobs}
    assert names == {"j1", "j2"}


def test_list_jobs_filter_by_status(queue):
    j1 = queue.submit(name="pending_job", command="echo", workdir="/tmp")
    j2 = queue.submit(name="cancel_me", command="echo", workdir="/tmp")
    queue.cancel_job(j2)

    pending = queue.list_jobs(status="pending")
    assert all(j["status"] == "pending" for j in pending)
    assert any(j["name"] == "pending_job" for j in pending)

    cancelled = queue.list_jobs(status="cancelled")
    assert all(j["status"] == "cancelled" for j in cancelled)


def test_cancel_pending_job(queue):
    job_id = queue.submit(name="tocancel", command="sleep 999", workdir="/tmp")
    assert queue.cancel_job(job_id) is True
    assert queue.get_job(job_id)["status"] == "cancelled"


def test_cancel_nonexistent_returns_false(queue):
    assert queue.cancel_job("00000000-0000-0000-0000-000000000000") is False


def test_cancel_already_cancelled(queue):
    job_id = queue.submit(name="double_cancel", command="echo", workdir="/tmp")
    queue.cancel_job(job_id)
    assert queue.cancel_job(job_id) is False


def test_priority_clipped(queue):
    j_low = queue.submit(name="low", command="echo", workdir="/tmp", priority=0)
    j_high = queue.submit(name="high", command="echo", workdir="/tmp", priority=99)
    assert queue.get_job(j_low)["priority"] == 1
    assert queue.get_job(j_high)["priority"] == 10


def test_next_pending_respects_priority(queue):
    queue.submit(name="low", command="echo lo", workdir="/tmp", priority=1)
    queue.submit(name="high", command="echo hi", workdir="/tmp", priority=9)
    queue.submit(name="mid", command="echo mid", workdir="/tmp", priority=5)
    next_job = queue.next_pending()
    assert next_job is not None
    assert next_job["name"] == "high"


def test_next_pending_empty(queue):
    assert queue.next_pending() is None


def test_mark_running_and_done(queue):
    job_id = queue.submit(name="runner", command="echo", workdir="/tmp")
    queue.mark_running(job_id, pid=12345, log_file="/tmp/runner.log")
    job = queue.get_job(job_id)
    assert job["status"] == "running"
    assert job["pid"] == 12345

    queue.mark_done(job_id, success=True)
    assert queue.get_job(job_id)["status"] == "done"


def test_mark_done_failure(queue):
    job_id = queue.submit(name="failer", command="exit 1", workdir="/tmp")
    queue.mark_running(job_id, pid=9999, log_file="/tmp/failer.log")
    queue.mark_done(job_id, success=False)
    assert queue.get_job(job_id)["status"] == "failed"


def test_get_stats(queue):
    queue.submit(name="a", command="echo", workdir="/tmp")
    j2 = queue.submit(name="b", command="echo", workdir="/tmp")
    queue.cancel_job(j2)

    stats = queue.get_stats()
    assert "db_path" in stats
    assert "counts_by_status" in stats
    assert stats["counts_by_status"].get("pending", 0) >= 1
    assert stats["counts_by_status"].get("cancelled", 0) >= 1
    assert stats["total"] >= 2


def test_gpu_ids_stored_as_list(queue):
    job_id = queue.submit(name="gpu_job", command="python train.py", workdir="/tmp", gpu_ids=[0, 1])
    job = queue.get_job(job_id)
    assert job["gpu_ids"] == [0, 1]
