"""Docker, Podman, and Singularity/Apptainer container management."""

from __future__ import annotations

import shutil
import subprocess


class ContainerError(Exception):
    """Raised when a container operation fails."""


def _run(
    cmd: list[str],
    timeout: int = 120,
    input_text: str | None = None,
) -> tuple[str, str, int]:
    """Run *cmd*, return (stdout, stderr, returncode)."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_text,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def _detect_runtimes() -> dict[str, str]:
    """Return a dict mapping runtime name → executable path for each available runtime."""
    runtimes: dict[str, str] = {}
    candidates = [
        ("docker", "docker"),
        ("podman", "podman"),
        ("singularity", "singularity"),
        ("apptainer", "apptainer"),
    ]
    for name, exe in candidates:
        path = shutil.which(exe)
        if path:
            # Verify it actually responds
            rc = subprocess.run([exe, "--version"], capture_output=True, timeout=5).returncode
            if rc == 0:
                # Normalise apptainer → singularity for API purposes
                key = "singularity" if name == "apptainer" else name
                runtimes[key] = path
    return runtimes


class ContainerManager:
    """Unified interface for Docker, Podman, and Singularity/Apptainer."""

    def __init__(self) -> None:
        self._runtimes = _detect_runtimes()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _exe(self, runtime: str) -> str:
        """Return the executable for *runtime*, or raise if not available."""
        runtime = runtime.lower()
        if runtime not in self._runtimes:
            available = list(self._runtimes.keys())
            if not available:
                raise ContainerError(
                    "No container runtime found. Install docker, podman, singularity, or apptainer."
                )
            # Fall back to first available
            runtime = available[0]
        return self._runtimes[runtime]

    def _is_singularity(self, runtime: str) -> bool:
        return runtime.lower() in ("singularity", "apptainer")

    def available_runtimes(self) -> list[str]:
        return list(self._runtimes.keys())

    def _default_runtime(self) -> str:
        for preferred in ("docker", "podman", "singularity"):
            if preferred in self._runtimes:
                return preferred
        return list(self._runtimes.keys())[0] if self._runtimes else "docker"

    # ------------------------------------------------------------------
    # Image management
    # ------------------------------------------------------------------

    def list_images(self, runtime: str = "") -> list[dict]:
        """List locally available images.

        Returns a list of dicts with keys: ``id``, ``repository``, ``tag``, ``size``.
        """
        runtime = runtime or self._default_runtime()
        exe = self._exe(runtime)

        if self._is_singularity(runtime):
            # Singularity doesn't have a local registry in the Docker sense;
            # list .sif files in ~/.singularity/cache or CWD.
            import glob
            import os

            sif_dirs = [
                os.path.expanduser("~/.singularity/cache"),
                os.path.expanduser("~/.apptainer/cache"),
                ".",
            ]
            images = []
            for d in sif_dirs:
                for sif in glob.glob(f"{d}/**/*.sif", recursive=True):
                    size = os.path.getsize(sif) if os.path.isfile(sif) else 0
                    images.append(
                        {
                            "id": sif,
                            "repository": sif,
                            "tag": "latest",
                            "size": f"{size // 1024 // 1024}MB",
                        }
                    )
            return images

        # Docker / Podman
        stdout, stderr, rc = _run(
            [exe, "images", "--format", "{{.ID}}\t{{.Repository}}\t{{.Tag}}\t{{.Size}}"],
            timeout=30,
        )
        if rc != 0:
            raise ContainerError(f"list_images failed: {stderr}")
        images = []
        for line in stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 4:
                images.append(
                    {
                        "id": parts[0],
                        "repository": parts[1],
                        "tag": parts[2],
                        "size": parts[3],
                    }
                )
        return images

    def pull_image(self, image: str, runtime: str = "") -> str:
        """Pull *image* from a registry.

        Returns the pull output / digest as a string.
        """
        runtime = runtime or self._default_runtime()
        exe = self._exe(runtime)

        if self._is_singularity(runtime):
            # Pull to a local .sif file in current directory
            sif_name = image.replace("/", "_").replace(":", "_") + ".sif"
            stdout, stderr, rc = _run(
                [exe, "pull", sif_name, f"docker://{image}"],
                timeout=600,
            )
        else:
            stdout, stderr, rc = _run([exe, "pull", image], timeout=600)

        if rc != 0:
            raise ContainerError(f"pull_image failed: {stderr}")
        return stdout or f"Image '{image}' pulled successfully."

    # ------------------------------------------------------------------
    # Container lifecycle
    # ------------------------------------------------------------------

    def run_container(
        self,
        image: str,
        command: str = "",
        volumes: dict[str, str] | None = None,
        gpu: bool = False,
        runtime: str = "",
        name: str = "",
    ) -> tuple[str, int]:
        """Run a container to completion and return ``(output, exit_code)``."""
        runtime = runtime or self._default_runtime()
        exe = self._exe(runtime)
        cmd: list[str]

        if self._is_singularity(runtime):
            cmd = [exe, "run"]
            if gpu:
                cmd.append("--nv")
            if volumes:
                for host_path, container_path in volumes.items():
                    cmd += ["--bind", f"{host_path}:{container_path}"]
            cmd.append(image)
            if command:
                cmd += command.split()
        else:
            # Docker / Podman
            cmd = [exe, "run", "--rm"]
            if name:
                cmd += ["--name", name]
            if gpu:
                # Docker: --gpus all; Podman: --device nvidia.com/gpu=all
                if "podman" in exe:
                    cmd += ["--device", "nvidia.com/gpu=all"]
                else:
                    cmd += ["--gpus", "all"]
            if volumes:
                for host_path, container_path in volumes.items():
                    cmd += ["-v", f"{host_path}:{container_path}"]
            cmd.append(image)
            if command:
                cmd += command.split()

        stdout, stderr, rc = _run(cmd, timeout=3600)
        combined = stdout + ("\n" + stderr if stderr else "")
        return combined.strip(), rc

    def run_container_detached(
        self,
        image: str,
        command: str = "",
        volumes: dict[str, str] | None = None,
        gpu: bool = False,
        runtime: str = "",
        name: str = "",
    ) -> str:
        """Start a container in detached mode and return its container ID / name."""
        runtime = runtime or self._default_runtime()
        exe = self._exe(runtime)

        if self._is_singularity(runtime):
            # Singularity: use instance start
            instance_name = name or f"llmos_{image.replace('/', '_').replace(':', '_')}"
            cmd = [exe, "instance", "start"]
            if gpu:
                cmd.append("--nv")
            if volumes:
                for h, c in (volumes or {}).items():
                    cmd += ["--bind", f"{h}:{c}"]
            cmd += [image, instance_name]
            if command:
                cmd += command.split()
            stdout, stderr, rc = _run(cmd, timeout=60)
            if rc != 0:
                raise ContainerError(f"run_container_detached failed: {stderr}")
            return instance_name

        # Docker / Podman
        cmd = [exe, "run", "-d"]
        if name:
            cmd += ["--name", name]
        if gpu:
            if "podman" in exe:
                cmd += ["--device", "nvidia.com/gpu=all"]
            else:
                cmd += ["--gpus", "all"]
        if volumes:
            for h, c in volumes.items():
                cmd += ["-v", f"{h}:{c}"]
        cmd.append(image)
        if command:
            cmd += command.split()

        stdout, stderr, rc = _run(cmd, timeout=60)
        if rc != 0:
            raise ContainerError(f"run_container_detached failed: {stderr}")
        return stdout.strip()

    # ------------------------------------------------------------------
    # Container inspection
    # ------------------------------------------------------------------

    def list_containers(self, runtime: str = "") -> list[dict]:
        """List currently running containers."""
        runtime = runtime or self._default_runtime()
        exe = self._exe(runtime)

        if self._is_singularity(runtime):
            stdout, stderr, rc = _run([exe, "instance", "list"], timeout=30)
            if rc != 0:
                return []
            containers = []
            for line in stdout.splitlines()[1:]:  # skip header
                parts = line.split()
                if parts:
                    containers.append(
                        {
                            "id": parts[0],
                            "name": parts[0],
                            "image": parts[1] if len(parts) > 1 else "",
                            "status": "running",
                        }
                    )
            return containers

        # Docker / Podman
        stdout, _, rc = _run(
            [exe, "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}"],
            timeout=30,
        )
        if rc != 0:
            return []
        containers = []
        for line in stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 4:
                containers.append(
                    {
                        "id": parts[0],
                        "name": parts[1],
                        "image": parts[2],
                        "status": parts[3],
                    }
                )
        return containers

    def stop_container(self, container_id_or_name: str, runtime: str = "") -> bool:
        """Stop a running container. Returns True on success."""
        runtime = runtime or self._default_runtime()
        exe = self._exe(runtime)

        if self._is_singularity(runtime):
            _, _, rc = _run([exe, "instance", "stop", container_id_or_name], timeout=30)
        else:
            _, _, rc = _run([exe, "stop", container_id_or_name], timeout=60)
        return rc == 0

    def get_container_logs(
        self,
        container_id_or_name: str,
        runtime: str = "",
        tail: int = 100,
    ) -> str:
        """Retrieve container log output."""
        runtime = runtime or self._default_runtime()
        exe = self._exe(runtime)

        if self._is_singularity(runtime):
            # Singularity instance logs go to ~/.singularity/instances/logs/
            import glob
            import os

            patterns = [
                os.path.expanduser(f"~/.singularity/instances/logs/**/{container_id_or_name}.err"),
                os.path.expanduser(f"~/.apptainer/instances/logs/**/{container_id_or_name}.err"),
            ]
            for pat in patterns:
                matches = glob.glob(pat, recursive=True)
                if matches:
                    with open(matches[0]) as fh:
                        lines = fh.readlines()
                    return "".join(lines[-tail:])
            return f"No log file found for Singularity instance '{container_id_or_name}'."

        stdout, stderr, rc = _run(
            [exe, "logs", "--tail", str(tail), container_id_or_name],
            timeout=30,
        )
        if rc != 0:
            return f"Error fetching logs: {stderr}"
        return stdout or stderr
