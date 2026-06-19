"""FastAPI server for the LLM-OS Web UI."""

from __future__ import annotations

import asyncio
import json
import os
import platform
from pathlib import Path
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..config import Config
from ..tools import dispatch_tool, get_tool_schemas

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="LLM-OS Web UI", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_config: Config = Config()
_conversation_history: list[dict] = []


def _detect_gpu_brief() -> str:
    import subprocess
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            return "NVIDIA: " + " | ".join(l.strip() for l in r.stdout.strip().splitlines())
    except Exception:
        pass
    try:
        r = subprocess.run(["rocm-smi", "--showproductname"], capture_output=True, text=True, timeout=5)
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
            rel = dict(l.strip().split("=", 1) for l in f if "=" in l)
        os_release = rel.get("PRETTY_NAME", "").strip('"') or platform.platform()
    except Exception:
        os_release = platform.platform()

    gpu_info = _detect_gpu_brief()

    return {
        "role": "system",
        "content": _config.system_prompt.format(
            hostname=hostname, user=user, cwd=cwd,
            os_release=os_release, gpu_info=gpu_info,
        ),
    }


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
            ["nvidia-smi", "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            result["available"] = True
            result["vendor"] = "nvidia"
            for line in r.stdout.strip().splitlines():
                idx, name, gpu_pct, mem_used, mem_total, temp = [x.strip() for x in line.split(",")]
                result["gpus"].append({
                    "index": idx, "name": name,
                    "util_pct": int(gpu_pct), "mem_used": int(mem_used),
                    "mem_total": int(mem_total), "temp": int(temp),
                })
            return result
    except Exception:
        pass
    try:
        r = subprocess.run(["rocm-smi", "--showuse", "--showmemuse", "--json"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            import json as _json
            data = _json.loads(r.stdout)
            result["available"] = True
            result["vendor"] = "amd"
            for key, info in data.items():
                if key.startswith("card"):
                    result["gpus"].append({
                        "index": key,
                        "name": info.get("Card series", key),
                        "util_pct": int(info.get("GPU use (%)", 0)),
                        "mem_used": 0,
                        "mem_total": 0,
                        "temp": int(float(info.get("Temperature (Sensor edge) (°C)", 0))),
                    })
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
                        json={"model": _config.model, "messages": messages, "tools": tools, "stream": False},
                    )
                    resp.raise_for_status()
                    msg = resp.json().get("message", {})
                    tool_calls = msg.get("tool_calls")

                    if not tool_calls:
                        content = msg.get("content", "")
                        _conversation_history.append({"role": "assistant", "content": content})
                        if len(_conversation_history) > _config.max_history * 2:
                            _conversation_history[:] = _conversation_history[-_config.max_history * 2:]
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

                        await websocket.send_json({
                            "type": "tool_call",
                            "name": name,
                            "args": args,
                        })

                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(None, dispatch_tool, name, args)

                        await websocket.send_json({
                            "type": "tool_result",
                            "name": name,
                            "result": result[:500] if result else "",
                        })

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
