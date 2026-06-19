from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
from pathlib import Path

from .registry import tool


def _run(cmd: list[str], timeout: int = 60, cwd: str | None = None, env: dict | None = None) -> str:
    try:
        merged_env = {**os.environ, **(env or {})}
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=cwd, env=merged_env
        )
        out = r.stdout.strip()
        err = r.stderr.strip()
        parts = [p for p in [out, err] if p]
        if r.returncode != 0:
            parts.append(f"[exit {r.returncode}]")
        return "\n".join(parts) if parts else "(no output)"
    except FileNotFoundError as e:
        return f"Error: command not found — {e}"
    except subprocess.TimeoutExpired:
        return f"Error: timed out after {timeout}s"


@tool(
    name="run_python_code",
    description=(
        "Execute Python code for scientific computation. "
        "Automatically uses GPU if CUDA/ROCm is available. "
        "Supports NumPy, SciPy, PyTorch, CuPy, Pandas, Matplotlib, and all installed packages."
    ),
    properties={
        "code": {"type": "string", "description": "Python code to execute"},
        "timeout": {"type": "integer", "description": "Maximum execution time in seconds (default: 120)"},
        "conda_env": {"type": "string", "description": "Conda environment to use (default: base)"},
        "save_output": {"type": "string", "description": "Save output to this file path (optional)"},
    },
    required=["code"],
)
def run_python_code(
    code: str,
    timeout: int = 120,
    conda_env: str | None = None,
    save_output: str | None = None,
) -> str:
    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, prefix="/tmp/llmos_"
    ) as f:
        f.write(code)
        script_path = f.name

    try:
        if conda_env:
            cmd = ["conda", "run", "-n", conda_env, "--no-capture-output", "python3", script_path]
        else:
            cmd = ["python3", script_path]

        result = _run(cmd, timeout=timeout)

        if save_output:
            Path(save_output).write_text(result)
            result += f"\n\n[Output saved to {save_output}]"

        return result
    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass


@tool(
    name="launch_jupyter",
    description="Start a JupyterLab server for interactive scientific computing with GPU support.",
    properties={
        "port": {"type": "integer", "description": "Port to listen on (default: 8888)"},
        "directory": {"type": "string", "description": "Working directory (default: /home/llmos)"},
        "no_browser": {"type": "boolean", "description": "Do not open browser automatically (default: true)"},
    },
    required=[],
)
def launch_jupyter(port: int = 8888, directory: str = "/home/llmos", no_browser: bool = True) -> str:
    import shutil
    if not shutil.which("jupyter"):
        return (
            "JupyterLab not installed. Install with:\n"
            "  pip install jupyterlab\n"
            "  or: conda install -c conda-forge jupyterlab"
        )

    # Check if already running
    check = subprocess.run(
        ["pgrep", "-f", f"jupyter.*{port}"], capture_output=True, text=True
    )
    if check.returncode == 0:
        return (
            f"JupyterLab already running on port {port}.\n"
            f"Open: http://localhost:{port}"
        )

    cmd = [
        "jupyter", "lab",
        f"--port={port}",
        f"--notebook-dir={directory}",
        "--ip=0.0.0.0",
        "--no-browser",
        "--NotebookApp.token=''",
        "--NotebookApp.password=''",
    ]

    subprocess.Popen(
        cmd,
        cwd=directory,
        stdout=open(f"/tmp/jupyter-{port}.log", "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    import time
    time.sleep(2)

    return (
        f"JupyterLab started on port {port}.\n"
        f"Access at: http://<vm-ip>:{port}\n"
        f"Log file: /tmp/jupyter-{port}.log\n"
        f"Stop with: pkill -f 'jupyter.*{port}'"
    )


@tool(
    name="get_scientific_stack",
    description="List all installed scientific computing software, versions, and GPU support status.",
    properties={},
    required=[],
)
def get_scientific_stack() -> str:
    checks = [
        ("python3", ["python3", "--version"]),
        ("numpy",   ["python3", "-c", "import numpy; print(numpy.__version__)"]),
        ("scipy",   ["python3", "-c", "import scipy; print(scipy.__version__)"]),
        ("pandas",  ["python3", "-c", "import pandas; print(pandas.__version__)"]),
        ("torch",   ["python3", "-c", "import torch; print(torch.__version__, '| CUDA:', torch.cuda.is_available(), '| Devices:', torch.cuda.device_count())"]),
        ("cupy",    ["python3", "-c", "import cupy; print(cupy.__version__, '|', cupy.cuda.runtime.runtimeGetVersion())"]),
        ("jax",     ["python3", "-c", "import jax; print(jax.__version__, '| devices:', jax.devices())"]),
        ("sklearn", ["python3", "-c", "import sklearn; print(sklearn.__version__)"]),
        ("matplotlib", ["python3", "-c", "import matplotlib; print(matplotlib.__version__)"]),
        ("jupyter", ["jupyter", "--version"]),
        ("mpi4py",  ["python3", "-c", "import mpi4py; print(mpi4py.__version__)"]),
        ("dask",    ["python3", "-c", "import dask; print(dask.__version__)"]),
        ("h5py",    ["python3", "-c", "import h5py; print(h5py.__version__)"]),
        ("netcdf4", ["python3", "-c", "import netCDF4; print(netCDF4.__version__)"]),
        ("numba",   ["python3", "-c", "import numba; print(numba.__version__)"]),
        ("GROMACS", ["gmx", "--version"]),
        ("OpenFOAM",["foamVersion"]),
        ("LAMMPS",  ["lmp", "-h"]),
        ("OpenMPI", ["mpirun", "--version"]),
        ("CUDA",    ["nvcc", "--version"]),
        ("ROCm",    ["rocminfo"]),
    ]

    lines = [f"{'Package':<15} {'Status':<10} {'Info'}"]
    lines.append("-" * 70)

    for name, cmd in checks:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                info = (r.stdout + r.stderr).strip().splitlines()[0][:50]
                lines.append(f"{name:<15} {'✓ OK':<10} {info}")
            else:
                lines.append(f"{name:<15} {'✗ missing':<10}")
        except Exception:
            lines.append(f"{name:<15} {'✗ missing':<10}")

    return "\n".join(lines)


@tool(
    name="run_simulation",
    description=(
        "Run a scientific simulation command (GROMACS, LAMMPS, OpenFOAM, custom) "
        "with optional MPI parallelism and GPU binding."
    ),
    properties={
        "command": {"type": "string", "description": "Simulation command (e.g. 'gmx mdrun -v -deffnm md' or 'lmp -in in.lj')"},
        "workdir": {"type": "string", "description": "Working directory containing input files"},
        "mpi_ranks": {"type": "integer", "description": "Number of MPI ranks (default: 1)"},
        "gpu_ids": {"type": "string", "description": "GPU IDs to use, e.g. '0' or '0,1' (default: all available)"},
        "timeout": {"type": "integer", "description": "Maximum runtime in seconds (default: 3600)"},
    },
    required=["command"],
)
def run_simulation(
    command: str,
    workdir: str = ".",
    mpi_ranks: int = 1,
    gpu_ids: str | None = None,
    timeout: int = 3600,
) -> str:
    env: dict[str, str] = {}
    if gpu_ids is not None:
        env["CUDA_VISIBLE_DEVICES"] = gpu_ids
        env["HIP_VISIBLE_DEVICES"] = gpu_ids

    if mpi_ranks > 1:
        cmd = ["mpirun", "-n", str(mpi_ranks)] + command.split()
    else:
        cmd = command.split()

    workdir_path = Path(workdir).expanduser()
    if not workdir_path.exists():
        return f"Error: working directory '{workdir}' not found"

    return _run(cmd, timeout=timeout, cwd=str(workdir_path), env=env)


@tool(
    name="create_conda_env",
    description="Create a new conda environment with scientific packages.",
    properties={
        "name": {"type": "string", "description": "Environment name"},
        "python_version": {"type": "string", "description": "Python version (e.g. '3.11')"},
        "packages": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Conda or pip packages to install",
        },
        "channels": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Conda channels (default: ['conda-forge'])",
        },
    },
    required=["name"],
)
def create_conda_env(
    name: str,
    python_version: str = "3.11",
    packages: list[str] | None = None,
    channels: list[str] | None = None,
) -> str:
    import shutil
    if not shutil.which("conda") and not shutil.which("mamba"):
        return (
            "Conda not found. Install Miniforge:\n"
            "  curl -fsSL https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh | bash"
        )

    conda = "mamba" if shutil.which("mamba") else "conda"
    channels_flags: list[str] = []
    for ch in (channels or ["conda-forge"]):
        channels_flags += ["-c", ch]

    cmd = [conda, "create", "-n", name, f"python={python_version}", "-y"] + channels_flags
    if packages:
        cmd += packages

    return _run(cmd, timeout=600)


@tool(
    name="list_conda_envs",
    description="List all available conda environments.",
    properties={},
    required=[],
)
def list_conda_envs() -> str:
    return _run(["conda", "env", "list"])


@tool(
    name="run_benchmark",
    description="Run a GPU or CPU benchmark to verify hardware performance.",
    properties={
        "target": {"type": "string", "description": "Benchmark target: 'gpu', 'cpu', or 'memory' (default: gpu)"},
        "duration": {"type": "integer", "description": "Benchmark duration in seconds (default: 10)"},
    },
    required=[],
)
def run_benchmark(target: str = "gpu", duration: int = 10) -> str:
    benchmarks = {
        "gpu": textwrap.dedent(f"""
import time
import sys

try:
    import torch
    if not torch.cuda.is_available():
        print("No CUDA GPU available. Falling back to CPU benchmark.")
        target = 'cpu'
    else:
        device = 'cuda'
        n = 8192
        print(f"GPU: {{torch.cuda.get_device_name(0)}}")
        a = torch.randn(n, n, device=device)
        b = torch.randn(n, n, device=device)
        torch.cuda.synchronize()
        t0 = time.time()
        iterations = 0
        while time.time() - t0 < {duration}:
            c = torch.mm(a, b)
            torch.cuda.synchronize()
            iterations += 1
        elapsed = time.time() - t0
        tflops = (2 * n**3 * iterations) / elapsed / 1e12
        print(f"Matrix multiply {{n}}x{{n}}: {{iterations}} iterations in {{elapsed:.1f}}s")
        print(f"Throughput: {{tflops:.2f}} TFLOPS")
        sys.exit(0)
except ImportError:
    pass

try:
    import cupy as cp
    a = cp.random.randn(4096, 4096)
    b = cp.random.randn(4096, 4096)
    cp.cuda.Stream.null.synchronize()
    t0 = time.time()
    iters = 0
    while time.time() - t0 < {duration}:
        c = cp.dot(a, b)
        cp.cuda.Stream.null.synchronize()
        iters += 1
    print(f"CuPy matmul 4096x4096: {{iters}} iters / {{time.time()-t0:.1f}}s")
except Exception as e:
    print(f"GPU benchmark failed: {{e}}")
"""),
        "cpu": textwrap.dedent(f"""
import time
import numpy as np
n = 4096
a = np.random.randn(n, n).astype(np.float32)
b = np.random.randn(n, n).astype(np.float32)
t0 = time.time()
iters = 0
while time.time() - t0 < {duration}:
    c = np.dot(a, b)
    iters += 1
elapsed = time.time() - t0
gflops = (2 * n**3 * iters) / elapsed / 1e9
print(f"CPU NumPy matmul {{n}}x{{n}}: {{iters}} iters in {{elapsed:.1f}}s")
print(f"Throughput: {{gflops:.1f}} GFLOPS")
"""),
        "memory": textwrap.dedent(f"""
import time, subprocess
try:
    import torch
    if torch.cuda.is_available():
        size = 1024**3  # 1 GB
        a = torch.zeros(size // 4, dtype=torch.float32, device='cuda')
        b = torch.zeros(size // 4, dtype=torch.float32, device='cuda')
        torch.cuda.synchronize()
        t0 = time.time()
        iters = 0
        while time.time() - t0 < {duration}:
            b.copy_(a)
            torch.cuda.synchronize()
            iters += 1
        bw = (size * iters) / (time.time() - t0) / 1e9
        print(f"GPU memory bandwidth: {{bw:.1f}} GB/s")
except Exception as e:
    print(f"Memory benchmark failed: {{e}}")
"""),
    }

    code = benchmarks.get(target, benchmarks["gpu"])
    return run_python_code(code, timeout=duration + 30)


@tool(
    name="install_hpc_software",
    description="Install scientific/HPC software packages (GROMACS, LAMMPS, OpenFOAM, Miniforge, etc.).",
    properties={
        "software": {
            "type": "string",
            "description": "Software to install: gromacs | lammps | openfoam | miniforge | rapids | pytorch-cuda | jax-cuda",
        },
    },
    required=["software"],
)
def install_hpc_software(software: str) -> str:
    installers: dict[str, list[str]] = {
        "gromacs": [
            "bash", "-c",
            "apt-get install -y gromacs gromacs-cuda 2>/dev/null || "
            "apt-get install -y gromacs && echo 'Installed CPU-only GROMACS (no CUDA package found)'"
        ],
        "lammps": ["apt-get", "install", "-y", "lammps"],
        "openfoam": [
            "bash", "-c",
            "curl -s https://dl.openfoam.com/add-debian-repo.sh | bash && "
            "apt-get install -y openfoam2312-default"
        ],
        "miniforge": [
            "bash", "-c",
            "curl -fsSL https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh "
            "-o /tmp/miniforge.sh && bash /tmp/miniforge.sh -b -p /opt/conda && "
            "ln -sf /opt/conda/bin/conda /usr/local/bin/conda && "
            "ln -sf /opt/conda/bin/mamba /usr/local/bin/mamba && "
            "echo 'Miniforge installed at /opt/conda'"
        ],
        "rapids": [
            "bash", "-c",
            "pip install --upgrade 'cudf-cu12' 'cuml-cu12' 'cugraph-cu12' "
            "--extra-index-url=https://pypi.nvidia.com"
        ],
        "pytorch-cuda": [
            "bash", "-c",
            "pip install torch torchvision torchaudio "
            "--index-url https://download.pytorch.org/whl/cu124"
        ],
        "jax-cuda": [
            "bash", "-c",
            "pip install 'jax[cuda12]' -f https://storage.googleapis.com/jax-releases/jax_cuda_releases.html"
        ],
    }

    installer = installers.get(software.lower())
    if not installer:
        return (
            f"Unknown software '{software}'.\n"
            f"Available: {', '.join(installers.keys())}"
        )

    import shlex
    return _run(installer, timeout=600)
