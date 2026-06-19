"""LLM-callable tools for scientific data visualization.

All plots use a dark theme matching the LLM-OS aesthetic.
Plots are saved to ~/plots/ by default and the tool returns both the file
path and a base64-encoded PNG thumbnail.
"""
from __future__ import annotations

import base64
import io
import os
import tempfile
import textwrap
import traceback
from pathlib import Path
from typing import Any

from .registry import tool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLOTS_DIR = Path("~/plots").expanduser()


def _ensure_plots_dir() -> Path:
    _PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    return _PLOTS_DIR


def _fig_to_b64(fig) -> str:
    """Encode a matplotlib Figure as a base64 PNG string (no data-URI prefix)."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=96)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _apply_dark_theme(plt, fig, axes=None) -> None:
    """Apply a consistent dark theme to a matplotlib figure."""
    BG = "#0d1117"
    SURFACE = "#161b22"
    TEXT = "#c9d1d9"
    GRID = "#30363d"
    ACCENT = "#58a6ff"

    fig.patch.set_facecolor(BG)
    ax_list = [axes] if axes is not None else fig.get_axes()
    for ax in ax_list:
        ax.set_facecolor(SURFACE)
        ax.tick_params(colors=TEXT)
        ax.xaxis.label.set_color(TEXT)
        ax.yaxis.label.set_color(TEXT)
        if hasattr(ax, "zaxis"):
            ax.zaxis.label.set_color(TEXT)
        ax.title.set_color(ACCENT)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID)
        ax.grid(True, color=GRID, linestyle="--", linewidth=0.5, alpha=0.7)


def _result(path: str, b64: str) -> str:
    return f"Plot saved: {path}\nBase64 preview (PNG): {b64}"


def _load_data(data_file: str):
    """Load a CSV or HDF5 file into a pandas DataFrame."""
    import pandas as pd  # type: ignore
    p = Path(data_file).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Data file not found: {data_file}")
    if p.suffix.lower() in (".h5", ".hdf5", ".he5"):
        return pd.read_hdf(str(p))
    return pd.read_csv(str(p))


def _require_matplotlib():
    try:
        import matplotlib  # type: ignore
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
        return plt
    except ImportError:
        raise RuntimeError(
            "matplotlib is not installed.\n"
            "Install with: pip install matplotlib"
        )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(
    name="render_plot",
    description=(
        "Execute matplotlib/plotly Python code and capture the resulting figure. "
        "Saves the plot to a file and returns the file path plus a base64 PNG thumbnail."
    ),
    properties={
        "python_code": {
            "type": "string",
            "description": (
                "Python code that produces a matplotlib figure.  "
                "Call plt.savefig(output_path) to control the output location, "
                "or leave that to the tool (it injects `output_path` into the namespace)."
            ),
        },
        "output_path": {
            "type": "string",
            "description": "Destination file path for the figure (default: ~/plots/render_<ts>.png).",
        },
    },
    required=["python_code"],
)
def render_plot(python_code: str, output_path: str | None = None) -> str:
    plt = _require_matplotlib()
    import matplotlib  # type: ignore
    matplotlib.use("Agg")

    plots_dir = _ensure_plots_dir()

    if output_path is None:
        import time
        ts = int(time.time())
        output_path = str(plots_dir / f"render_{ts}.png")
    else:
        output_path = str(Path(output_path).expanduser())

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Inject helpers into the execution namespace
    ns: dict[str, Any] = {
        "output_path": output_path,
        "__name__": "__llmos_render__",
    }

    # Wrap code to capture the figure and apply dark theme
    wrapper = textwrap.dedent(f"""\
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
{python_code}
# Apply dark theme to all current figures
for _fig in [plt.gcf()]:
    _fig.patch.set_facecolor('#0d1117')
    for _ax in _fig.get_axes():
        _ax.set_facecolor('#161b22')
        _ax.tick_params(colors='#c9d1d9')
        _ax.xaxis.label.set_color('#c9d1d9')
        _ax.yaxis.label.set_color('#c9d1d9')
        _ax.title.set_color('#58a6ff')
        for _sp in _ax.spines.values():
            _sp.set_edgecolor('#30363d')
        _ax.grid(True, color='#30363d', linestyle='--', linewidth=0.5, alpha=0.7)
if not plt.get_fignums():
    pass
else:
    plt.savefig(output_path, bbox_inches='tight', dpi=96, facecolor='#0d1117')
    plt.close('all')
""")

    try:
        exec(wrapper, ns)  # noqa: S102
    except Exception:
        return f"Error executing plot code:\n{traceback.format_exc()}"

    if not Path(output_path).exists():
        return "Plot code executed but no file was saved.  Ensure the code creates a figure."

    with open(output_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    return _result(output_path, b64)


@tool(
    name="plot_timeseries",
    description=(
        "Load a CSV or HDF5 data file and plot one or more columns as a time series.  "
        "Returns the file path and a base64 PNG thumbnail."
    ),
    properties={
        "data_file": {
            "type": "string",
            "description": "Path to a CSV or HDF5 data file.",
        },
        "x_column": {
            "type": "string",
            "description": "Column name to use as the X axis (time).",
        },
        "y_columns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Column name(s) to plot on the Y axis.",
        },
        "title": {
            "type": "string",
            "description": "Plot title (default: 'Time Series').",
        },
        "output_path": {
            "type": "string",
            "description": "Destination file path (default: ~/plots/timeseries_<ts>.png).",
        },
    },
    required=["data_file", "x_column", "y_columns"],
)
def plot_timeseries(
    data_file: str,
    x_column: str,
    y_columns: list[str],
    title: str = "Time Series",
    output_path: str | None = None,
) -> str:
    plt = _require_matplotlib()
    import matplotlib  # type: ignore
    matplotlib.use("Agg")

    try:
        df = _load_data(data_file)
    except Exception as exc:
        return f"Error loading data: {exc}"

    plots_dir = _ensure_plots_dir()
    if output_path is None:
        import time
        ts = int(time.time())
        output_path = str(plots_dir / f"timeseries_{ts}.png")
    else:
        output_path = str(Path(output_path).expanduser())

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Colour palette matching the dark theme
    COLORS = ["#58a6ff", "#3fb950", "#f78166", "#e3b341", "#bc8cff", "#39d353"]

    fig, ax = plt.subplots(figsize=(12, 5))
    for i, col in enumerate(y_columns):
        if col not in df.columns:
            continue
        ax.plot(
            df[x_column], df[col],
            label=col,
            color=COLORS[i % len(COLORS)],
            linewidth=1.5,
        )

    ax.set_xlabel(x_column)
    ax.set_ylabel(", ".join(y_columns))
    ax.set_title(title)
    ax.legend(facecolor="#161b22", edgecolor="#30363d", labelcolor="#c9d1d9")
    _apply_dark_theme(plt, fig, ax)

    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight", dpi=96, facecolor="#0d1117")
    plt.close(fig)

    b64 = _fig_to_b64(plt.figure()) if False else base64.b64encode(
        Path(output_path).read_bytes()
    ).decode()

    return _result(output_path, b64)


@tool(
    name="plot_heatmap",
    description=(
        "Load a CSV data file and display it as a 2-D heatmap.  "
        "Returns the file path and a base64 PNG thumbnail."
    ),
    properties={
        "data_file": {
            "type": "string",
            "description": "Path to a CSV file containing a 2-D numeric matrix.",
        },
        "title": {
            "type": "string",
            "description": "Plot title (default: 'Heatmap').",
        },
        "output_path": {
            "type": "string",
            "description": "Destination file path (default: ~/plots/heatmap_<ts>.png).",
        },
    },
    required=["data_file"],
)
def plot_heatmap(
    data_file: str,
    title: str = "Heatmap",
    output_path: str | None = None,
) -> str:
    plt = _require_matplotlib()
    import matplotlib  # type: ignore
    matplotlib.use("Agg")

    try:
        df = _load_data(data_file)
    except Exception as exc:
        return f"Error loading data: {exc}"

    plots_dir = _ensure_plots_dir()
    if output_path is None:
        import time
        ts = int(time.time())
        output_path = str(plots_dir / f"heatmap_{ts}.png")
    else:
        output_path = str(Path(output_path).expanduser())

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    numeric_df = df.select_dtypes(include="number")
    if numeric_df.empty:
        return "No numeric columns found in data file."

    fig, ax = plt.subplots(figsize=(10, 8))
    data = numeric_df.values

    im = ax.imshow(data, aspect="auto", cmap="viridis", interpolation="nearest")
    cbar = fig.colorbar(im, ax=ax)
    cbar.ax.yaxis.label.set_color("#c9d1d9")
    cbar.ax.tick_params(colors="#c9d1d9")

    # Label axes with column names if matrix is small enough
    if len(numeric_df.columns) <= 50:
        ax.set_xticks(range(len(numeric_df.columns)))
        ax.set_xticklabels(numeric_df.columns, rotation=45, ha="right", fontsize=8)

    ax.set_title(title)
    ax.set_xlabel("Columns")
    ax.set_ylabel("Rows")
    _apply_dark_theme(plt, fig, ax)

    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight", dpi=96, facecolor="#0d1117")
    plt.close(fig)

    b64 = base64.b64encode(Path(output_path).read_bytes()).decode()
    return _result(output_path, b64)


@tool(
    name="plot_histogram",
    description=(
        "Load a CSV data file and plot a histogram for a chosen column.  "
        "Returns the file path and a base64 PNG thumbnail."
    ),
    properties={
        "data_file": {
            "type": "string",
            "description": "Path to a CSV data file.",
        },
        "column": {
            "type": "string",
            "description": "Column name to histogram.",
        },
        "bins": {
            "type": "integer",
            "description": "Number of histogram bins (default: 30).",
        },
        "title": {
            "type": "string",
            "description": "Plot title (default: 'Histogram').",
        },
        "output_path": {
            "type": "string",
            "description": "Destination file path (default: ~/plots/histogram_<ts>.png).",
        },
    },
    required=["data_file", "column"],
)
def plot_histogram(
    data_file: str,
    column: str,
    bins: int = 30,
    title: str = "Histogram",
    output_path: str | None = None,
) -> str:
    plt = _require_matplotlib()
    import matplotlib  # type: ignore
    matplotlib.use("Agg")

    try:
        df = _load_data(data_file)
    except Exception as exc:
        return f"Error loading data: {exc}"

    if column not in df.columns:
        return f"Column '{column}' not found. Available: {', '.join(df.columns)}"

    plots_dir = _ensure_plots_dir()
    if output_path is None:
        import time
        ts = int(time.time())
        output_path = str(plots_dir / f"histogram_{ts}.png")
    else:
        output_path = str(Path(output_path).expanduser())

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(
        df[column].dropna(),
        bins=bins,
        color="#58a6ff",
        edgecolor="#30363d",
        alpha=0.85,
    )
    ax.set_title(title)
    ax.set_xlabel(column)
    ax.set_ylabel("Count")
    _apply_dark_theme(plt, fig, ax)

    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight", dpi=96, facecolor="#0d1117")
    plt.close(fig)

    b64 = base64.b64encode(Path(output_path).read_bytes()).decode()
    return _result(output_path, b64)


@tool(
    name="plot_scatter_3d",
    description=(
        "Load a CSV data file and generate a 3-D scatter plot.  "
        "Returns the file path and a base64 PNG thumbnail."
    ),
    properties={
        "data_file": {
            "type": "string",
            "description": "Path to a CSV data file.",
        },
        "x": {
            "type": "string",
            "description": "Column name for the X axis.",
        },
        "y": {
            "type": "string",
            "description": "Column name for the Y axis.",
        },
        "z": {
            "type": "string",
            "description": "Column name for the Z axis.",
        },
        "color_column": {
            "type": "string",
            "description": "Optional column name to use for point colouring.",
        },
        "title": {
            "type": "string",
            "description": "Plot title (default: '3D Scatter').",
        },
        "output_path": {
            "type": "string",
            "description": "Destination file path (default: ~/plots/scatter3d_<ts>.png).",
        },
    },
    required=["data_file", "x", "y", "z"],
)
def plot_scatter_3d(
    data_file: str,
    x: str,
    y: str,
    z: str,
    color_column: str | None = None,
    title: str = "3D Scatter",
    output_path: str | None = None,
) -> str:
    plt = _require_matplotlib()
    import matplotlib  # type: ignore
    matplotlib.use("Agg")
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 — registers 3d projection

    try:
        df = _load_data(data_file)
    except Exception as exc:
        return f"Error loading data: {exc}"

    for col in (x, y, z):
        if col not in df.columns:
            return f"Column '{col}' not found. Available: {', '.join(df.columns)}"

    plots_dir = _ensure_plots_dir()
    if output_path is None:
        import time
        ts = int(time.time())
        output_path = str(plots_dir / f"scatter3d_{ts}.png")
    else:
        output_path = str(Path(output_path).expanduser())

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection="3d")

    # Colour mapping
    if color_column and color_column in df.columns:
        import numpy as np  # type: ignore
        c_values = df[color_column].astype(float)
        c_norm = (c_values - c_values.min()) / (c_values.max() - c_values.min() + 1e-12)
        colors = plt.cm.plasma(c_norm.values)  # type: ignore[attr-defined]
        scatter = ax.scatter(
            df[x], df[y], df[z],
            c=colors,
            s=20,
            alpha=0.8,
            depthshade=True,
        )
    else:
        scatter = ax.scatter(
            df[x], df[y], df[z],
            color="#58a6ff",
            s=20,
            alpha=0.8,
            depthshade=True,
        )

    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.set_zlabel(z)  # type: ignore[attr-defined]
    ax.set_title(title)

    # Dark theme for 3D
    BG = "#0d1117"
    SURFACE = "#161b22"
    TEXT = "#c9d1d9"
    ACCENT = "#58a6ff"
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(SURFACE)
    ax.tick_params(colors=TEXT)
    ax.xaxis.label.set_color(TEXT)
    ax.yaxis.label.set_color(TEXT)
    ax.zaxis.label.set_color(TEXT)  # type: ignore[attr-defined]
    ax.title.set_color(ACCENT)
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False  # type: ignore[attr-defined]
    ax.xaxis.pane.set_edgecolor("#30363d")
    ax.yaxis.pane.set_edgecolor("#30363d")
    ax.zaxis.pane.set_edgecolor("#30363d")  # type: ignore[attr-defined]

    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight", dpi=96, facecolor=BG)
    plt.close(fig)

    b64 = base64.b64encode(Path(output_path).read_bytes()).decode()
    return _result(output_path, b64)
