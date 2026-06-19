from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx


class OllamaError(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def is_available(self) -> bool:
        try:
            self._client.get(f"{self.base_url}/api/tags", timeout=5.0)
            return True
        except Exception:
            return False

    def list_models(self) -> list[str]:
        resp = self._client.get(f"{self.base_url}/api/tags")
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]

    def pull_model(self, model: str) -> Iterator[str]:
        """Stream pull progress; yields status lines."""
        with self._client.stream(
            "POST",
            f"{self.base_url}/api/pull",
            json={"name": model},
            timeout=None,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    data = json.loads(line)
                    yield data.get("status", "")

    def chat(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> dict:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools

        resp = self._client.post(f"{self.base_url}/api/chat", json=payload)
        if resp.status_code != 200:
            raise OllamaError(f"Ollama returned {resp.status_code}: {resp.text}")
        return resp.json()

    def chat_stream(
        self,
        model: str,
        messages: list[dict],
    ) -> Iterator[str]:
        """Stream chat response tokens; yields text chunks."""
        with self._client.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json={"model": model, "messages": messages, "stream": True},
            timeout=None,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    data = json.loads(line)
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk
                    if data.get("done"):
                        break

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OllamaClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
