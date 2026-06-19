#!/usr/bin/env bash
# Install LLM-OS on an existing Ubuntu/Debian system.
set -euo pipefail

LLMOS_MODEL="${LLMOS_MODEL:-llama3.2}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_PREFIX="/usr/local"
LIB_DIR="/usr/lib/llmos"
ETC_DIR="/etc/llmos"
VAR_DIR="/var/lib/llmos"

log()  { echo -e "\033[1;36m[llmos-install]\033[0m $*"; }
ok()   { echo -e "\033[1;32m  ✓\033[0m $*"; }
err()  { echo -e "\033[1;31m  ✗\033[0m $*" >&2; exit 1; }

require_root() {
    [[ $EUID -eq 0 ]] || err "Run as root: sudo $0"
}

check_os() {
    if ! command -v apt-get &>/dev/null; then
        err "This installer requires a Debian/Ubuntu system (apt-get not found)."
    fi
    log "Detected Debian/Ubuntu system."
}

install_dependencies() {
    log "Installing system dependencies…"
    apt-get update -qq
    apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        curl wget git \
        net-tools iputils-ping dnsutils \
        systemd \
        2>/dev/null
    ok "System dependencies installed."
}

install_python_package() {
    log "Installing LLM-OS Python package…"
    pip3 install --quiet --break-system-packages "$REPO_DIR"
    ok "llmos installed to $(which llmos 2>/dev/null || echo $INSTALL_PREFIX/bin/llmos)"
}

install_config() {
    log "Installing configuration…"
    mkdir -p "$ETC_DIR" "$LIB_DIR" "$VAR_DIR"
    cp "$REPO_DIR/config/llmos.yaml" "$ETC_DIR/llmos.yaml"
    # Install scripts
    cp "$REPO_DIR/scripts/first-boot.sh" "$LIB_DIR/first-boot.sh"
    chmod +x "$LIB_DIR/first-boot.sh"
    ok "Configuration installed to $ETC_DIR"
}

install_systemd_services() {
    log "Installing systemd services…"
    local svc_dir="$LIB_DIR/systemd"
    mkdir -p "$svc_dir"
    cp "$REPO_DIR/systemd/"*.service "$svc_dir/"
    # Install to systemd
    cp "$REPO_DIR/systemd/ollama.service" /etc/systemd/system/ollama.service
    cp "$REPO_DIR/systemd/llmos-firstboot.service" /etc/systemd/system/llmos-firstboot.service
    systemctl daemon-reload
    ok "Systemd services installed."
}

setup_ollama() {
    log "Setting up Ollama…"
    bash "$REPO_DIR/scripts/setup-ollama.sh" "$LLMOS_MODEL"
}

print_summary() {
    echo
    echo "=============================="
    echo "  LLM-OS installation complete"
    echo "=============================="
    echo
    echo "  Run interactively:   llmos"
    echo "  Single command:      llmos --cmd 'list files in /home'"
    echo "  Change model:        llmos --model mistral"
    echo "  Config file:         $ETC_DIR/llmos.yaml"
    echo
    echo "  Systemd services:"
    echo "    ollama.service       — LLM inference server"
    echo "    llmos.service        — Auto-start shell on tty1"
    echo "    llmos-firstboot.service — First-boot model download"
    echo
}

main() {
    require_root
    check_os
    install_dependencies
    install_python_package
    install_config
    install_systemd_services
    setup_ollama
    print_summary
}

main "$@"
