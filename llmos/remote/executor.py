from __future__ import annotations

"""SSH / SLURM remote compute executor backed by paramiko."""

import re
import time
from pathlib import Path
from typing import Optional

try:
    import paramiko  # type: ignore

    _PARAMIKO_AVAILABLE = True
except ImportError:
    _PARAMIKO_AVAILABLE = False


class RemoteExecutorError(Exception):
    """Raised for SSH / SLURM errors."""


class RemoteExecutor:
    """Manage SSH connections and SLURM job submission to an HPC cluster.

    Parameters
    ----------
    host:      Hostname or IP of the remote machine.
    username:  SSH login username.
    key_file:  Path to the private SSH key (PEM or OpenSSH format).
    port:      SSH port (default 22).
    """

    def __init__(
        self,
        host: str,
        username: str,
        key_file: Optional[str] = None,
        port: int = 22,
    ) -> None:
        if not _PARAMIKO_AVAILABLE:
            raise ImportError(
                "paramiko is required for remote compute: pip install paramiko"
            )
        self.host = host
        self.username = username
        self.key_file = key_file
        self.port = port
        self._client: Optional["paramiko.SSHClient"] = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the SSH connection."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": 30,
        }
        if self.key_file:
            connect_kwargs["key_filename"] = str(Path(self.key_file).expanduser())

        client.connect(**connect_kwargs)
        self._client = client

    def disconnect(self) -> None:
        """Close the SSH connection."""
        if self._client:
            self._client.close()
            self._client = None

    def _ensure_connected(self) -> "paramiko.SSHClient":
        if self._client is None:
            self.connect()
        assert self._client is not None
        return self._client

    def __enter__(self) -> "RemoteExecutor":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    def run_command(
        self,
        command: str,
        timeout: int = 60,
    ) -> tuple[str, str, int]:
        """Execute *command* over SSH.

        Returns ``(stdout, stderr, exit_code)``.
        """
        client = self._ensure_connected()
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return stdout.read().decode(), stderr.read().decode(), exit_code

    # ------------------------------------------------------------------
    # File transfers
    # ------------------------------------------------------------------

    def upload_file(self, local_path: str, remote_path: str) -> None:
        """Upload a local file to the remote host via SFTP."""
        client = self._ensure_connected()
        sftp = client.open_sftp()
        try:
            sftp.put(str(Path(local_path).expanduser()), remote_path)
        finally:
            sftp.close()

    def download_file(self, remote_path: str, local_path: str) -> None:
        """Download a remote file to a local path via SFTP."""
        client = self._ensure_connected()
        sftp = client.open_sftp()
        try:
            sftp.get(remote_path, str(Path(local_path).expanduser()))
        finally:
            sftp.close()

    # ------------------------------------------------------------------
    # SLURM job management
    # ------------------------------------------------------------------

    def submit_slurm(
        self,
        script_path: str,
        job_name: str = "llmos_job",
        nodes: int = 1,
        ntasks: int = 1,
        gres: str = "",
        time_limit: str = "01:00:00",
        partition: str = "compute",
    ) -> str:
        """Submit a batch script via *sbatch* and return the job ID.

        If *script_path* ends in ``.sh`` it is uploaded and submitted;
        otherwise it is treated as the inline script body and a temporary
        remote file is created.
        """
        remote_script = script_path

        # Build sbatch options as a header if the user passed a script body
        # (not a path to an existing file).
        is_file = script_path.strip().startswith("/") or script_path.strip().endswith(".sh")
        if not is_file:
            # Inline script body — write to a temp file on the remote
            header_lines = [
                "#!/bin/bash",
                f"#SBATCH --job-name={job_name}",
                f"#SBATCH --nodes={nodes}",
                f"#SBATCH --ntasks={ntasks}",
                f"#SBATCH --time={time_limit}",
                f"#SBATCH --partition={partition}",
            ]
            if gres:
                header_lines.append(f"#SBATCH --gres={gres}")
            full_script = "\n".join(header_lines) + "\n" + script_path
            remote_script = f"/tmp/llmos_job_{int(time.time())}.sh"
            self.run_command(
                f"cat > {remote_script} << 'LLMOS_EOF'\n{full_script}\nLLMOS_EOF"
            )
        else:
            # Upload the local script file
            import os
            if os.path.isfile(script_path):
                remote_script = f"/tmp/{Path(script_path).name}"
                self.upload_file(script_path, remote_script)

        cmd_parts = [
            "sbatch",
            f"--job-name={job_name}",
            f"--nodes={nodes}",
            f"--ntasks={ntasks}",
            f"--time={time_limit}",
            f"--partition={partition}",
        ]
        if gres:
            cmd_parts.append(f"--gres={gres}")
        cmd_parts.append(remote_script)

        stdout, stderr, rc = self.run_command(" ".join(cmd_parts))
        if rc != 0:
            raise RemoteExecutorError(f"sbatch failed (rc={rc}): {stderr.strip()}")

        # "Submitted batch job 12345"
        match = re.search(r"\b(\d+)\b", stdout)
        if not match:
            raise RemoteExecutorError(f"Could not parse job ID from sbatch output: {stdout!r}")
        return match.group(1)

    def get_slurm_status(self, job_id: str) -> dict:
        """Query SLURM for the status of *job_id*.

        Returns a dict with keys: ``status``, ``state``, ``node``, ``elapsed``.
        """
        stdout, _, rc = self.run_command(
            f"squeue -j {job_id} -o '%T %R %N %M' --noheader 2>/dev/null"
        )
        if rc != 0 or not stdout.strip():
            # Job not in queue — check sacct for completed/failed
            sacct_out, _, _ = self.run_command(
                f"sacct -j {job_id} --format=State,Reason,NodeList,Elapsed "
                f"--noheader --parsable2 2>/dev/null | head -1"
            )
            if sacct_out.strip():
                parts = sacct_out.strip().split("|")
                return {
                    "status": "done",
                    "state": parts[0] if len(parts) > 0 else "UNKNOWN",
                    "node": parts[2] if len(parts) > 2 else "",
                    "elapsed": parts[3] if len(parts) > 3 else "",
                }
            return {"status": "unknown", "state": "UNKNOWN", "node": "", "elapsed": ""}

        parts = stdout.strip().split()
        return {
            "status": "running" if parts[0] == "RUNNING" else "pending",
            "state": parts[0] if parts else "UNKNOWN",
            "node": parts[2] if len(parts) > 2 else "",
            "elapsed": parts[3] if len(parts) > 3 else "",
        }

    def cancel_slurm(self, job_id: str) -> bool:
        """Cancel a SLURM job. Returns True if the cancellation succeeded."""
        _, _, rc = self.run_command(f"scancel {job_id}")
        return rc == 0

    def list_slurm_jobs(self, username: str = "") -> list[dict]:
        """List running and pending SLURM jobs for *username* (defaults to SSH user)."""
        user = username or self.username
        stdout, _, rc = self.run_command(
            f"squeue -u {user} -o '%i %j %T %R %N %M %D' --noheader 2>/dev/null"
        )
        if rc != 0 or not stdout.strip():
            return []

        jobs: list[dict] = []
        for line in stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 6:
                jobs.append(
                    {
                        "job_id": parts[0],
                        "name": parts[1],
                        "state": parts[2],
                        "reason": parts[3],
                        "node": parts[4],
                        "elapsed": parts[5],
                        "nodes": parts[6] if len(parts) > 6 else "1",
                    }
                )
        return jobs
