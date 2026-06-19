# LLM-OS

An Ubuntu-based Linux distribution where an LLM (powered by [Ollama](https://ollama.com)) **is** the operating system's primary interface. Instead of a traditional shell, you talk to the OS in plain English.

```
llmos> show me all python files larger than 1MB in /home

  ↳ search_files(directory='/home', name_pattern='*.py')
  ↳ get_disk_usage(path='/home')

Found 3 file(s):
  /home/user/project/dataset_loader.py   (2.1 MB)
  /home/user/scripts/train_model.py      (1.8 MB)
  /home/user/backup/old_pipeline.py      (1.2 MB)
```

---

## Architecture

```
┌─────────────────────────────────────────────┐
│                  User                        │
│         (natural language input)             │
└────────────────────┬────────────────────────┘
                     │
┌────────────────────▼────────────────────────┐
│              LLM-OS Shell                    │
│         llmos/shell.py                       │
│  • Maintains conversation context            │
│  • Streams to Ollama API                     │
│  • Renders Markdown responses (rich)         │
└──────┬─────────────────────────┬────────────┘
       │  tool calls             │ responses
┌──────▼──────────┐   ┌──────────▼───────────┐
│   Tool Registry │   │   Ollama Server       │
│  llmos/tools/   │   │   localhost:11434     │
│                 │   │   Model: llama3.2     │
│  • filesystem   │   └──────────────────────┘
│  • process      │
│  • network      │
│  • packages     │
└─────────────────┘
```

The LLM receives a **system prompt** describing its role as the OS, along with **tool definitions** for file operations, process control, networking, and package management. It autonomously chains tool calls to complete multi-step requests.

---

## Interface

LLM-OS ships with **two interfaces** — choose based on your environment:

### Web UI (Ubuntu-style desktop in the browser)

A full graphical desktop experience inspired by Ubuntu's GNOME interface — top bar, dock, draggable windows, and the LLM assistant at the center.

```bash
llmos --web           # opens http://localhost:8080 in your browser
llmos --web --port 9000
make web
```

Features:
- **Activities overlay** with app launcher grid
- **Draggable, resizable windows** for the AI assistant and settings
- **Quick-action buttons**: System Info, Files, Processes, Network, Disk, Packages
- **Live tool-call display** — watch the LLM work step by step
- **Model switcher** — change Ollama models without restarting
- **Ubuntu Yaru color scheme** (orange + purple dark theme)

### Terminal Shell

A lightweight REPL for headless servers, TTYs, and scripts.

```bash
llmos               # interactive shell
llmos --cmd "list files in /var/log"   # one-shot
```

---

## Quick Start

### Option A — Run on existing Ubuntu/Debian

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2

# 2. Install LLM-OS
git clone https://github.com/mtalafha90/OS.git
cd OS
pip3 install .

# 3. Launch
llmos
```

### Option B — Docker (no install required)

```bash
# Build image
docker build -t llmos -f docker/Dockerfile .

# Run (requires Ollama on host)
docker run -it --rm \
  --add-host host.docker.internal:host-gateway \
  llmos
```

### Option C — Full install script (as root)

```bash
sudo LLMOS_MODEL=llama3.2 bash scripts/install.sh
```

This installs all dependencies, sets up Ollama as a systemd service, and configures `llmos` to auto-start on `tty1`.

---

## Running in a Virtual Machine

> **This is the primary way to use LLM-OS.** The build system produces ready-to-import VM images for VirtualBox and QEMU/KVM.

### Prerequisites

| Tool | Purpose | Install |
|---|---|---|
| [Packer ≥ 1.10](https://developer.hashicorp.com/packer/install) | Builds the VM image | `make vm-deps` |
| [VirtualBox ≥ 7.0](https://www.virtualbox.org/wiki/Downloads) | Runs the OVA (Windows/Mac/Linux) | Download from site |
| QEMU + KVM | Runs QCOW2 (Linux) | `sudo apt install qemu-kvm` |

### Build the VM image

```bash
# Initialize Packer plugins (once)
make packer-init

# Build VirtualBox OVA + QEMU QCOW2 (includes llama3.2, ~25 GB build, ~5 GB output)
make vm

# Or build just one format
make vm-virtualbox    # → dist/virtualbox/llmos.ova
make vm-qemu          # → dist/qemu/llmos.qcow2

# Faster build (skips model pre-pull — VM needs internet on first boot)
make vm-fast
```

Build time: ~30–45 minutes (most time is pulling the Ubuntu ISO + llama3.2 model).

---

### VirtualBox

```bash
# Import via GUI:
#   File → Import Appliance → select dist/virtualbox/llmos.ova

# Or via command line:
VBoxManage import dist/virtualbox/llmos.ova --vsys 0 --vmname "LLM-OS"
VBoxManage startvm "LLM-OS"
```

Recommended settings (already configured in the OVA):
- RAM: **4 GB** minimum (8 GB recommended for larger models)
- CPU: 2 cores
- Storage: 20 GB
- Network: NAT (internet access for package installation)

### QEMU / KVM

```bash
# Start VM with port 8080 forwarded to host
qemu-system-x86_64 \
  -m 4G -smp 2 \
  -drive file=dist/qemu/llmos.qcow2,format=qcow2 \
  -net nic -net user,hostfwd=tcp::8080-:8080,hostfwd=tcp::2222-:22 \
  -enable-kvm \
  -display sdl        # or -nographic for headless
```

### Proxmox / libvirt

```bash
# Copy image to libvirt storage
sudo cp dist/qemu/llmos.qcow2 /var/lib/libvirt/images/

# Create VM (libvirt/virt-manager): point to the QCOW2 as the disk
virt-install --name llmos --memory 4096 --vcpus 2 \
  --disk /var/lib/libvirt/images/llmos.qcow2 \
  --import --os-variant ubuntu24.04
```

---

### First boot

1. **Login**: `llmos` / `llmos` (change with `passwd`)
2. **Web UI** launches automatically at `http://<vm-ip>:8080`
3. If the model wasn't pre-pulled, it downloads on first boot (~2 GB, needs internet)

> **Find the VM's IP**: run `ip addr` in the VM terminal, or check your VM manager's network info.

---

### Building a live ISO (USB/bare-metal)

```bash
make iso-deps   # install live-build
make iso        # → dist/llmos-1.0.0-amd64.iso
sudo dd if=dist/llmos-1.0.0-amd64.iso of=/dev/sdX bs=4M status=progress
```

---

## Usage

| You type | What happens |
|---|---|
| `list files in /var/log` | Lists `/var/log` with sizes and dates |
| `install nginx and start it` | Runs `apt-get install nginx`, then `systemctl start nginx` |
| `what's using port 8080?` | Runs `lsof -i :8080` and explains |
| `show disk usage` | Reports usage on all partitions |
| `ping google.com` | Pings and summarises packet loss |
| `find all .py files containing TODO` | Searches recursively and shows matches |
| `create a file /tmp/hello.txt with "Hello World"` | Writes the file |

### Shell built-ins

```
models          — list available Ollama models
model <name>    — switch to a different model
history clear   — clear conversation context
clear           — clear the screen
exit            — quit LLM-OS
```

### CLI flags

```
llmos [OPTIONS]

  --model, -m MODEL       Override the default model
  --ollama-url, -u URL    Override Ollama server URL
  --config, -c PATH       Path to config YAML
  --no-tool-output        Hide tool call details
  --cmd, -x PROMPT        Run one prompt non-interactively and exit
```

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

---

## Tools available to the LLM

| Category | Tools |
|---|---|
| **Filesystem** | `list_directory`, `read_file`, `write_file`, `create_directory`, `delete_path`, `move_path`, `copy_path`, `search_files`, `get_disk_usage` |
| **Process** | `list_processes`, `kill_process`, `run_command`, `systemctl_action`, `get_system_info` |
| **Network** | `ping_host`, `check_port`, `dns_lookup`, `get_network_interfaces`, `http_request`, `get_network_stats` |
| **Packages** | `apt_install`, `apt_remove`, `apt_update`, `apt_upgrade`, `apt_search`, `apt_show`, `list_installed_packages`, `pip_install`, `pip_uninstall` |

---

## Project Structure

```
OS/
├── llmos/                  # Core Python package
│   ├── main.py             # CLI entry point
│   ├── shell.py            # LLM shell loop
│   ├── config.py           # Configuration
│   ├── ollama_client.py    # Ollama HTTP client
│   └── tools/
│       ├── registry.py     # Tool decorator & dispatcher
│       ├── filesystem.py   # File operations
│       ├── process.py      # Process management
│       ├── network.py      # Network tools
│       └── packages.py     # apt / pip
├── build/
│   └── build-iso.sh        # live-build ISO builder
├── config/
│   └── llmos.yaml          # Default config
├── docker/
│   ├── Dockerfile
│   └── entrypoint.sh
├── scripts/
│   ├── install.sh          # Full system install
│   ├── setup-ollama.sh     # Ollama installer
│   └── first-boot.sh       # First-boot model pull
├── systemd/
│   ├── ollama.service
│   ├── llmos.service
│   └── llmos-firstboot.service
├── Makefile
└── pyproject.toml
```

---

## Supported Models

Any model supported by Ollama works. Recommended:

| Model | Size | Best for |
|---|---|---|
| `llama3.2` | 2 GB | Default — fast, capable |
| `mistral` | 4 GB | Excellent instruction following |
| `qwen2.5` | 4–7 GB | Strong at coding and system tasks |
| `phi4-mini` | 2 GB | Very fast, low-resource systems |

Switch models at runtime: type `model mistral` inside the shell.

---

## License

MIT