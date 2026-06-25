#!/usr/bin/env bash
# LLM-OS VM provisioner — runs as root inside the new VM via Packer.
set -euo pipefail

LLMOS_MODEL="${LLMOS_MODEL:-llama3.2}"
SRC="/tmp/llmos-src"
LOG="/var/log/llmos-provision.log"

log() { echo "[$(date +%T)] $*" | tee -a "$LOG"; }
err() { log "ERROR: $*"; exit 1; }

log "=== LLM-OS Provisioner starting ==="
log "Model: $LLMOS_MODEL"

# ── System update ─────────────────────────────────────────────────────────────
log "Updating system packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq

# ── Additional packages ───────────────────────────────────────────────────────
log "Installing dependencies…"
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    curl wget git \
    net-tools iputils-ping iproute2 dnsutils \
    htop iotop lsof nano vim less \
    jq tree unzip \
    pciutils usbutils \
    2>/dev/null

# ── Ollama ────────────────────────────────────────────────────────────────────
log "Installing Ollama…"
curl -fsSL https://ollama.com/install.sh | OLLAMA_MODELS=/usr/share/ollama/.ollama/models sh

# Create dedicated ollama system user
if ! id ollama &>/dev/null; then
    useradd -r -s /bin/false -d /usr/share/ollama ollama
fi
mkdir -p /usr/share/ollama/.ollama/models
chown -R ollama:ollama /usr/share/ollama

# ── LLM-OS Python package ─────────────────────────────────────────────────────
log "Installing LLM-OS…"
# Copy source to final location
mkdir -p /opt/llmos
cp -r "$SRC"/llmos "$SRC"/pyproject.toml "$SRC"/requirements.txt /opt/llmos/ 2>/dev/null || true
pip3 install --break-system-packages /opt/llmos/

# Verify installation
llmos --help &>/dev/null && log "llmos CLI installed OK" || err "llmos CLI not found after install"

# ── System configuration ──────────────────────────────────────────────────────
log "Configuring system…"

# Create llmos system directories
mkdir -p /etc/llmos /var/lib/llmos /usr/lib/llmos

# Install default config
cp "$SRC"/config/llmos.yaml /etc/llmos/llmos.yaml 2>/dev/null || true

# Install scripts
cp "$SRC"/scripts/first-boot.sh /usr/lib/llmos/ 2>/dev/null && chmod +x /usr/lib/llmos/first-boot.sh || true

# Install systemd services
cp "$SRC"/systemd/*.service /etc/systemd/system/ 2>/dev/null || true
systemctl daemon-reload

# Enable services
systemctl enable ollama.service
systemctl enable llmos-web.service
systemctl enable llmos-firstboot.service

# ── User shell configuration ──────────────────────────────────────────────────
log "Configuring llmos user…"
HOME_LLMOS="/home/llmos"
mkdir -p "$HOME_LLMOS/.config/llmos"
cp /etc/llmos/llmos.yaml "$HOME_LLMOS/.config/llmos/config.yaml"
chown -R llmos:llmos "$HOME_LLMOS/.config"

# Shell config for the llmos user
cat > "$HOME_LLMOS/.bashrc" << 'BASHRC'
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
export LLMOS_MODEL="${LLMOS_MODEL:-llama3.2}"

if [[ $- == *i* ]]; then
    echo ""
    echo "  ╔══════════════════════════════════════╗"
    echo "  ║           L L M - O S               ║"
    echo "  ║   Natural Language Operating System  ║"
    echo "  ╚══════════════════════════════════════╝"
    echo ""
    IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    echo "  Web UI:  http://${IP:-localhost}:8080"
    echo "  Password: llmos  (change with: passwd)"
    echo ""
fi
BASHRC
chown llmos:llmos "$HOME_LLMOS/.bashrc"

# Set llmos user's default shell to bash (not /bin/sh)
chsh -s /bin/bash llmos

# ── MOTD ──────────────────────────────────────────────────────────────────────
cat > /etc/motd << 'MOTD'

  ╔═══════════════════════════════════════════════╗
  ║              L L M - O S                     ║
  ║      Natural Language Operating System        ║
  ╠═══════════════════════════════════════════════╣
  ║  Default credentials:  llmos / llmos          ║
  ║  Web UI:  http://<vm-ip>:8080                 ║
  ║  Terminal: llmos                              ║
  ║  Change password: passwd                      ║
  ╚═══════════════════════════════════════════════╝

MOTD

# Disable default Ubuntu MOTD spam
chmod -x /etc/update-motd.d/10-help-text 2>/dev/null || true
chmod -x /etc/update-motd.d/50-motd-news 2>/dev/null || true

# ── Firewall: allow web UI port ───────────────────────────────────────────────
if command -v ufw &>/dev/null; then
    ufw allow 22/tcp  comment "SSH"
    ufw allow 8080/tcp comment "LLM-OS Web UI"
fi

log "=== Provisioning complete ==="
log "Model will be pulled on first boot via llmos-firstboot.service"
