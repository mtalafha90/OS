"""LLM-callable tool wrappers for the simulation run tracker."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .registry import tool

if TYPE_CHECKING:
    from llmos.versioning import SimulationTracker

_tracker: SimulationTracker | None = None


def _get_tracker() -> SimulationTracker:
    global _tracker
    if _tracker is None:
        from llmos.versioning import SimulationTracker

        _tracker = SimulationTracker()
    return _tracker


# ---------------------------------------------------------------------------
# track_simulation
# ---------------------------------------------------------------------------
@tool(
    name="track_simulation",
    description=(
        "Start tracking a new simulation run. Call this before launching the simulation. "
        "Returns a run_id to be used with finish_simulation or get_simulation."
    ),
    properties={
        "name": {
            "type": "string",
            "description": "Short descriptive name for the simulation run.",
        },
        "command": {
            "type": "string",
            "description": "The exact command used to run the simulation.",
        },
        "parameters": {
            "type": "object",
            "description": 'Key-value dict of simulation parameters (e.g. {"timestep": 0.001, "box_size": 10}).',
        },
        "description": {
            "type": "string",
            "description": "Longer description of what this simulation tests or explores.",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": 'List of tags for filtering/grouping runs (e.g. ["md", "NVT", "water"]).',
        },
        "output_dir": {
            "type": "string",
            "description": "Directory where the simulation will write its output files.",
        },
    },
    required=["name"],
)
def track_simulation(
    name: str,
    command: str = "",
    parameters: dict | None = None,
    description: str = "",
    tags: list[str] | None = None,
    output_dir: str | None = None,
) -> str:
    tracker = _get_tracker()
    run_id = tracker.start_run(
        name=name,
        command=command,
        parameters=parameters,
        description=description,
        tags=tags,
        output_dir=output_dir,
    )
    return (
        f"Simulation run started.\n"
        f"  run_id:      {run_id}\n"
        f"  name:        {name}\n"
        f"  description: {description or '(none)'}\n"
        f"  tags:        {tags or []}\n"
        f"  status:      running\n\n"
        f"Use finish_simulation(run_id='{run_id}', ...) when done."
    )


# ---------------------------------------------------------------------------
# finish_simulation
# ---------------------------------------------------------------------------
@tool(
    name="finish_simulation",
    description=(
        "Mark a simulation run as complete and record its outputs and metrics. "
        "Call after the simulation finishes successfully."
    ),
    properties={
        "run_id": {
            "type": "string",
            "description": "UUID returned by track_simulation.",
        },
        "metrics": {
            "type": "object",
            "description": 'Key-value dict of result metrics (e.g. {"energy": -1234.5, "rmsd": 0.9}).',
        },
        "result_files": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of paths to output files produced by the simulation.",
        },
        "notes": {
            "type": "string",
            "description": "Freeform notes or observations about this run.",
        },
    },
    required=["run_id"],
)
def finish_simulation(
    run_id: str,
    metrics: dict | None = None,
    result_files: list[str] | None = None,
    notes: str = "",
) -> str:
    tracker = _get_tracker()
    updated = tracker.finish_run(run_id, metrics=metrics, result_files=result_files, notes=notes)
    if not updated:
        return f"Run {run_id} not found."
    metrics_str = json.dumps(metrics or {})
    return (
        f"Simulation run {run_id} marked as done.\n"
        f"  metrics:      {metrics_str}\n"
        f"  result_files: {result_files or []}\n"
        f"  notes:        {notes or '(none)'}"
    )


# ---------------------------------------------------------------------------
# list_simulations
# ---------------------------------------------------------------------------
@tool(
    name="list_simulations",
    description="List past simulation runs, optionally filtered by tag.",
    properties={
        "tag": {
            "type": "string",
            "description": "Filter by tag (e.g. 'md', 'NVT'). Leave empty to list all.",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of runs to return (default 20).",
        },
        "status": {
            "type": "string",
            "description": "Filter by status: running, done, failed. Leave empty for all.",
        },
    },
    required=[],
)
def list_simulations(
    tag: str | None = None,
    limit: int = 20,
    status: str | None = None,
) -> str:
    tracker = _get_tracker()
    runs = tracker.list_runs(tag=tag or None, limit=limit, status=status or None)
    if not runs:
        parts = []
        if tag:
            parts.append(f"tag='{tag}'")
        if status:
            parts.append(f"status='{status}'")
        label = ", ".join(parts) if parts else "any filter"
        return f"No simulation runs found for {label}."

    lines = [f"Listing {len(runs)} simulation run(s):\n"]
    for run in runs:
        metrics_preview = ""
        if run.get("metrics"):
            items = list(run["metrics"].items())[:3]
            metrics_preview = ", ".join(f"{k}={v}" for k, v in items)
            if len(run["metrics"]) > 3:
                metrics_preview += ", ..."
            metrics_preview = f"\n  metrics:  {metrics_preview}"
        lines.append(
            f"• [{run['status'].upper():8}] {run['id']}\n"
            f"  name:     {run['name']}\n"
            f"  tags:     {run.get('tags', [])}\n"
            f"  started:  {run.get('start_time', '?')}\n"
            f"  ended:    {run.get('end_time', 'still running')}"
            f"{metrics_preview}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# get_simulation
# ---------------------------------------------------------------------------
@tool(
    name="get_simulation",
    description="Get the full record of a specific simulation run.",
    properties={
        "run_id": {
            "type": "string",
            "description": "UUID of the simulation run.",
        },
    },
    required=["run_id"],
)
def get_simulation(run_id: str) -> str:
    tracker = _get_tracker()
    run = tracker.get_run(run_id)
    if run is None:
        return f"Simulation run {run_id} not found."
    lines = [f"Simulation run {run_id}:"]
    for key, val in run.items():
        if isinstance(val, (dict, list)):
            val = json.dumps(val, indent=2)
        lines.append(f"  {key:<14}: {val}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# compare_simulations
# ---------------------------------------------------------------------------
@tool(
    name="compare_simulations",
    description=(
        "Compare multiple simulation runs side-by-side. "
        "Shows all parameters and metrics across the selected runs, "
        "highlighting which values differ."
    ),
    properties={
        "run_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of run UUIDs to compare (2 or more).",
        },
    },
    required=["run_ids"],
)
def compare_simulations(run_ids: list[str]) -> str:
    tracker = _get_tracker()
    comparison = tracker.compare_runs(run_ids)

    if "error" in comparison:
        return comparison["error"]

    runs = comparison["runs"]
    params = comparison["parameters"]
    metrics_data = comparison["metrics"]

    if not runs:
        return "No runs found for the provided IDs."

    # Header row
    id_labels = {r["id"]: f"{r['name'][:20]} ({r['id'][:8]})" for r in runs}
    col_ids = [r["id"] for r in runs]

    lines = ["=== Simulation Comparison ===\n"]

    # Run summary
    lines.append("Runs:")
    for r in runs:
        if r.get("end_time") and r.get("start_time"):
            lines.append(
                f"  {r['id'][:8]}  [{r['status']:8}]  {r['name']}  tags={r.get('tags', [])}"
            )
        else:
            lines.append(f"  {r['id'][:8]}  [{r['status']:8}]  {r['name']}  (still running)")

    # Parameters table
    if params:
        lines.append("\nParameters:")
        header = f"  {'Parameter':<30} " + "  ".join(f"{id_labels[cid]:<30}" for cid in col_ids)
        lines.append(header)
        lines.append("  " + "-" * (30 + 32 * len(col_ids)))
        for param_key in sorted(params):
            vals = params[param_key]
            unique_vals = set(str(v) for v in vals.values())
            flag = " *" if len(unique_vals) > 1 else ""
            row = f"  {param_key:<30} " + "  ".join(
                f"{str(vals.get(cid, 'N/A')):<30}" for cid in col_ids
            )
            lines.append(row + flag)

    # Metrics table
    if metrics_data:
        lines.append("\nMetrics:")
        header = f"  {'Metric':<30} " + "  ".join(f"{id_labels[cid]:<30}" for cid in col_ids)
        lines.append(header)
        lines.append("  " + "-" * (30 + 32 * len(col_ids)))
        for metric_key in sorted(metrics_data):
            vals = metrics_data[metric_key]
            unique_vals = set(str(v) for v in vals.values())
            flag = " *" if len(unique_vals) > 1 else ""
            row = f"  {metric_key:<30} " + "  ".join(
                f"{str(vals.get(cid, 'N/A')):<30}" for cid in col_ids
            )
            lines.append(row + flag)

    lines.append("\n(* = values differ across runs)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# search_simulations
# ---------------------------------------------------------------------------
@tool(
    name="search_simulations",
    description="Search simulation runs by name, description, tags, or notes.",
    properties={
        "query": {
            "type": "string",
            "description": "Search query (e.g. 'water NVT equilibration', 'failed run', 'timestep 0.002').",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of results to return (default 10).",
        },
    },
    required=["query"],
)
def search_simulations(query: str, limit: int = 10) -> str:
    tracker = _get_tracker()
    runs = tracker.search_runs(query, limit=limit)
    if not runs:
        return f"No simulation runs found matching '{query}'."
    lines = [f"Found {len(runs)} run(s) matching '{query}':\n"]
    for run in runs:
        desc_preview = run.get("description", "")[:60]
        if len(run.get("description", "")) > 60:
            desc_preview += "..."
        lines.append(
            f"• [{run['status'].upper():8}] {run['id']}\n"
            f"  name:    {run['name']}\n"
            f"  desc:    {desc_preview or '(none)'}\n"
            f"  tags:    {run.get('tags', [])}\n"
            f"  started: {run.get('start_time', '?')}"
        )
    return "\n".join(lines)
