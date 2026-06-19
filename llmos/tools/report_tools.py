"""LLM-callable tools for report generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .registry import tool


def _default_output_dir() -> Path:
    p = Path("~/reports").expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get_generator():
    from llmos.reports import ReportGenerator

    return ReportGenerator()


@tool(
    name="generate_report",
    description=(
        "Generate an HTML or PDF report from structured content sections.  "
        "Returns the path(s) to the generated file(s)."
    ),
    properties={
        "title": {
            "type": "string",
            "description": "Report title.",
        },
        "content_sections": {
            "type": "array",
            "items": {
                "type": "object",
                "description": (
                    "Section with keys: title (str), content (str), "
                    "type ('text'|'code'|'table'|'image'), data (optional)."
                ),
            },
            "description": "List of content sections to include in the report.",
        },
        "output_path": {
            "type": "string",
            "description": (
                "Destination file path.  Extension (.html / .pdf) determines format "
                "when 'format' is omitted.  Defaults to ~/reports/<title>.<ext>."
            ),
        },
        "format": {
            "type": "string",
            "description": "Output format: 'html', 'pdf', or 'both' (default: 'html').",
        },
    },
    required=["title", "content_sections"],
)
def generate_report(
    title: str,
    content_sections: list[dict[str, Any]],
    output_path: str | None = None,
    format: str = "html",
) -> str:
    gen = _get_generator()
    fmt = (format or "html").lower()

    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)[:60]
    default_dir = _default_output_dir()

    results: list[str] = []

    if fmt in ("html", "both"):
        html_out = output_path or str(default_dir / f"{safe_title}.html")
        if not html_out.endswith(".html"):
            html_out = html_out.rstrip("/") + ".html"
        path = gen.generate_html_report(title, content_sections, html_out)
        results.append(f"HTML report: {path}")

    if fmt in ("pdf", "both"):
        pdf_out = output_path or str(default_dir / f"{safe_title}.pdf")
        if not pdf_out.endswith(".pdf"):
            pdf_out = pdf_out.rstrip("/") + ".pdf"
        path = gen.generate_pdf_report(title, content_sections, pdf_out)
        results.append(f"PDF report: {path}")

    if not results:
        return f"Unknown format '{format}'. Use 'html', 'pdf', or 'both'."

    return "\n".join(results)


@tool(
    name="create_simulation_report",
    description=(
        "Auto-generate a complete simulation report for a given run ID.  "
        "Pulls run metadata from the versioning tracker if available.  "
        "Returns paths to the generated HTML and PDF files."
    ),
    properties={
        "run_id": {
            "type": "string",
            "description": "Simulation run ID to report on.",
        },
        "notes": {
            "type": "string",
            "description": "Free-form notes to append to the report.",
        },
        "output_dir": {
            "type": "string",
            "description": "Directory for output files (default: ~/reports/).",
        },
    },
    required=["run_id"],
)
def create_simulation_report(
    run_id: str,
    notes: str = "",
    output_dir: str = "~/reports",
) -> str:
    gen = _get_generator()

    # Try to load run data from the versioning tracker
    run_data: dict[str, Any] = {"run_id": run_id}
    plots: list[str] = []
    metrics: dict[str, Any] = {}

    try:
        # Attempt to locate a run JSON produced by versioning/tracker
        candidates = [
            Path(f"~/.config/llmos/runs/{run_id}.json").expanduser(),
            Path(f"~/runs/{run_id}.json").expanduser(),
            Path(f"/tmp/llmos_run_{run_id}.json"),
        ]
        for c in candidates:
            if c.exists():
                loaded = json.loads(c.read_text())
                run_data.update(loaded)
                plots = loaded.get("plots", [])
                metrics = loaded.get("metrics", {})
                break
    except Exception:
        pass

    # Look for any plot images associated with this run_id in ~/plots/
    plots_dir = Path("~/plots").expanduser()
    if plots_dir.exists():
        for img in sorted(plots_dir.glob(f"*{run_id}*")):
            if img.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg"):
                if str(img) not in plots:
                    plots.append(str(img))

    result = gen.create_simulation_report(
        run_data=run_data,
        plots=plots,
        metrics=metrics,
        notes=notes,
        output_dir=output_dir,
    )

    return (
        f"Simulation report generated for run '{run_id}':\n"
        f"  HTML: {result['html_path']}\n"
        f"  PDF:  {result['pdf_path']}"
    )


@tool(
    name="list_reports",
    description="List generated reports in ~/reports/ (sorted by modification time, newest first).",
    properties={
        "directory": {
            "type": "string",
            "description": "Directory to list reports from (default: ~/reports/).",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of reports to list (default: 50).",
        },
    },
    required=[],
)
def list_reports(directory: str = "~/reports", limit: int = 50) -> str:
    reports_dir = Path(directory).expanduser()
    if not reports_dir.exists():
        return f"Reports directory '{reports_dir}' does not exist yet."

    exts = {".html", ".pdf"}
    files = [f for f in reports_dir.iterdir() if f.is_file() and f.suffix.lower() in exts]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    files = files[:limit]

    if not files:
        return f"No reports found in {reports_dir}."

    lines = [f"Reports in {reports_dir} ({len(files)} files):"]
    for f in files:
        import datetime

        mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime)
        size_kb = f.stat().st_size / 1024
        lines.append(f"  {f.name:<50s}  {size_kb:7.1f} KB  {mtime.strftime('%Y-%m-%d %H:%M')}")
    return "\n".join(lines)
