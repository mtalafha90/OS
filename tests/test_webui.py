"""Tests for the FastAPI web UI endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from llmos.webui.server import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_index_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_status_endpoint_shape(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "model" in data
    assert "ollama_url" in data
    assert "models" in data
    assert isinstance(data["models"], list)


def test_gpu_endpoint_shape(client):
    resp = client.get("/api/gpu")
    assert resp.status_code == 200
    data = resp.json()
    assert "available" in data
    assert "vendor" in data
    assert "gpus" in data
    assert isinstance(data["gpus"], list)


def test_metrics_endpoint_shape(client):
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "cpu_pct" in data
    assert "ram_pct" in data
    assert "disk_pct" in data
    assert "gpu" in data
    assert isinstance(data["gpu"], list)


def test_jobs_endpoint_returns_list(client):
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_simulations_endpoint_returns_list(client):
    resp = client.get("/api/simulations")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_plots_endpoint_returns_list(client):
    resp = client.get("/api/plots")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_clear_history(client):
    resp = client.post("/api/clear")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cleared"


def test_plot_image_404_for_missing(client):
    resp = client.get("/api/plots/image/__nonexistent_plot_xyz__.png")
    assert resp.status_code == 404


def test_plot_image_path_traversal_blocked(client):
    resp = client.get("/api/plots/image/../etc/passwd")
    assert resp.status_code == 404


def test_static_files_served(client):
    resp = client.get("/static/style.css")
    assert resp.status_code == 200


def test_submit_job_without_queue(client):
    resp = client.post("/api/jobs/submit", json={"name": "test", "command": "echo hi"})
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data


def test_cancel_job_without_queue(client):
    resp = client.delete("/api/jobs/nonexistent-job-id")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
