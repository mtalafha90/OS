"""LLM-callable tools for Docker, Podman, and Singularity container management."""

from __future__ import annotations

import json

from .registry import tool


def _manager():
    from llmos.containers import ContainerManager

    return ContainerManager()


@tool(
    name="list_container_images",
    description=(
        "List container images available on this machine. "
        "Supports docker, podman, and singularity/apptainer runtimes."
    ),
    properties={
        "runtime": {
            "type": "string",
            "description": "Container runtime to use: docker, podman, or singularity (auto-detected if omitted)",
        },
    },
    required=[],
)
def list_container_images(runtime: str = "") -> str:
    mgr = _manager()
    if not mgr.available_runtimes():
        return "No container runtime found. Install docker, podman, singularity, or apptainer."
    images = mgr.list_images(runtime)
    if not images:
        return "No images found."
    lines = [f"{'ID':<15} {'Repository':<35} {'Tag':<15} Size"]
    lines.append("-" * 72)
    for img in images:
        lines.append(
            f"{img.get('id', '')[:12]:<15} {img.get('repository', ''):<35} "
            f"{img.get('tag', ''):<15} {img.get('size', '')}"
        )
    return "\n".join(lines)


@tool(
    name="pull_container_image",
    description="Pull a container image from a registry (Docker Hub, GHCR, etc.).",
    properties={
        "image": {
            "type": "string",
            "description": "Image name and tag, e.g. 'pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime'",
        },
        "runtime": {
            "type": "string",
            "description": "Container runtime: docker, podman, or singularity (auto-detected if omitted)",
        },
    },
    required=["image"],
)
def pull_container_image(image: str, runtime: str = "") -> str:
    mgr = _manager()
    result = mgr.pull_image(image, runtime)
    return result


@tool(
    name="run_container",
    description=(
        "Run a container with an optional command, bind-mount volumes, and GPU access. "
        "Waits for completion and returns the output."
    ),
    properties={
        "image": {"type": "string", "description": "Container image to run"},
        "command": {
            "type": "string",
            "description": "Command to execute inside the container (default: image entrypoint)",
        },
        "volumes": {
            "type": "object",
            "description": (
                "Volume mounts as a JSON object mapping host paths to container paths. "
                'Example: {"/data/input": "/input", "/data/output": "/output"}'
            ),
        },
        "use_gpu": {
            "type": "boolean",
            "description": "Pass GPU devices to the container (default: false)",
        },
        "runtime": {
            "type": "string",
            "description": "Container runtime: docker, podman, or singularity",
        },
        "name": {
            "type": "string",
            "description": "Assign a name to the container (docker/podman only)",
        },
    },
    required=["image"],
)
def run_container(
    image: str,
    command: str = "",
    volumes: dict | None = None,
    use_gpu: bool = False,
    runtime: str = "",
    name: str = "",
) -> str:
    if isinstance(volumes, str):
        try:
            volumes = json.loads(volumes)
        except json.JSONDecodeError:
            volumes = None

    mgr = _manager()
    output, rc = mgr.run_container(
        image=image,
        command=command,
        volumes=volumes or {},
        gpu=use_gpu,
        runtime=runtime,
        name=name,
    )
    result = f"Exit code: {rc}\n"
    if output:
        result += f"Output:\n{output}"
    return result.strip()


@tool(
    name="list_running_containers",
    description="List all currently running containers.",
    properties={
        "runtime": {
            "type": "string",
            "description": "Container runtime: docker, podman, or singularity (auto-detected if omitted)",
        },
    },
    required=[],
)
def list_running_containers(runtime: str = "") -> str:
    mgr = _manager()
    containers = mgr.list_containers(runtime)
    if not containers:
        return "No running containers."
    lines = [f"{'ID':<15} {'Name':<25} {'Image':<35} Status"]
    lines.append("-" * 80)
    for c in containers:
        lines.append(
            f"{c.get('id', '')[:12]:<15} {c.get('name', ''):<25} "
            f"{c.get('image', ''):<35} {c.get('status', '')}"
        )
    return "\n".join(lines)


@tool(
    name="stop_container",
    description="Stop a running container by its ID or name.",
    properties={
        "container_id": {
            "type": "string",
            "description": "Container ID or name (from list_running_containers)",
        },
        "runtime": {
            "type": "string",
            "description": "Container runtime: docker, podman, or singularity",
        },
    },
    required=["container_id"],
)
def stop_container(container_id: str, runtime: str = "") -> str:
    mgr = _manager()
    success = mgr.stop_container(container_id, runtime)
    if success:
        return f"Container '{container_id}' stopped successfully."
    return f"Failed to stop container '{container_id}' (it may have already exited)."


@tool(
    name="get_container_logs",
    description="Retrieve the stdout/stderr output from a running or stopped container.",
    properties={
        "container_id": {
            "type": "string",
            "description": "Container ID or name",
        },
        "tail_lines": {
            "type": "integer",
            "description": "Number of lines to return from the end of the log (default: 100)",
        },
        "runtime": {
            "type": "string",
            "description": "Container runtime: docker, podman, or singularity",
        },
    },
    required=["container_id"],
)
def get_container_logs(
    container_id: str,
    tail_lines: int = 100,
    runtime: str = "",
) -> str:
    mgr = _manager()
    logs = mgr.get_container_logs(container_id, runtime, tail=tail_lines)
    if not logs:
        return f"No log output available for container '{container_id}'."
    return logs
