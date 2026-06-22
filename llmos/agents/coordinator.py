"""Multi-agent orchestration: Agent base class and AgentCoordinator."""

from __future__ import annotations

import json
import threading
from typing import Any


# ---------------------------------------------------------------------------
# Base Agent
# ---------------------------------------------------------------------------

class Agent:
    """LLM agent that interacts with Ollama using a role-specific system prompt."""

    def __init__(self, name: str, role_description: str, config: Any, ollama_client: Any) -> None:
        self.name = name
        self.role_description = role_description
        self.config = config
        self.ollama = ollama_client

    def _system_message(self) -> dict:
        return {
            "role": "system",
            "content": (
                f"You are {self.name}, a specialised AI agent within LLM-OS.\n\n"
                f"Your role: {self.role_description}\n\n"
                "Respond concisely and precisely. Produce actionable results only."
            ),
        }

    def _build_user_message(self, task: str, context: str | None) -> str:
        return f"Context:\n{context}\n\nTask:\n{task}" if context else task

    def run(self, task: str, context: str | None = None) -> str:
        messages = [
            self._system_message(),
            {"role": "user", "content": self._build_user_message(task, context)},
        ]
        resp = self.ollama.chat(model=self.config.model, messages=messages)
        return resp.get("message", {}).get("content", "")

    def run_with_tools(
        self,
        task: str,
        context: str | None = None,
        tools: list[dict] | None = None,
    ) -> tuple[str, list[dict]]:
        """Run with tool-calling; returns (final_text, list_of_tool_call_dicts)."""
        messages = [
            self._system_message(),
            {"role": "user", "content": self._build_user_message(task, context)},
        ]
        tool_calls_made: list[dict] = []

        while True:
            resp = self.ollama.chat(model=self.config.model, messages=messages, tools=tools or [])
            message = resp.get("message", {})
            tool_calls = message.get("tool_calls")

            if not tool_calls:
                return message.get("content", ""), tool_calls_made

            messages.append(message)
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                try:
                    from llmos.tools.registry import dispatch_tool
                    result = dispatch_tool(name, args)
                except Exception as exc:
                    result = f"Error executing {name}: {exc}"
                tool_calls_made.append({"name": name, "arguments": args, "result": result})
                messages.append({"role": "tool", "content": result})


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

_ROLE_DESCRIPTIONS: dict[str, str] = {
    "gpu_monitor": (
        "You monitor GPU utilisation during computations. Report GPU utilisation %, "
        "memory usage, temperature, and power draw. Flag anomalies such as thermal "
        "throttling or out-of-memory conditions."
    ),
    "analyzer": (
        "You analyse simulation results and numerical data. Identify patterns, anomalies, "
        "and statistical insights. Produce a clear, structured summary with key findings "
        "and recommendations."
    ),
    "planner": (
        "You decompose complex scientific or engineering tasks into concrete, ordered steps. "
        "Each step must be specific and actionable. Consider dependencies, resource "
        "requirements, and potential failure modes."
    ),
    "coder": (
        "You write correct, efficient Python code for scientific simulations and data "
        "processing. Validate your code logic before returning it. Include necessary "
        "imports, docstrings, and brief inline comments."
    ),
}


class AgentCoordinator:
    """Orchestrates multiple specialised LLM agents."""

    def __init__(self, config: Any, ollama_client: Any) -> None:
        self.config = config
        self.ollama = ollama_client

    def _make_agent(self, role: str) -> Agent:
        description = _ROLE_DESCRIPTIONS.get(
            role,
            f"You are a specialised {role} agent within LLM-OS. Respond accurately and concisely.",
        )
        return Agent(name=role, role_description=description, config=self.config, ollama_client=self.ollama)

    def spawn_agent(self, role: str, task: str, context: str | None = None) -> str:
        return self._make_agent(role).run(task, context)

    def run_parallel(self, tasks: dict[str, str]) -> dict[str, str]:
        """Run multiple agents concurrently; returns {task_name: response}."""
        results: dict[str, str] = {}
        lock = threading.Lock()
        threads: list[threading.Thread] = []

        def _worker(task_name: str, task_desc: str) -> None:
            try:
                response = self.spawn_agent(task_name, task_desc)
            except Exception as exc:
                response = f"Error: {exc}"
            with lock:
                results[task_name] = response

        for task_name, task_desc in tasks.items():
            t = threading.Thread(target=_worker, args=(task_name, task_desc), daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        return results

    def pipeline(self, steps: list[dict[str, str]]) -> list[str]:
        """Run agents sequentially; each step receives the previous output as context."""
        responses: list[str] = []
        previous_output: str | None = None
        for step in steps:
            role = step.get("role", "analyzer")
            task = step.get("task", "")
            response = self.spawn_agent(role, task, context=previous_output)
            responses.append(response)
            previous_output = response
        return responses
