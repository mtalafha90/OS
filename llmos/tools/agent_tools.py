from __future__ import annotations

"""LLM-callable tools for multi-agent orchestration."""

import json
from typing import Any

from .registry import tool


def _get_coordinator() -> Any:
    """Lazily create a coordinator using the process-level config and Ollama client."""
    from llmos.config import Config
    from llmos.ollama_client import OllamaClient
    from llmos.agents.coordinator import AgentCoordinator

    config = Config.load()
    client = OllamaClient(base_url=config.ollama_url, timeout=config.request_timeout)
    return AgentCoordinator(config=config, ollama_client=client)


@tool(
    name="run_agents_parallel",
    description=(
        "Run multiple specialised AI agents in parallel on independent tasks. "
        "Available agent roles: gpu_monitor, analyzer, planner, coder. "
        "Each agent works concurrently and returns its result independently."
    ),
    properties={
        "tasks": {
            "type": "object",
            "description": (
                "A JSON object mapping agent role names to task descriptions. "
                'Example: {"analyzer": "Summarise the CSV data", "planner": "Design the experiment"}'
            ),
        },
    },
    required=["tasks"],
)
def run_agents_parallel(tasks: dict | str) -> str:
    if isinstance(tasks, str):
        try:
            tasks = json.loads(tasks)
        except json.JSONDecodeError as exc:
            return f"Error: tasks must be a JSON object: {exc}"

    coordinator = _get_coordinator()
    results = coordinator.run_parallel(tasks)
    lines = [f"=== {role} ===\n{result}" for role, result in results.items()]
    return "\n\n".join(lines)


@tool(
    name="analyze_results",
    description=(
        "Spawn an analyzer agent to answer a specific question about data or results. "
        "The agent will inspect the data and produce a structured analysis."
    ),
    properties={
        "data": {"type": "string", "description": "The data or results to analyse (text, CSV, JSON, etc.)"},
        "question": {"type": "string", "description": "The specific question to answer about the data"},
    },
    required=["data", "question"],
)
def analyze_results(data: str, question: str) -> str:
    coordinator = _get_coordinator()
    task = f"Question: {question}\n\nData:\n{data}"
    return coordinator.spawn_agent("analyzer", task)


@tool(
    name="generate_simulation_code",
    description=(
        "Spawn a coder agent to write Python simulation or data-processing code. "
        "Returns a complete, runnable Python script."
    ),
    properties={
        "description": {
            "type": "string",
            "description": "Detailed description of what the code should do",
        },
        "framework": {
            "type": "string",
            "description": (
                "Scientific framework to use: e.g. numpy, pytorch, jax, gromacs, "
                "lammps, openfoam, scipy (default: numpy)"
            ),
        },
    },
    required=["description"],
)
def generate_simulation_code(description: str, framework: str = "numpy") -> str:
    coordinator = _get_coordinator()
    task = (
        f"Write a Python script using the {framework} framework.\n\n"
        f"Requirements:\n{description}\n\n"
        "Include all necessary imports, a main() function, and if __name__ == '__main__' guard."
    )
    return coordinator.spawn_agent("coder", task)


@tool(
    name="plan_experiment",
    description=(
        "Spawn a planner agent to create a detailed, step-by-step experiment plan "
        "given a scientific goal and any constraints."
    ),
    properties={
        "goal": {
            "type": "string",
            "description": "The scientific or engineering goal of the experiment",
        },
        "constraints": {
            "type": "string",
            "description": (
                "Resource or methodological constraints, e.g. 'max 8 GPU hours, "
                "use GROMACS, output must be in HDF5 format'"
            ),
        },
    },
    required=["goal"],
)
def plan_experiment(goal: str, constraints: str = "") -> str:
    coordinator = _get_coordinator()
    task = f"Goal: {goal}"
    if constraints:
        task += f"\n\nConstraints: {constraints}"
    task += (
        "\n\nProduce a numbered, step-by-step experiment plan. "
        "For each step specify: action, inputs, expected outputs, and estimated time."
    )
    return coordinator.spawn_agent("planner", task)
