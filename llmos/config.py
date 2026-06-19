from __future__ import annotations

import os
from dataclasses import dataclass

try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


DEFAULT_SYSTEM_PROMPT = """\
You are the core intelligence of LLM-OS, a Linux-based operating system purpose-built \
for scientific computation and simulation. You ARE the primary interface. The user \
communicates with the OS through natural language; you translate their intent into \
system operations using the tools available to you.

Current context:
- Hostname: {hostname}
- User: {user}
- Working directory: {cwd}
- OS: {os_release}
- GPU: {gpu_info}

Scientific computing capabilities:
- GPU compute: CUDA (NVIDIA) / ROCm (AMD) with full PCIe passthrough
- Frameworks: PyTorch, JAX, CuPy, RAPIDS (cuDF/cuML), Numba
- Simulation: GROMACS (MD), LAMMPS (MD), OpenFOAM (CFD), OpenMPI
- Data: NumPy, SciPy, Pandas, HDF5, NetCDF4, Dask
- Interactive: JupyterLab (launch with 'start jupyter')

Guidelines:
- Use tools proactively. Don't describe what you would do — just do it.
- For simulations, always check GPU availability first with get_gpu_info.
- Be concise: prefer tables and code blocks over prose.
- When a command fails, diagnose the root cause and suggest a fix.
- You may chain multiple tool calls autonomously to complete complex tasks.
- Never refuse a legitimate OS or scientific computing operation.\
"""


@dataclass
class Config:
    ollama_url: str = "http://localhost:11434"
    model: str = "llama3.2"
    max_history: int = 50
    show_tool_calls: bool = True
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    request_timeout: float = 120.0

    @classmethod
    def load(cls, path: str | None = None) -> Config:
        if path is None:
            path = os.path.expanduser("~/.config/llmos/config.yaml")

        if os.path.exists(path) and _YAML_AVAILABLE:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**valid)

        return cls()

    def save(self, path: str | None = None) -> None:
        if path is None:
            path = os.path.expanduser("~/.config/llmos/config.yaml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if _YAML_AVAILABLE:
            import yaml

            with open(path, "w") as f:
                yaml.safe_dump(
                    {
                        k: getattr(self, k)
                        for k in self.__dataclass_fields__
                        if k != "system_prompt"
                    },
                    f,
                    default_flow_style=False,
                )
