"""Auto-report generation for LLM-OS simulation results.

Generates rich HTML reports (always) and PDF via reportlab, weasyprint, or
wkhtmltopdf (tried in that order).
"""

from __future__ import annotations

import base64
import datetime
import html
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

Section = dict[str, Any]
"""
Expected keys
    title   : str
    content : str          — narrative text shown above the section body
    type    : "text" | "code" | "table" | "image"
    data    : depends on type
        text  → None (content is the body)
        code  → str  (source code)
        table → list[dict]  (rows)
        image → str  (file path or base64 PNG/JPEG string)
"""


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """
:root {
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --accent: #58a6ff;
    --accent2: #3fb950;
    --text: #c9d1d9;
    --text-dim: #8b949e;
    --code-bg: #1e2a3a;
    --danger: #f85149;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    font-size: 15px;
    line-height: 1.65;
}

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ── Cover page ── */
.cover {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    background: linear-gradient(135deg, #0d1117 0%, #161b22 50%, #0d1117 100%);
    border-bottom: 1px solid var(--border);
    padding: 4rem 2rem;
}

.cover h1 {
    font-size: 2.8rem;
    font-weight: 700;
    color: var(--accent);
    letter-spacing: -0.5px;
    margin-bottom: 1.2rem;
}

.cover .subtitle {
    font-size: 1.1rem;
    color: var(--text-dim);
    margin-bottom: 2.5rem;
}

.cover .meta-table {
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    min-width: 360px;
}

.cover .meta-table td {
    padding: 0.55rem 1.2rem;
    border-bottom: 1px solid var(--border);
}

.cover .meta-table td:first-child {
    color: var(--text-dim);
    font-weight: 600;
    background: var(--surface);
    width: 130px;
}

.cover .meta-table tr:last-child td { border-bottom: none; }

/* ── Navigation ── */
nav {
    position: sticky;
    top: 0;
    z-index: 100;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 0.6rem 2rem;
    display: flex;
    gap: 1.5rem;
    overflow-x: auto;
}

nav a {
    font-size: 0.85rem;
    color: var(--text-dim);
    white-space: nowrap;
}

nav a:hover { color: var(--accent); }

/* ── Main content ── */
main {
    max-width: 1100px;
    margin: 0 auto;
    padding: 3rem 2rem;
}

/* ── Sections ── */
.section {
    margin-bottom: 4rem;
    padding-bottom: 2rem;
    border-bottom: 1px solid var(--border);
}

.section:last-child { border-bottom: none; }

.section-header {
    display: flex;
    align-items: baseline;
    gap: 0.75rem;
    margin-bottom: 1.2rem;
}

.section-num {
    font-size: 0.8rem;
    font-weight: 700;
    color: var(--accent);
    background: rgba(88,166,255,.12);
    border: 1px solid rgba(88,166,255,.3);
    padding: 0.1rem 0.55rem;
    border-radius: 4px;
    letter-spacing: 0.5px;
}

.section h2 {
    font-size: 1.45rem;
    font-weight: 600;
    color: var(--text);
}

.section-content {
    color: var(--text);
    margin-bottom: 1rem;
    white-space: pre-wrap;
    word-break: break-word;
}

/* ── Code ── */
.code-block {
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: 6px;
    padding: 1.2rem 1.4rem;
    overflow-x: auto;
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 0.85rem;
    line-height: 1.6;
    color: #e6edf3;
    white-space: pre;
}

/* ── Tables ── */
.data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
    margin-top: 0.5rem;
}

.data-table th {
    background: var(--surface);
    color: var(--accent);
    font-weight: 600;
    padding: 0.6rem 1rem;
    text-align: left;
    border: 1px solid var(--border);
}

.data-table td {
    padding: 0.55rem 1rem;
    border: 1px solid var(--border);
    color: var(--text);
}

.data-table tr:nth-child(even) td {
    background: rgba(255,255,255,.02);
}

.data-table tr:hover td {
    background: rgba(88,166,255,.06);
}

/* ── Images ── */
.figure {
    text-align: center;
    margin-top: 0.75rem;
}

.figure img {
    max-width: 100%;
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: 0 4px 24px rgba(0,0,0,.4);
}

.figure figcaption {
    margin-top: 0.5rem;
    font-size: 0.85rem;
    color: var(--text-dim);
}

/* ── Footer ── */
footer {
    text-align: center;
    padding: 2rem;
    color: var(--text-dim);
    font-size: 0.8rem;
    border-top: 1px solid var(--border);
    margin-top: 4rem;
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64_from_path(path: str) -> str:
    """Read an image file and return a base64 data-URI."""
    p = Path(path).expanduser()
    suffix = p.suffix.lower().lstrip(".")
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "svg": "image/svg+xml",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(suffix, "image/png")
    data = base64.b64encode(p.read_bytes()).decode()
    return f"data:{mime};base64,{data}"


def _is_base64(s: str) -> bool:
    return s.startswith("data:") or (len(s) > 100 and "\n" not in s[:100])


def _render_section_body(section: Section, idx: int) -> str:
    """Return the HTML body (below the header) for one section."""
    stype = section.get("type", "text")
    content = section.get("content", "")
    data = section.get("data")
    parts: list[str] = []

    if content:
        parts.append(f'<div class="section-content">{html.escape(content)}</div>')

    if stype == "code" and data:
        escaped = html.escape(str(data))
        parts.append(f'<pre class="code-block">{escaped}</pre>')

    elif stype == "table" and data:
        rows: list[dict] = data if isinstance(data, list) else []
        if rows:
            headers = list(rows[0].keys())
            header_html = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
            row_htmls: list[str] = []
            for row in rows:
                cells = "".join(f"<td>{html.escape(str(row.get(h, '')))}</td>" for h in headers)
                row_htmls.append(f"<tr>{cells}</tr>")
            parts.append(
                f'<table class="data-table">'
                f"<thead><tr>{header_html}</tr></thead>"
                f"<tbody>{''.join(row_htmls)}</tbody>"
                f"</table>"
            )

    elif stype == "image" and data:
        if isinstance(data, str):
            if data.startswith("data:"):
                src = data
            elif Path(data).expanduser().exists():
                src = _b64_from_path(data)
            else:
                # Assume raw base64 PNG
                src = f"data:image/png;base64,{data}"
        else:
            src = ""

        if src:
            caption = html.escape(section.get("title", f"Figure {idx}"))
            parts.append(
                f'<figure class="figure">'
                f'<img src="{src}" alt="{caption}">'
                f"<figcaption>{caption}</figcaption>"
                f"</figure>"
            )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# ReportGenerator
# ---------------------------------------------------------------------------


class ReportGenerator:
    """Generate HTML and PDF reports for simulation results."""

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def generate_html_report(
        self,
        title: str,
        sections: list[Section],
        output_path: str,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Generate a rich HTML report and save it to *output_path*.

        Args:
            title:       Report title shown on the cover page.
            sections:    List of section dicts (see module docstring).
            output_path: Destination file path.
            metadata:    Optional key→value pairs shown in the cover table.

        Returns:
            Absolute path to the written HTML file.
        """
        out = Path(output_path).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)

        now = datetime.datetime.now()
        meta = {
            "Generated": now.strftime("%Y-%m-%d %H:%M:%S"),
            "System": "LLM-OS",
            **(metadata or {}),
        }

        # ── Navigation ──
        nav_links = "".join(
            f'<a href="#section-{i}">{html.escape(s.get("title", f"Section {i}"))}</a>'
            for i, s in enumerate(sections, 1)
        )

        # ── Cover metadata table ──
        meta_rows = "".join(
            f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>"
            for k, v in meta.items()
        )

        # ── Section bodies ──
        section_html_parts: list[str] = []
        for i, sec in enumerate(sections, 1):
            sid = f"section-{i}"
            sec_title = html.escape(sec.get("title", f"Section {i}"))
            body = _render_section_body(sec, i)
            section_html_parts.append(
                f'<section class="section" id="{sid}">'
                f'<div class="section-header">'
                f'<span class="section-num">{i:02d}</span>'
                f"<h2>{sec_title}</h2>"
                f"</div>"
                f"{body}"
                f"</section>"
            )

        sections_html = "\n".join(section_html_parts)
        esc_title = html.escape(title)

        doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc_title}</title>
<style>
{_CSS}
</style>
</head>
<body>

<div class="cover">
  <h1>{esc_title}</h1>
  <p class="subtitle">Simulation Report — LLM-OS</p>
  <table class="meta-table">
    <tbody>{meta_rows}</tbody>
  </table>
</div>

<nav>{nav_links}</nav>

<main>
{sections_html}
</main>

<footer>
  Generated by LLM-OS ReportGenerator &mdash; {html.escape(now.strftime("%Y-%m-%d %H:%M:%S"))}
</footer>

</body>
</html>"""

        out.write_text(doc, encoding="utf-8")
        return str(out.resolve())

    # -----------------------------------------------------------------------

    def generate_pdf_report(
        self,
        title: str,
        sections: list[Section],
        output_path: str,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Generate a PDF report.

        Tries in order:
          1. reportlab
          2. weasyprint
          3. wkhtmltopdf (CLI)
          4. Falls back to writing an HTML file with a .pdf extension and a
             warning comment.

        Args:
            title, sections, output_path, metadata: same as generate_html_report.

        Returns:
            Absolute path to the generated file.
        """
        out = Path(output_path).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)

        # First produce HTML in a temp file
        with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", delete=False, prefix="/tmp/llmos_report_"
        ) as tf:
            html_tmp = tf.name
        try:
            self.generate_html_report(title, sections, html_tmp, metadata)

            # ── 1. reportlab ─────────────────────────────────────────────
            if self._try_reportlab(title, sections, str(out), metadata):
                return str(out.resolve())

            # ── 2. weasyprint ─────────────────────────────────────────────
            if self._try_weasyprint(html_tmp, str(out)):
                return str(out.resolve())

            # ── 3. wkhtmltopdf ───────────────────────────────────────────
            if self._try_wkhtmltopdf(html_tmp, str(out)):
                return str(out.resolve())

            # ── 4. Fallback: rename HTML → .pdf path ─────────────────────
            import shutil

            shutil.copy(html_tmp, str(out))
            # Prepend a comment so readers know
            content = out.read_text(encoding="utf-8")
            out.write_text(
                "<!-- PDF generation failed; this is an HTML file. -->\n" + content,
                encoding="utf-8",
            )
            return str(out.resolve())

        finally:
            try:
                os.unlink(html_tmp)
            except OSError:
                pass

    # -----------------------------------------------------------------------

    def create_simulation_report(
        self,
        run_data: dict[str, Any],
        plots: list[str] | None = None,
        metrics: dict[str, Any] | None = None,
        notes: str = "",
        output_dir: str = "~/reports",
    ) -> dict[str, str]:
        """High-level: build a complete simulation report from run data.

        Args:
            run_data:   Dict with simulation metadata (run_id, start_time,
                        command, parameters, …).
            plots:      List of image file paths to embed.
            metrics:    Dict of scalar metrics to show as a table.
            notes:      Free-form notes to include.
            output_dir: Directory for output files (default ~/reports).

        Returns:
            {"html_path": "...", "pdf_path": "..."}
        """
        run_id = run_data.get("run_id", "unknown")
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"sim_{run_id}_{ts}"
        base = Path(output_dir).expanduser()
        base.mkdir(parents=True, exist_ok=True)

        title = f"Simulation Report — {run_id}"
        sections: list[Section] = []

        # 1. Overview
        overview_lines = [f"Run ID: {run_id}"]
        for k, v in run_data.items():
            if k != "run_id":
                overview_lines.append(f"{k}: {v}")
        sections.append(
            {
                "title": "Overview",
                "content": "\n".join(overview_lines),
                "type": "text",
            }
        )

        # 2. Parameters
        params = run_data.get("parameters")
        if params and isinstance(params, dict):
            rows = [{"Parameter": k, "Value": str(v)} for k, v in params.items()]
            sections.append(
                {
                    "title": "Parameters",
                    "content": "Simulation parameters used for this run.",
                    "type": "table",
                    "data": rows,
                }
            )

        # 3. Metrics
        if metrics:
            rows = [{"Metric": k, "Value": str(v)} for k, v in metrics.items()]
            sections.append(
                {
                    "title": "Performance Metrics",
                    "content": "Key metrics recorded during the simulation.",
                    "type": "table",
                    "data": rows,
                }
            )

        # 4. Plots
        for i, plot_path in enumerate(plots or [], 1):
            if Path(plot_path).expanduser().exists():
                sections.append(
                    {
                        "title": f"Figure {i}: {Path(plot_path).stem}",
                        "content": "",
                        "type": "image",
                        "data": plot_path,
                    }
                )

        # 5. Raw data (JSON dump)
        sections.append(
            {
                "title": "Raw Run Data",
                "content": "Complete JSON dump of the run metadata.",
                "type": "code",
                "data": json.dumps(run_data, indent=2, default=str),
            }
        )

        # 6. Notes
        if notes:
            sections.append(
                {
                    "title": "Notes",
                    "content": notes,
                    "type": "text",
                }
            )

        html_path = self.generate_html_report(
            title,
            sections,
            str(base / f"{stem}.html"),
            metadata={"Run ID": run_id},
        )
        pdf_path = self.generate_pdf_report(
            title,
            sections,
            str(base / f"{stem}.pdf"),
            metadata={"Run ID": run_id},
        )

        return {"html_path": html_path, "pdf_path": pdf_path}

    # -----------------------------------------------------------------------
    # Private PDF back-ends
    # -----------------------------------------------------------------------

    def _try_reportlab(
        self,
        title: str,
        sections: list[Section],
        output_path: str,
        metadata: dict[str, str] | None,
    ) -> bool:
        """Attempt PDF generation with reportlab.  Returns True on success."""
        try:
            from reportlab.lib import colors  # type: ignore
            from reportlab.lib.pagesizes import A4  # type: ignore
            from reportlab.lib.styles import getSampleStyleSheet  # type: ignore
            from reportlab.lib.units import cm  # type: ignore
            from reportlab.platypus import (
                Image as RLImage,
            )
            from reportlab.platypus import (  # type: ignore
                Paragraph,
                Preformatted,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )

            doc = SimpleDocTemplate(output_path, pagesize=A4)
            styles = getSampleStyleSheet()
            story = []

            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            story.append(Paragraph(title, styles["Title"]))
            story.append(Spacer(1, 0.3 * cm))
            story.append(Paragraph(f"Generated: {now}", styles["Normal"]))
            story.append(Spacer(1, 1 * cm))

            for sec in sections:
                story.append(Paragraph(sec.get("title", ""), styles["Heading2"]))
                story.append(Spacer(1, 0.2 * cm))

                content = sec.get("content", "")
                if content:
                    story.append(Paragraph(html.escape(content), styles["Normal"]))
                    story.append(Spacer(1, 0.3 * cm))

                stype = sec.get("type", "text")
                data = sec.get("data")

                if stype == "code" and data:
                    story.append(Preformatted(str(data), styles["Code"]))

                elif stype == "table" and isinstance(data, list) and data:
                    headers = list(data[0].keys())
                    table_data = [headers] + [
                        [str(row.get(h, "")) for h in headers] for row in data
                    ]
                    tbl = Table(table_data)
                    tbl.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#161b22")),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#58a6ff")),
                                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#30363d")),
                                ("FONTSIZE", (0, 0), (-1, -1), 9),
                            ]
                        )
                    )
                    story.append(tbl)

                elif stype == "image" and data:
                    img_path = None
                    if isinstance(data, str):
                        if data.startswith("data:"):
                            # decode base64
                            header, b64 = data.split(",", 1)
                            raw = base64.b64decode(b64)
                            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                                tf.write(raw)
                                img_path = tf.name
                        elif Path(data).expanduser().exists():
                            img_path = str(Path(data).expanduser())
                    if img_path:
                        try:
                            story.append(RLImage(img_path, width=14 * cm))
                        except Exception:
                            pass

                story.append(Spacer(1, 0.5 * cm))

            doc.build(story)
            return True
        except ImportError:
            return False
        except Exception:
            return False

    def _try_weasyprint(self, html_path: str, output_path: str) -> bool:
        try:
            import weasyprint  # type: ignore

            weasyprint.HTML(filename=html_path).write_pdf(output_path)
            return True
        except ImportError:
            return False
        except Exception:
            return False

    def _try_wkhtmltopdf(self, html_path: str, output_path: str) -> bool:
        import shutil

        binary = shutil.which("wkhtmltopdf")
        if not binary:
            return False
        try:
            r = subprocess.run(
                [binary, html_path, output_path],
                capture_output=True,
                timeout=120,
            )
            return r.returncode == 0
        except Exception:
            return False
