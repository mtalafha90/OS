from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from .registry import tool


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _nvidia_smi(*args: str, fmt: str | None = None) -> str | None:
    cmd = ["nvidia-smi"]
    if fmt:
        cmd += ["--format=csv,noheader,nounits", f"--query-gpu={fmt}"]
    cmd += list(args)
    rc, out, err = _run(cmd)
    return out if rc == 0 and out else None


def _rocm_smi(*args: str) -> str | None:
    rc, out, _ = _run(["rocm-smi"] + list(args))
    return out if rc == 0 and out else None


def _detect_vendor() -> str:
    rc, out, _ = _run(["lspci"])
    if rc != 0:
        return "unknown"
    lines = out.lower()
    if "nvidia" in lines:
        return "nvidia"
    if "amd" in lines or "radeon" in lines or "advanced micro" in lines:
        return "amd"
    if "intel" in lines and "graphics" in lines:
        return "intel"
    return "none"


@tool(
    name="get_gpu_info",
    description=(
        "Get comprehensive information about available GPUs: vendor, model, VRAM, "
        "temperature, utilization, driver version, and CUDA/ROCm version."
    ),
    properties={},
    required=[],
)
def get_gpu_info() -> str:
    sections = []
    vendor = _detect_vendor()
    sections.append(f"GPU Vendor: {vendor.upper()}")

    # ── NVIDIA ──────────────────────────────────────────────────────────────
    nvidia_out = _nvidia_smi(
        fmt=(
            "index,name,driver_version,memory.total,memory.used,memory.free,"
            "utilization.gpu,utilization.memory,temperature.gpu,power.draw,power.limit"
        )
    )
    if nvidia_out:
        headers = [
            "Index", "Name", "Driver", "VRAM Total", "VRAM Used", "VRAM Free",
            "GPU %", "Mem %", "Temp °C", "Power W", "Limit W",
        ]
        rows = []
        for line in nvidia_out.splitlines():
            fields = [f.strip() for f in line.split(",")]
            rows.append(dict(zip(headers, fields)))

        sections.append("\nNVIDIA GPUs:")
        for r in rows:
            sections.append(
                f"  GPU {r['Index']}: {r['Name']}\n"
                f"    Driver: {r['Driver']} | VRAM: {r['VRAM Used']} / {r['VRAM Total']} MB "
                f"({r['VRAM Free']} MB free)\n"
                f"    Utilization: GPU {r['GPU %']}% | Memory {r['Mem %']}%\n"
                f"    Temperature: {r['Temp °C']}°C | Power: {r['Power W']} / {r['Limit W']} W"
            )

        # CUDA version
        rc, nvcc_out, _ = _run(["nvcc", "--version"])
        if rc == 0:
            for line in nvcc_out.splitlines():
                if "release" in line.lower():
                    sections.append(f"  CUDA: {line.strip()}")
                    break
        else:
            # Try from toolkit env
            rc2, cuda_out, _ = _run(["cat", "/usr/local/cuda/version.json"])
            if rc2 == 0:
                try:
                    sections.append(f"  CUDA Toolkit: {json.loads(cuda_out).get('cuda', {}).get('version', 'unknown')}")
                except Exception:
                    pass

    # ── AMD ROCm ─────────────────────────────────────────────────────────────
    amd_out = _rocm_smi("--showallinfo", "--json")
    if amd_out:
        try:
            data = json.loads(amd_out)
            sections.append("\nAMD ROCm GPUs:")
            for gpu_id, info in data.items():
                if not gpu_id.startswith("card"):
                    continue
                sections.append(
                    f"  {gpu_id}: {info.get('Card series', 'Unknown')}\n"
                    f"    VRAM: {info.get('GPU memory use (%)', '?')}% used\n"
                    f"    GPU use: {info.get('GPU use (%)', '?')}%\n"
                    f"    Temp: {info.get('Temperature (Sensor edge) (°C)', '?')}°C"
                )
        except Exception:
            sections.append(f"\nAMD ROCm:\n{amd_out[:500]}")

        # ROCm version
        rc, rocm_ver, _ = _run(["cat", "/opt/rocm/.info/version"])
        if rc == 0:
            sections.append(f"  ROCm Version: {rocm_ver}")

    if len(sections) == 1:
        return (
            "No GPU detected via nvidia-smi or rocm-smi.\n"
            "If you passed through a GPU to this VM, ensure drivers are installed:\n"
            "  NVIDIA: sudo apt install nvidia-driver-565-open cuda-toolkit-12-6\n"
            "  AMD:    sudo amdgpu-install --usecase=rocm"
        )

    return "\n".join(sections)


@tool(
    name="monitor_gpu",
    description="Monitor GPU utilization, memory, and temperature in real time.",
    properties={
        "duration": {"type": "integer", "description": "How many seconds to monitor (default: 10)"},
        "interval": {"type": "integer", "description": "Sampling interval in seconds (default: 2)"},
    },
    required=[],
)
def monitor_gpu(duration: int = 10, interval: int = 2) -> str:
    import time
    samples = []
    end = time.time() + min(duration, 120)

    while time.time() < end:
        ts = time.strftime("%H:%M:%S")
        line_parts = [f"[{ts}]"]

        nv = _nvidia_smi(fmt="index,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw")
        if nv:
            for row in nv.splitlines():
                idx, gpu_pct, mem_used, mem_total, temp, pwr = [x.strip() for x in row.split(",")]
                line_parts.append(
                    f"GPU{idx} util={gpu_pct}% mem={mem_used}/{mem_total}MB "
                    f"temp={temp}°C pwr={pwr}W"
                )

        amd = _rocm_smi("--showuse", "--showtemp", "--showmemuse")
        if amd:
            line_parts.append(amd.replace("\n", " | "))

        if len(line_parts) > 1:
            samples.append(" | ".join(line_parts))
        else:
            samples.append(f"{ts} — no GPU data")

        time.sleep(max(1, interval))

    return "\n".join(samples) if samples else "No GPU monitoring data collected."


@tool(
    name="list_gpu_processes",
    description="List processes currently using the GPU and their VRAM consumption.",
    properties={},
    required=[],
)
def list_gpu_processes() -> str:
    out = _nvidia_smi("--query-compute-apps=pid,used_memory,name", "--format=csv,noheader")
    if out:
        lines = ["PID      VRAM(MB)  Process"]
        lines.append("-" * 50)
        for row in out.splitlines():
            parts = [p.strip() for p in row.split(",")]
            if len(parts) >= 3:
                lines.append(f"{parts[0]:<8} {parts[1]:<9} {parts[2]}")
        return "\n".join(lines)

    amd = _rocm_smi("--showpidgpus", "--json")
    if amd:
        return amd

    return "No GPU processes found (or no GPU detected)."


@tool(
    name="set_gpu_power_limit",
    description="Set the GPU power limit (TDP) in watts. Useful for thermal management in simulations.",
    properties={
        "gpu_id": {"type": "integer", "description": "GPU index (0, 1, …)"},
        "watts": {"type": "integer", "description": "Power limit in watts"},
    },
    required=["gpu_id", "watts"],
)
def set_gpu_power_limit(gpu_id: int, watts: int) -> str:
    rc, out, err = _run(["nvidia-smi", "-i", str(gpu_id), "-pl", str(watts)])
    if rc == 0:
        return f"GPU {gpu_id} power limit set to {watts}W.\n{out}"
    return f"Error: {err or 'nvidia-smi not available or permission denied (try sudo)'}"


@tool(
    name="get_cuda_info",
    description="Show CUDA toolkit version, GPU compute capabilities, and available cuDNN/NCCL versions.",
    properties={},
    required=[],
)
def get_cuda_info() -> str:
    lines = []

    rc, nvcc, _ = _run(["nvcc", "--version"])
    if rc == 0:
        lines.append("CUDA Toolkit (nvcc):")
        lines += [f"  {l}" for l in nvcc.splitlines() if l.strip()]
    else:
        # Check pre-installed toolkit
        rc2, ver, _ = _run(["bash", "-c", "cat /usr/local/cuda/version.json 2>/dev/null || echo ''"])
        if rc2 == 0 and ver:
            try:
                lines.append(f"CUDA Toolkit: {json.loads(ver)}")
            except Exception:
                pass

    # Compute capability via Python
    py_code = """
import subprocess
try:
    import torch
    for i in range(torch.cuda.device_count()):
        p = torch.cuda.get_device_properties(i)
        print(f"GPU {i}: {p.name} | Compute {p.major}.{p.minor} | VRAM {p.total_memory//1024**2}MB")
except Exception as e:
    print(f"PyTorch not available or no GPU: {e}")
"""
    rc3, py_out, _ = _run(["python3", "-c", py_code], timeout=30)
    if rc3 == 0 and py_out:
        lines.append("\nPyTorch CUDA devices:")
        lines += [f"  {l}" for l in py_out.splitlines()]

    # cuDNN
    rc4, cudnn, _ = _run(["bash", "-c", (
        "python3 -c 'import torch; print(torch.backends.cudnn.version())' 2>/dev/null || "
        "find /usr -name 'cudnn_version.h' 2>/dev/null | head -1 | xargs grep -h CUDNN_MAJOR"
    )])
    if rc4 == 0 and cudnn:
        lines.append(f"\ncuDNN: {cudnn}")

    return "\n".join(lines) if lines else "CUDA not found. Install with: sudo apt install cuda-toolkit-12-6"


@tool(
    name="reset_gpu",
    description="Reset a GPU (useful if a simulation crashed and left the GPU in a bad state).",
    properties={
        "gpu_id": {"type": "integer", "description": "GPU index to reset (default: 0)"},
    },
    required=[],
)
def reset_gpu(gpu_id: int = 0) -> str:
    rc, out, err = _run(["nvidia-smi", "--gpu-reset", "-i", str(gpu_id)])
    if rc == 0:
        return f"GPU {gpu_id} reset successfully.\n{out}"
    return f"Error: {err or 'nvidia-smi --gpu-reset failed (requires no processes on GPU)'}"
