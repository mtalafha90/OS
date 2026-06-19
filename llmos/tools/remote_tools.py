"""LLM-callable tools for remote HPC cluster management via SSH/SLURM."""

from __future__ import annotations

from .registry import tool

# ---------------------------------------------------------------------------
# Cluster registration
# ---------------------------------------------------------------------------


@tool(
    name="add_cluster",
    description=(
        "Register an HPC cluster so it can be used by other remote tools. "
        "The cluster credentials are stored in ~/.config/llmos/clusters.json."
    ),
    properties={
        "name": {
            "type": "string",
            "description": "Short identifier for this cluster (e.g. 'frontier')",
        },
        "host": {
            "type": "string",
            "description": "Hostname or IP address of the cluster login node",
        },
        "username": {"type": "string", "description": "SSH username"},
        "key_file": {"type": "string", "description": "Path to the SSH private key file"},
        "port": {"type": "integer", "description": "SSH port (default: 22)"},
    },
    required=["name", "host", "username", "key_file"],
)
def add_cluster(name: str, host: str, username: str, key_file: str, port: int = 22) -> str:
    from llmos.remote import add_cluster as _add

    _add(name, host, username, key_file, port)
    return f"Cluster '{name}' registered ({username}@{host}:{port})."


@tool(
    name="list_clusters",
    description="List all registered HPC clusters.",
    properties={},
    required=[],
)
def list_clusters() -> str:
    from llmos.remote import list_clusters as _list

    names = _list()
    if not names:
        return "No clusters registered. Use add_cluster to register one."
    return "Registered clusters:\n" + "\n".join(f"  • {n}" for n in names)


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------


@tool(
    name="run_remote_command",
    description="Run an arbitrary shell command on a registered HPC cluster via SSH.",
    properties={
        "cluster": {
            "type": "string",
            "description": "Cluster name (as registered with add_cluster)",
        },
        "command": {"type": "string", "description": "Shell command to execute on the remote host"},
        "timeout": {"type": "integer", "description": "Command timeout in seconds (default: 60)"},
    },
    required=["cluster", "command"],
)
def run_remote_command(cluster: str, command: str, timeout: int = 60) -> str:
    from llmos.remote import get_cluster

    executor = get_cluster(cluster)
    with executor:
        stdout, stderr, rc = executor.run_command(command, timeout=timeout)
    parts = []
    if stdout.strip():
        parts.append(f"stdout:\n{stdout.strip()}")
    if stderr.strip():
        parts.append(f"stderr:\n{stderr.strip()}")
    parts.append(f"exit code: {rc}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# SLURM job submission and management
# ---------------------------------------------------------------------------


@tool(
    name="submit_hpc_job",
    description=(
        "Submit a batch script to SLURM on a registered HPC cluster. "
        "You can provide either the path to an existing .sh file or the raw "
        "script body as the 'script' argument. Returns the SLURM job ID."
    ),
    properties={
        "cluster": {"type": "string", "description": "Cluster name"},
        "script": {
            "type": "string",
            "description": "Path to the batch script on the local filesystem, or the inline script body",
        },
        "job_name": {"type": "string", "description": "SLURM job name (default: llmos_job)"},
        "nodes": {"type": "integer", "description": "Number of nodes (default: 1)"},
        "gpus": {
            "type": "integer",
            "description": "Number of GPUs per node via --gres=gpu:<n> (default: 0)",
        },
        "hours": {"type": "number", "description": "Wall-clock time limit in hours (default: 1)"},
        "partition": {"type": "string", "description": "SLURM partition name (default: compute)"},
    },
    required=["cluster", "script"],
)
def submit_hpc_job(
    cluster: str,
    script: str,
    job_name: str = "llmos_job",
    nodes: int = 1,
    gpus: int = 0,
    hours: float = 1.0,
    partition: str = "compute",
) -> str:
    from llmos.remote import get_cluster

    # Convert hours to HH:MM:SS
    total_minutes = int(hours * 60)
    h, m = divmod(total_minutes, 60)
    time_limit = f"{h:02d}:{m:02d}:00"

    gres = f"gpu:{gpus}" if gpus > 0 else ""

    executor = get_cluster(cluster)
    with executor:
        job_id = executor.submit_slurm(
            script_path=script,
            job_name=job_name,
            nodes=nodes,
            ntasks=nodes,
            gres=gres,
            time_limit=time_limit,
            partition=partition,
        )
    return f"Job submitted to {cluster}. SLURM Job ID: {job_id}"


@tool(
    name="get_hpc_job_status",
    description="Check the status of a SLURM job on a registered cluster.",
    properties={
        "cluster": {"type": "string", "description": "Cluster name"},
        "job_id": {"type": "string", "description": "SLURM job ID returned by submit_hpc_job"},
    },
    required=["cluster", "job_id"],
)
def get_hpc_job_status(cluster: str, job_id: str) -> str:
    from llmos.remote import get_cluster

    executor = get_cluster(cluster)
    with executor:
        status = executor.get_slurm_status(job_id)
    lines = [f"Job {job_id} on {cluster}:"]
    for k, v in status.items():
        if v:
            lines.append(f"  {k}: {v}")
    return "\n".join(lines)


@tool(
    name="cancel_hpc_job",
    description="Cancel a running or pending SLURM job on a registered cluster.",
    properties={
        "cluster": {"type": "string", "description": "Cluster name"},
        "job_id": {"type": "string", "description": "SLURM job ID to cancel"},
    },
    required=["cluster", "job_id"],
)
def cancel_hpc_job(cluster: str, job_id: str) -> str:
    from llmos.remote import get_cluster

    executor = get_cluster(cluster)
    with executor:
        success = executor.cancel_slurm(job_id)
    if success:
        return f"Job {job_id} on {cluster} cancelled successfully."
    return f"Failed to cancel job {job_id} on {cluster} (it may have already finished)."


@tool(
    name="list_hpc_jobs",
    description="List all running and pending SLURM jobs for your user on a registered cluster.",
    properties={
        "cluster": {"type": "string", "description": "Cluster name"},
    },
    required=["cluster"],
)
def list_hpc_jobs(cluster: str) -> str:
    from llmos.remote import get_cluster

    executor = get_cluster(cluster)
    with executor:
        jobs = executor.list_slurm_jobs()

    if not jobs:
        return f"No running or pending jobs on {cluster}."

    header = f"{'JobID':<12} {'Name':<20} {'State':<12} {'Node':<16} {'Elapsed'}"
    lines = [f"Jobs on {cluster}:", header, "-" * 72]
    for j in jobs:
        lines.append(
            f"{j.get('job_id', ''):<12} {j.get('name', ''):<20} "
            f"{j.get('state', ''):<12} {j.get('node', ''):<16} {j.get('elapsed', '')}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# File transfers
# ---------------------------------------------------------------------------


@tool(
    name="upload_to_cluster",
    description="Upload a local file to a registered HPC cluster via SFTP.",
    properties={
        "cluster": {"type": "string", "description": "Cluster name"},
        "local_path": {"type": "string", "description": "Path to the local file to upload"},
        "remote_path": {"type": "string", "description": "Destination path on the remote cluster"},
    },
    required=["cluster", "local_path", "remote_path"],
)
def upload_to_cluster(cluster: str, local_path: str, remote_path: str) -> str:
    from llmos.remote import get_cluster

    executor = get_cluster(cluster)
    with executor:
        executor.upload_file(local_path, remote_path)
    return f"Uploaded {local_path} → {cluster}:{remote_path}"


@tool(
    name="download_from_cluster",
    description="Download a file from a registered HPC cluster to the local machine via SFTP.",
    properties={
        "cluster": {"type": "string", "description": "Cluster name"},
        "remote_path": {"type": "string", "description": "Path to the file on the remote cluster"},
        "local_path": {"type": "string", "description": "Local destination path"},
    },
    required=["cluster", "remote_path", "local_path"],
)
def download_from_cluster(cluster: str, remote_path: str, local_path: str) -> str:
    from llmos.remote import get_cluster

    executor = get_cluster(cluster)
    with executor:
        executor.download_file(remote_path, local_path)
    return f"Downloaded {cluster}:{remote_path} → {local_path}"
