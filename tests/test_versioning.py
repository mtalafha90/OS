"""Tests for the SimulationTracker."""
from __future__ import annotations

import pytest

from llmos.versioning.tracker import SimulationTracker


@pytest.fixture
def tracker(tmp_path):
    return SimulationTracker(db_path=str(tmp_path / "sims.db"))


def test_start_run_returns_uuid(tracker):
    run_id = tracker.start_run(name="sim_a", parameters={"n": 100})
    assert isinstance(run_id, str)
    assert len(run_id) == 36


def test_get_run_after_start(tracker):
    run_id = tracker.start_run(
        name="my_sim",
        parameters={"alpha": 0.01, "steps": 1000},
        description="test run",
        tags=["test", "debug"],
    )
    run = tracker.get_run(run_id)
    assert run is not None
    assert run["name"] == "my_sim"
    assert run["status"] == "running"
    assert run["parameters"] == {"alpha": 0.01, "steps": 1000}
    assert "test" in run["tags"]


def test_get_run_nonexistent(tracker):
    assert tracker.get_run("00000000-0000-0000-0000-000000000000") is None


def test_finish_run(tracker):
    run_id = tracker.start_run(name="finish_me", parameters={"x": 1})
    result = tracker.finish_run(run_id, metrics={"loss": 0.42, "accuracy": 0.95})
    assert result is True
    run = tracker.get_run(run_id)
    assert run["status"] == "done"
    assert run["metrics"]["loss"] == pytest.approx(0.42)
    assert run["metrics"]["accuracy"] == pytest.approx(0.95)
    assert run["end_time"] is not None


def test_fail_run(tracker):
    run_id = tracker.start_run(name="fail_me", parameters={})
    result = tracker.fail_run(run_id, error="out of memory")
    assert result is True
    run = tracker.get_run(run_id)
    assert run["status"] == "failed"
    assert "memory" in run["notes"]


def test_list_runs_empty(tracker):
    assert tracker.list_runs() == []


def test_list_runs_all(tracker):
    tracker.start_run(name="run_a", parameters={"x": 1})
    tracker.start_run(name="run_b", parameters={"x": 2})
    runs = tracker.list_runs()
    assert len(runs) == 2
    names = {r["name"] for r in runs}
    assert "run_a" in names
    assert "run_b" in names


def test_list_runs_filter_by_status(tracker):
    id1 = tracker.start_run(name="running_sim", parameters={})
    id2 = tracker.start_run(name="done_sim", parameters={})
    tracker.finish_run(id2, metrics={})

    running = tracker.list_runs(status="running")
    assert all(r["status"] == "running" for r in running)

    done = tracker.list_runs(status="done")
    assert all(r["status"] == "done" for r in done)


def test_list_runs_filter_by_tag(tracker):
    tracker.start_run(name="tagged", parameters={}, tags=["gpu", "production"])
    tracker.start_run(name="untagged", parameters={})
    gpu_runs = tracker.list_runs(tag="gpu")
    names = {r["name"] for r in gpu_runs}
    assert "tagged" in names
    assert "untagged" not in names


def test_search_runs(tracker):
    tracker.start_run(name="hydrogen_bond_simulation", parameters={"molecule": "H2O"})
    tracker.start_run(name="protein_folding", parameters={"protein": "P53"})
    results = tracker.search_runs("hydrogen")
    names = {r["name"] for r in results}
    assert "hydrogen_bond_simulation" in names
    assert "protein_folding" not in names


def test_search_runs_no_match(tracker):
    tracker.start_run(name="something", parameters={})
    results = tracker.search_runs("__no_match_xyz_term__")
    assert results == []


def test_compare_runs(tracker):
    id1 = tracker.start_run(name="run1", parameters={"lr": 0.001, "batch": 32})
    tracker.finish_run(id1, metrics={"loss": 0.5, "accuracy": 0.8})
    id2 = tracker.start_run(name="run2", parameters={"lr": 0.01, "batch": 64})
    tracker.finish_run(id2, metrics={"loss": 0.3, "accuracy": 0.9})

    comparison = tracker.compare_runs([id1, id2])
    assert "runs" in comparison
    assert "parameters" in comparison
    assert "metrics" in comparison
    assert "lr" in comparison["parameters"]
    assert "loss" in comparison["metrics"]
    assert len(comparison["runs"]) == 2


def test_compare_runs_nonexistent(tracker):
    comparison = tracker.compare_runs(["00000000-0000-0000-0000-000000000000"])
    assert "error" in comparison or comparison["runs"] == []
