# LLM-OS Packer variable overrides.
# Usage:  packer build -var-file=variables.pkrvars.hcl llmos.pkr.hcl
#
# To find the latest Ubuntu ISO URL + SHA256:
#   https://releases.ubuntu.com/24.04/
#   https://releases.ubuntu.com/24.04/SHA256SUMS

# ── ISO source ────────────────────────────────────────────────────────────────
# Ubuntu 24.04.2 LTS (Noble Numbat) — server install image
ubuntu_iso_url      = "https://releases.ubuntu.com/24.04.2/ubuntu-24.04.2-live-server-amd64.iso"
ubuntu_iso_checksum = "sha256:d6dab0c3a657988501b4bd76f1297c053df710e06e0c3aece60dead24f270b4d"

# ── Ollama model ──────────────────────────────────────────────────────────────
# Pre-pulled into the image at build time (~2 GB for llama3.2).
# Other options: llama3.1, mistral, phi3, gemma2, qwen2.5
ollama_model = "llama3.2"

# ── VM resources ─────────────────────────────────────────────────────────────
# Minimum for comfortable use: 4 GB RAM, 2 CPUs, 20 GB disk.
# For large models (70B+): 64+ GB RAM recommended.
memory_mb    = 4096
cpus         = 2
disk_size_mb = 20480

# ── Output directory ─────────────────────────────────────────────────────────
# Relative to the packer/ directory.  Created automatically.
output_dir = "../dist"
