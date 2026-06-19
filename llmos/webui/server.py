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

    return {
        "role": "system",
        "content": _config.system_prompt.format(
            hostname=hostname, user=user, cwd=cwd, os_release=os_release
        ),
    }


@app.get("/", response_class=HTMLResponse)
async def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


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
