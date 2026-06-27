"""FastAPI server for the LLM-OS Web UI."""

from __future__ import annotations

import asyncio
import json
import os
import platform
from pathlib import Path

import httpx
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..config import Config
from ..tools import dispatch_tool, get_tool_schemas

STATIC_DIR = Path(__file__).parent / "static"
PLOTS_DIR = Path.home() / "plots"

app = FastAPI(title="LLM-OS Web UI", docs_url=None, redoc_url=None)
# Guard the mount: StaticFiles(directory=...) raises at import if the dir is
# missing, which would crash the whole server before it can bind. The package
# now ships static/ (see pyproject package-data), but stay defensive.
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_config: Config = Config()
_conversation_history: list[dict] = []


# ---------------------------------------------------------------------------
# Lazy optional-dependency helpers
# ---------------------------------------------------------------------------


def _get_job_queue():
    """Return a JobQueue instance, or None if the module is unavailable."""
    try:
        from ..jobs import JobQueue  # type: ignore

        return JobQueue.instance()
    except Exception:
        return None


def _get_simulation_tracker():
    """Return a SimulationTracker instance, or None if unavailable."""
    try:
        from ..simulation import SimulationTracker  # type: ignore

        return SimulationTracker.instance()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_gpu_brief() -> str:
    import subprocess

    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return "NVIDIA: " + " | ".join(ln.strip() for ln in r.stdout.strip().splitlines())
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["rocm-smi", "--showproductname"], capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            return "AMD ROCm: " + r.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return "No GPU detected"


def _system_message() -> dict:
    try:
        hostname = os.uname().nodename
    except AttributeError:
        hostname = "llmos"
    user = os.environ.get("USER", "user")
    cwd = os.getcwd()
    try:
        with open("/etc/os-release") as f:
            rel = dict(ln.strip().split("=", 1) for ln in f if "=" in ln)
        os_release = rel.get("PRETTY_NAME", "").strip('"') or platform.platform()
    except Exception:
        os_release = platform.platform()

    gpu_info = _detect_gpu_brief()

    return {
        "role": "system",
        "content": _config.system_prompt.format(
            hostname=hostname,
            user=user,
            cwd=cwd,
            os_release=os_release,
            gpu_info=gpu_info,
        ),
    }


# ---------------------------------------------------------------------------
# Existing routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/gpu")
async def gpu_status() -> dict:
    """Return GPU utilization for the top-bar widget."""
    import subprocess

    result: dict = {"available": False, "vendor": "none", "gpus": []}
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            result["available"] = True
            result["vendor"] = "nvidia"
            for line in r.stdout.strip().splitlines():
                idx, name, gpu_pct, mem_used, mem_total, temp = [x.strip() for x in line.split(",")]
                result["gpus"].append(
                    {
                        "index": idx,
                        "name": name,
                        "util_pct": int(gpu_pct),
                        "mem_used": int(mem_used),
                        "mem_total": int(mem_total),
                        "temp": int(temp),
                    }
                )
            return result
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["rocm-smi", "--showuse", "--showmemuse", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            import json as _json

            data = _json.loads(r.stdout)
            result["available"] = True
            result["vendor"] = "amd"
            for key, info in data.items():
                if key.startswith("card"):
                    result["gpus"].append(
                        {
                            "index": key,
                            "name": info.get("Card series", key),
                            "util_pct": int(info.get("GPU use (%)", 0)),
                            "mem_used": 0,
                            "mem_total": 0,
                            "temp": int(float(info.get("Temperature (Sensor edge) (°C)", 0))),
                        }
                    )
    except Exception:
        pass
    return result


@app.get("/api/status")
async def status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_config.ollama_url}/api/tags")
            models = [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        models = []
    return {
        "ollama_url": _config.ollama_url,
        "model": _config.model,
        "models": models,
        "hostname": os.uname().nodename if hasattr(os, "uname") else "llmos",
        "user": os.environ.get("USER", "user"),
    }


@app.post("/api/clear")
async def clear_history() -> dict:
    _conversation_history.clear()
    return {"status": "cleared"}


# ---------------------------------------------------------------------------
# New endpoints
# ---------------------------------------------------------------------------


@app.get("/api/metrics")
async def get_metrics() -> dict:
    """Return real-time CPU, RAM, Disk, and GPU metrics using psutil."""
    result: dict = {
        "cpu_pct": None,
        "ram_pct": None,
        "ram_used_gb": None,
        "ram_total_gb": None,
        "disk_pct": None,
        "gpu": [],
    }

    try:
        import psutil  # type: ignore

        result["cpu_pct"] = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        result["ram_pct"] = vm.percent
        result["ram_used_gb"] = round(vm.used / (1024**3), 2)
        result["ram_total_gb"] = round(vm.total / (1024**3), 2)
        disk = psutil.disk_usage("/")
        result["disk_pct"] = disk.percent
    except Exception:
        pass

    # GPU metrics (reuse existing logic but lightweight)
    try:
        import subprocess

        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                parts = [x.strip() for x in line.split(",")]
                if len(parts) >= 4:
                    result["gpu"].append(
                        {
                            "util": int(parts[0]),
                            "mem_pct": round(int(parts[1]) / max(int(parts[2]), 1) * 100, 1),
                            "temp": int(parts[3]),
                        }
                    )
    except Exception:
        pass

    return result


@app.get("/api/jobs")
async def list_jobs() -> list:
    """Return jobs from JobQueue. Gracefully returns empty list if unavailable."""
    try:
        jq = _get_job_queue()
        if jq is None:
            return []
        jobs = jq.list_jobs() if hasattr(jq, "list_jobs") else []
        return jobs if isinstance(jobs, list) else list(jobs)
    except Exception:
        return []


@app.post("/api/jobs/submit")
async def submit_job(body: dict) -> dict:
    """Submit a new job to the JobQueue."""
    try:
        jq = _get_job_queue()
        if jq is None:
            return {"status": "error", "message": "JobQueue not available"}
        job_id = jq.submit(
            name=body.get("name", "unnamed"),
            command=body.get("command", ""),
            workdir=body.get("workdir", ""),
            gpu_ids=body.get("gpu_ids", ""),
            mpi_ranks=int(body.get("mpi_ranks", 1)),
            priority=int(body.get("priority", 5)),
        )
        return {"status": "ok", "job_id": job_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.delete("/api/jobs/{job_id}")
async def cancel_job(job_id: str) -> dict:
    """Cancel a pending or running job."""
    try:
        jq = _get_job_queue()
        if jq is None:
            return {"status": "error", "message": "JobQueue not available"}
        jq.cancel(job_id)
        return {"status": "ok", "job_id": job_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/simulations")
async def list_simulations() -> list:
    """Return past simulation runs from SimulationTracker."""
    try:
        tracker = _get_simulation_tracker()
        if tracker is None:
            return []
        sims = tracker.list() if hasattr(tracker, "list") else []
        return sims if isinstance(sims, list) else list(sims)
    except Exception:
        return []


@app.get("/api/plots")
async def list_plots() -> list:
    """Return metadata for PNG files in ~/plots/."""
    try:
        if not PLOTS_DIR.is_dir():
            return []
        plots = []
        for f in sorted(PLOTS_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True):
            plots.append(
                {
                    "name": f.name,
                    "path": str(f),
                    "url": f"/api/plots/image/{f.name}",
                    "mtime": f.stat().st_mtime,
                }
            )
        return plots
    except Exception:
        return []


@app.get("/api/plots/image/{filename}")
async def serve_plot(filename: str) -> FileResponse:
    """Serve a PNG plot file from ~/plots/."""
    # Sanitize: only allow simple filenames, no path traversal
    safe_name = Path(filename).name
    plot_path = PLOTS_DIR / safe_name
    if not plot_path.is_file():
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Plot not found")
    return FileResponse(str(plot_path), media_type="image/png")


@app.post("/api/voice/transcribe")
async def voice_transcribe(file: UploadFile = File(...)) -> dict:
    """Accept an audio upload and transcribe it with Whisper if available."""
    import tempfile

    audio_bytes = await file.read()
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"

    try:
        import whisper  # type: ignore

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            loop = asyncio.get_event_loop()
            model = await loop.run_in_executor(None, lambda: whisper.load_model("base"))
            result = await loop.run_in_executor(None, lambda: model.transcribe(tmp_path))
            text = result.get("text", "").strip()
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        return {"text": text}

    except ImportError:
        # Whisper not installed — return a friendly message
        return {
            "text": "",
            "error": "Whisper not installed. Install with: pip install openai-whisper",
        }
    except Exception as e:
        return {"text": "", "error": str(e)}


# ---------------------------------------------------------------------------
# WebSocket chat
# ---------------------------------------------------------------------------


@app.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    tools = get_tool_schemas()

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            action = data.get("action", "chat")

            if action == "clear":
                _conversation_history.clear()
                await websocket.send_json({"type": "cleared"})
                continue

            if action == "switch_model":
                _config.model = data.get("model", _config.model)
                await websocket.send_json({"type": "model_switched", "model": _config.model})
                continue

            user_content = data.get("message", "")
            if not user_content:
                continue

            _conversation_history.append({"role": "user", "content": user_content})
            messages = [_system_message()] + _conversation_history

            await websocket.send_json({"type": "thinking"})

            async with httpx.AsyncClient(timeout=_config.request_timeout) as client:
                while True:
                    resp = await client.post(
                        f"{_config.ollama_url}/api/chat",
                        json={
                            "model": _config.model,
                            "messages": messages,
                            "tools": tools,
                            "stream": False,
                        },
                    )
                    resp.raise_for_status()
                    msg = resp.json().get("message", {})
                    tool_calls = msg.get("tool_calls")

                    if not tool_calls:
                        content = msg.get("content", "")
                        _conversation_history.append({"role": "assistant", "content": content})
                        if len(_conversation_history) > _config.max_history * 2:
                            _conversation_history[:] = _conversation_history[
                                -_config.max_history * 2 :
                            ]
                        await websocket.send_json({"type": "response", "content": content})
                        break

                    messages.append(msg)
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        name = fn.get("name", "")
                        args = fn.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {}

                        await websocket.send_json(
                            {
                                "type": "tool_call",
                                "name": name,
                                "args": args,
                            }
                        )

                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(None, dispatch_tool, name, args)

                        await websocket.send_json(
                            {
                                "type": "tool_result",
                                "name": name,
                                "result": result[:500] if result else "",
                            }
                        )

                        messages.append({"role": "tool", "content": result})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


def run(host: str = "0.0.0.0", port: int = 8080, config: Config | None = None) -> None:
    global _config
    if config:
        _config = config
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning")
