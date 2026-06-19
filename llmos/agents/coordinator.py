from __future__ import annotations

import threading
from typing import Any

from .base import Agent


# Role descriptions for each specialised agent type
_ROLE_DESCRIPTIONS: dict[str, str] = {
    "gpu_monitor": (
        "You monitor GPU utilisation during computations. "
        "Report current GPU utilisation percentage, memory usage, temperature, "
        "and power draw. Flag any anomalies such as thermal throttling or "
        "out-of-memory conditions."
    ),
    "analyzer": (
        "You analyse simulation results and numerical data. "
        "Identify patterns, anomalies, and statistical insights. "
        "Produce a clear, structured summary with key findings and recommendations."
    ),
    "planner": (
        "You decompose complex scientific or engineering tasks into concrete, "
        "ordered steps. Each step must be specific and actionable. "
        "Consider dependencies, resource requirements, and potential failure modes."
    ),
    "coder": (
        "You write correct, efficient Python code for scientific simulations "
        "and data processing. Validate your code logic before returning it. "
        "Include necessary imports, docstrings, and brief inline comments."
    ),
}


class AgentCoordinator:
    """Orchestrates multiple specialised LLM agents."""

    def __init__(self, config: Any, ollama_client: Any) -> None:
        self.config = config
        self.ollama = ollama_client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_agent(self, role: str) -> Agent:
        description = _ROLE_DESCRIPTIONS.get(
            role,
            f"You are a specialised {role} agent within LLM-OS. Respond accurately and concisely.",
        )
        return Agent(
            name=role,
            role_description=description,
            config=self.config,
            ollama_client=self.ollama,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def spawn_agent(self, role: str, task: str, context: str | None = None) -> str:
        """Spawn a single agent for *role* and run *task*.

        Returns the agent's text response.
        """
        agent = self._make_agent(role)
        return agent.run(task, context)

    def run_parallel(self, tasks: dict[str, str]) -> dict[str, str]:
        """Run multiple agents concurrently.

        *tasks* maps ``task_name`` → ``task_description``.  Each key is also
        used as the agent role (must be one of the known roles or a free-form
        name).

        Returns a dict mapping each task name to the agent's response.
        """
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
            t = threading.Thread(
                target=_worker,
                args=(task_name, task_desc),
                daemon=True,
                name=f"agent-{task_name}",
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        return results

    def pipeline(self, steps: list[dict[str, str]]) -> list[str]:
        """Run agents sequentially; each step receives the previous output as context.

        Each element of *steps* must be a dict with at least:
          - ``role``: agent role to use
          - ``task``: task description for that agent

        Returns a list of responses, one per step.
        """
        responses: list[str] = []
        previous_output: str | None = None

        for step in steps:
            role = step.get("role", "analyzer")
            task = step.get("task", "")
            response = self.spawn_agent(role, task, context=previous_output)
            responses.append(response)
            previous_output = response

        return responses
