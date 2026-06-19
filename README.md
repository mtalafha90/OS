# LLM-OS

An Ubuntu-based Linux distribution where an LLM (powered by [Ollama](https://ollama.com)) **is** the operating system's primary interface. Instead of a traditional shell, you talk to the OS in plain English — and it can do everything from managing files to submitting HPC jobs.

```
llmos> run a molecular dynamics simulation with GROMACS, track the run, and generate a PDF report

  ↳ track_simulation(name="protein_fold_NVT", tags=["gromacs", "NVT"])
  ↳ run_simulation(command="gmx mdrun -v -deffnm md_NVT", gpu_ids=[0], mpi_ranks=4)
  ↳ finish_simulation(run_id="a3f1...", metrics={"energy": -42310.5, "rmsd": 0.87})
  ↳ create_simulation_report(run_id="a3f1...")

Report saved: ~/reports/sim_a3f1_20260619.pdf
```

---

## Features

### Core
- **Natural language OS control** — files, processes, network, packages, system info
- **89 LLM-callable tools** across 15 categories, all registered automatically
- **Multi-turn context** — the LLM remembers your conversation and builds on previous steps
- **Streaming tool calls** — watch the LLM work step by step in real time

### Interface
- **Browser-based desktop** — Ubuntu Yaru theme, draggable windows, dock, Activities overlay
- **Real-time dashboard** — Chart.js graphs for CPU/RAM/disk/GPU, tabbed job queue, simulation history, plot gallery
- **Terminal shell** — lightweight REPL for headless servers and scripts
- **Voice input** — speak to the OS (Whisper STT), hear responses (pyttsx3/espeak TTS)

### Scientific Computing
- **GPU passthrough** — bare-metal NVIDIA CUDA 12.6 + AMD ROCm 6.2 in the VM
- **Full HPC stack** — GROMACS, LAMMPS, OpenFOAM, OpenMPI, PyTorch, JAX, RAPIDS, JupyterLab
- **Job scheduler** — queue and run simulations with GPU/MPI resource allocation
- **Simulation versioning** — track every run with parameters, metrics, and full-text search
- **Result visualization** — matplotlib dark-theme plots (timeseries, heatmap, 3D scatter, histogram)
- **Auto-report generation** — HTML + PDF reports from simulation runs (with embedded plots)

### Infrastructure
- **Persistent memory/RAG** — the LLM remembers facts across sessions (ChromaDB or SQLite FTS5)
- **Multi-agent mode** — spawn parallel specialist agents (GPU monitor, analyzer, planner, coder)
- **Remote HPC compute** — SSH to clusters, submit SLURM jobs, transfer files via SFTP
- **Container management** — Docker, Podman, and Singularity/Apptainer with GPU passthrough
- **Plugin system** — drop `.py` files into `~/.config/llmos/tools/` to add custom tools

### VM
- **Packer-built images** — VirtualBox OVA + QEMU QCOW2, one command to build
- **Auto first-boot** — GPU driver installed automatically on first boot (NVIDIA or AMD detected via `lspci`)
- **systemd services** — Ollama and LLM-OS start automatically

---

## Quick Start

### Run locally (no VM)

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2

# 2. Install LLM-OS (core only)
git clone https://github.com/mtalafha90/OS.git
cd OS
pip install -e .

# 3. Launch terminal shell
llmos

# 4. Or launch the web UI
pip install -e ".[web]"
llmos --web          # → http://localhost:8080
```

### Install optional feature packs

```bash
pip install -e ".[memory]"    # ChromaDB + sentence-transformers (RAG)
pip install -e ".[voice]"     # Whisper STT + pyttsx3 TTS
pip install -e ".[remote]"    # paramiko (SSH/SFTP to HPC clusters)
pip install -e ".[reports]"   # reportlab + weasyprint (PDF reports)
pip install -e ".[sci]"       # numpy, scipy, pandas, matplotlib, plotly, ...
pip install -e ".[all]"       # everything
```

All optional deps degrade gracefully — the core shell works even if none are installed.

---

## Web UI

```bash
llmos --web [--port 8080]
make web
```

Opens a browser-based desktop at `http://localhost:8080`.

**Assistant window** — chat with the OS, watch tool calls in real time, use quick-action buttons, speak with the microphone button.

**Dashboard window** (click 📊 in the dock):
- **Monitor tab** — live CPU, RAM, disk, GPU charts (Chart.js, 60-second rolling window, updates every 2 s)
- **Jobs tab** — job queue with status badges, cancel buttons, submit-job dialog
- **History tab** — expandable simulation run history with full metadata
- **Plots tab** — thumbnail gallery of all files in `~/plots/`, click to enlarge

**Settings** (⚙️ in the dock) — switch Ollama models without restarting.

---

## Terminal Shell

```bash
llmos                              # interactive REPL
llmos --cmd "show disk usage"      # one-shot, then exit
llmos --model qwen2.5:14b          # override model
llmos --config config/llmos-hpc.yaml
```

Built-in commands:
```
models            list available Ollama models
model <name>      switch to a different model
history clear     clear conversation context
clear             clear the screen
exit              quit
```

---

## All 89 Tools

### Core (always available)

| Category | Tools |
|---|---|
| **Filesystem** | `list_directory` `read_file` `write_file` `create_directory` `delete_path` `move_path` `copy_path` `search_files` `get_disk_usage` |
| **Process** | `list_processes` `kill_process` `run_command` `systemctl_action` `get_system_info` |
| **Network** | `ping_host` `check_port` `dns_lookup` `get_network_interfaces` `http_request` `get_network_stats` |
| **Packages** | `apt_install` `apt_remove` `apt_update` `apt_upgrade` `apt_search` `apt_show` `list_installed_packages` `pip_install` `pip_uninstall` |
| **GPU** | `get_gpu_info` `monitor_gpu` `list_gpu_processes` `set_gpu_power_limit` `get_cuda_info` `reset_gpu` |
| **Scientific** | `run_python_code` `launch_jupyter` `get_scientific_stack` `run_simulation` `create_conda_env` `list_conda_envs` `run_benchmark` `install_hpc_software` |

### Optional (loaded when deps are present)

| Category | Tools | Requires |
|---|---|---|
| **Memory/RAG** | `remember` `recall` `list_memories` `forget` | `chromadb sentence-transformers` |
| **Scheduler** | `submit_job` `list_jobs` `get_job_status` `cancel_job` `get_job_log` `get_job_stats` | stdlib only |
| **Multi-agent** | `run_agents_parallel` `analyze_results` `generate_simulation_code` `plan_experiment` | stdlib only |
| **Voice** | `speak` `listen_microphone` `voice_status` | `openai-whisper sounddevice pyttsx3` |
| **Versioning** | `track_simulation` `finish_simulation` `list_simulations` `get_simulation` `compare_simulations` `search_simulations` | stdlib only |
| **Remote HPC** | `add_cluster` `list_clusters` `run_remote_command` `submit_hpc_job` `get_hpc_job_status` `cancel_hpc_job` `list_hpc_jobs` `upload_to_cluster` `download_from_cluster` | `paramiko` |
| **Containers** | `list_container_images` `pull_container_image` `run_container` `list_running_containers` `stop_container` `get_container_logs` | docker/podman/singularity binary |
| **Reports** | `generate_report` `create_simulation_report` `list_reports` | `reportlab` or `weasyprint` |
| **Visualization** | `render_plot` `plot_timeseries` `plot_heatmap` `plot_histogram` `plot_scatter_3d` | `matplotlib` |

---

## Feature Guides

### Persistent Memory

The LLM remembers facts across sessions.

```
llmos> remember that my cluster login is user@hpc.university.edu

llmos> what's my cluster login?
  ↳ recall(query="cluster login")
Your cluster login is user@hpc.university.edu
```

Storage: `~/.config/llmos/memory/` — ChromaDB vector DB if available, SQLite FTS5 otherwise.

### Job Scheduler

Queue long-running simulations with GPU and MPI resource allocation. A background daemon picks up pending jobs and runs up to 2 concurrently (configurable).

```
llmos> submit a job to run python train.py --epochs 100 on GPU 0

  ↳ submit_job(name="training", command="python train.py --epochs 100",
               gpu_ids="0", priority=5)
Job submitted. ID: b2c3d4e5
```

Job state is stored in `~/.config/llmos/jobs.db`. Logs are written to `~/.config/llmos/logs/`.

### Simulation Versioning

Every simulation run is tracked — parameters, metrics, output files, timing, and notes.

```
llmos> compare my last 3 GROMACS runs

  ↳ list_simulations(tag="gromacs", limit=3)
  ↳ compare_simulations(run_ids=["a1b2...", "c3d4...", "e5f6..."])

  Parameter       run1 (a1b2)   run2 (c3d4)   run3 (e5f6)
  timestep        0.002         0.002         0.001         *
  temperature     300           310 *         300
  pressure        1.0           1.0           1.0

  Metric          run1          run2          run3
  energy (kJ/mol) -42310.5      -41980.2      -42540.1
  rmsd (nm)       0.87          0.91          0.83         *
```

Data stored in `~/.config/llmos/simulations.db` with full-text search.

### Multi-Agent Mode

Spawn multiple specialist LLM agents to work in parallel.

```
llmos> analyze my simulation results using the analyzer and planner agents in parallel

  ↳ run_agents_parallel(task="analyze results in ~/sim/output/",
                        roles=["analyzer", "planner"])
```

Roles: `gpu_monitor`, `analyzer`, `planner`, `coder`. Results are merged and returned together.

### Voice Interface

```
llmos> voice_status        ← check what's installed

# Then speak to the OS via the microphone button in the web UI,
# or from the terminal:
llmos> listen_microphone(duration=5)
llmos> speak("Simulation complete. Energy converged at -42310 kJ/mol.")
```

Install deps: `pip install openai-whisper sounddevice pyttsx3`

### Remote HPC Compute

```
llmos> add my university cluster

  ↳ add_cluster(name="uni-hpc", host="hpc.university.edu",
                username="myuser", key_file="~/.ssh/id_rsa")

llmos> submit a SLURM job to run my simulation on 4 GPUs

  ↳ submit_hpc_job(cluster="uni-hpc", script="run.sh",
                   gpus=4, partition="gpu", time="24:00:00")
  Job submitted: SLURM job 1234567
```

Cluster config stored in `~/.config/llmos/clusters.json`.

### Container Management

Works with Docker, Podman, and Singularity/Apptainer automatically.

```
llmos> run my PyTorch container with GPU access and mount /data

  ↳ run_container(image="pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime",
                  command="python train.py",
                  volumes={"/data": "/data"},
                  use_gpu=True)
```

### Auto-Report Generation

```
llmos> generate a PDF report of run a3f1 with the plots from ~/plots/

  ↳ create_simulation_report(run_id="a3f1", notes="NVT equilibration at 300K")

Report saved:
  HTML: ~/reports/sim_a3f1_20260619.html
  PDF:  ~/reports/sim_a3f1_20260619.pdf
```

PDF backend: reportlab → weasyprint → wkhtmltopdf → HTML fallback.

### Visualization

```
llmos> plot the energy over time from energy.csv and save it

  ↳ plot_timeseries(csv_file="energy.csv", x_col="time", y_col="energy",
                    title="NVT Energy", output="~/plots/energy.png")

Saved: ~/plots/energy.png
```

All plots appear automatically in the dashboard's Plots tab.

### Plugin System

Add your own tools by dropping a Python file into `~/.config/llmos/tools/`:

```python
# ~/.config/llmos/tools/my_tools.py
from llmos.tools.registry import tool

@tool(
    name="my_custom_tool",
    description="Does something custom.",
    properties={"input": {"type": "string", "description": "Input data"}},
    required=["input"],
)
def my_custom_tool(input: str) -> str:
    return f"Processed: {input}"
```

Plugins are loaded at startup. An example plugin is written automatically on first run.

---

## Running in a Virtual Machine

> **Recommended for scientific computing** — gives you a fully isolated GPU-accelerated environment.

### Build the VM image

Prerequisites: [Packer ≥ 1.10](https://developer.hashicorp.com/packer/install), QEMU/KVM or VirtualBox.

```bash
cd packer
packer init llmos.pkr.hcl             # download plugins (once)
packer build llmos.pkr.hcl            # build both OVA + QCOW2 (~30–45 min)

# Or build one format:
packer build -only=virtualbox-iso.llmos llmos.pkr.hcl   # → dist/virtualbox/llmos.ova
packer build -only=qemu.llmos          llmos.pkr.hcl   # → dist/qemu/llmos.qcow2
```

### VirtualBox

```bash
# Import
VBoxManage import dist/virtualbox/llmos.ova --vsys 0 --vmname "LLM-OS"
VBoxManage startvm "LLM-OS"

# Or: File → Import Appliance in the VirtualBox GUI
```

### QEMU / KVM

```bash
qemu-system-x86_64 \
  -m 8G -smp 4 \
  -drive file=dist/qemu/llmos.qcow2,format=qcow2 \
  -net nic -net user,hostfwd=tcp::8080-:8080,hostfwd=tcp::2222-:22 \
  -enable-kvm
```

### GPU Passthrough (NVIDIA or AMD)

Gives the VM direct bare-metal GPU access. No virtualization overhead — full CUDA/ROCm performance.

```bash
# Step 1: configure the host (run once, then reboot)
sudo bash scripts/setup-gpu-passthrough.sh

# Step 2: build the VM (if not done)
cd packer && packer build llmos.pkr.hcl

# Step 3: launch with GPU
bash scripts/run-vm-gpu.sh    # generated by setup-gpu-passthrough.sh
```

On first boot the VM auto-detects the GPU vendor and installs the correct driver.

> VirtualBox does **not** support CUDA passthrough. Use QEMU/KVM for GPU compute.

### First boot

1. Login: `llmos` / `llmos`
2. Web UI starts automatically at `http://<vm-ip>:8080`
3. If the model wasn't pre-pulled (~2 GB), it downloads on first boot

---

## GPU & Scientific Stack (pre-installed in VM)

| Category | Software |
|---|---|
| GPU support | NVIDIA CUDA 12.6 + cuDNN 9, AMD ROCm 6.2 |
| Deep Learning | PyTorch 2.3, JAX (CUDA), TensorFlow |
| GPU Computing | CuPy, RAPIDS (cuDF, cuML, cuGraph) |
| Simulation | GROMACS, LAMMPS, OpenFOAM |
| Parallel | OpenMPI (CUDA-aware), mpi4py, Dask |
| Data | NumPy, SciPy, Pandas, HDF5, NetCDF4 |
| Visualization | ParaView, Matplotlib, Plotly |
| Interactive | JupyterLab + GPU dashboard |
| Environment | Miniforge (conda/mamba) |

---

## Configuration

`~/.config/llmos/config.yaml`

```yaml
ollama_url: "http://localhost:11434"
model: "llama3.2"
max_history: 50
show_tool_calls: true
request_timeout: 120.0
```

For HPC use cases, `config/llmos-hpc.yaml` ships with a larger model and longer timeout:

```bash
llmos --config config/llmos-hpc.yaml
```

---

## Supported Models

Any Ollama model works. Recommended:

| Model | Size | Best for |
|---|---|---|
| `llama3.2` | 2 GB | Default — fast, capable |
| `mistral` | 4 GB | Strong instruction following |
| `qwen2.5:14b` | 8 GB | Best for HPC/coding tasks |
| `phi4-mini` | 2 GB | Fastest, low-resource systems |

Switch at runtime: type `model qwen2.5:14b` in the shell, or use the Settings panel in the web UI.

---

## Project Structure

```
OS/
├── llmos/                      # Core Python package
│   ├── main.py                 # CLI entry point
│   ├── shell.py                # Terminal REPL
│   ├── config.py               # Configuration dataclass
│   ├── ollama_client.py        # Ollama HTTP client
│   ├── tools/                  # 89 LLM-callable tools
│   │   ├── registry.py         # @tool decorator + dispatcher
│   │   ├── filesystem.py       # File operations (9 tools)
│   │   ├── process.py          # Process management (5 tools)
│   │   ├── network.py          # Network (6 tools)
│   │   ├── packages.py         # apt + pip (9 tools)
│   │   ├── gpu.py              # GPU monitor/control (6 tools)
│   │   ├── scientific.py       # Simulations + HPC (8 tools)
│   │   ├── memory_tools.py     # RAG memory (4 tools)
│   │   ├── scheduler_tools.py  # Job queue (6 tools)
│   │   ├── agent_tools.py      # Multi-agent (4 tools)
│   │   ├── voice_tools.py      # STT/TTS (3 tools)
│   │   ├── versioning_tools.py # Sim tracking (6 tools)
│   │   ├── remote_tools.py     # HPC/SSH (9 tools)
│   │   ├── container_tools.py  # Docker/Podman/Singularity (6 tools)
│   │   ├── report_tools.py     # PDF/HTML reports (3 tools)
│   │   └── visualization_tools.py # Plots (5 tools)
│   ├── memory/                 # ChromaDB + SQLite FTS5 RAG store
│   ├── scheduler/              # SQLite job queue + daemon runner
│   ├── agents/                 # Multi-agent coordinator
│   ├── voice/                  # Whisper STT + pyttsx3 TTS
│   ├── versioning/             # Simulation run tracker
│   ├── remote/                 # SSH/SLURM executor
│   ├── containers/             # Docker/Podman/Singularity manager
│   ├── reports/                # HTML + PDF report generator
│   ├── plugins/                # Dynamic plugin loader
│   └── webui/
│       ├── server.py           # FastAPI + WebSocket backend
│       └── static/
│           ├── index.html      # Desktop UI + dashboard
│           ├── style.css       # Ubuntu Yaru theme
│           └── app.js          # Chart.js, voice, job queue
├── packer/
│   ├── llmos.pkr.hcl           # Packer template (VirtualBox + QEMU)
│   ├── http/user-data          # Ubuntu autoinstall cloud-init
│   └── scripts/
│       ├── provision.sh        # Ollama + llmos install
│       ├── provision-scientific.sh  # CUDA + ROCm + HPC stack
│       ├── pull-model.sh       # Pre-pull llama3.2
│       └── cleanup.sh          # Zero free space, remove SSH keys
├── scripts/
│   ├── setup-gpu-passthrough.sh  # VFIO/IOMMU host setup wizard
│   └── first-boot.sh           # Auto GPU driver install
├── config/
│   ├── llmos.yaml              # Default config
│   └── llmos-hpc.yaml          # HPC config (larger model)
├── systemd/
│   ├── ollama.service
│   ├── llmos.service
│   └── llmos-firstboot.service
├── .gitignore
├── pyproject.toml
├── requirements.txt
└── Makefile
```

---

## License

MIT
