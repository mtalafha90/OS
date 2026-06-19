#!/usr/bin/env bash
# Install Ollama and pull the default model.
set -euo pipefail

OLLAMA_MODEL="${1:-llama3.2}"
OLLAMA_INSTALL_URL="https://ollama.com/install.sh"

log() { echo "[llmos] $*"; }

require_root() {
    if [[ $EUID -ne 0 ]]; then
        echo "Error: this script must be run as root." >&2
        exit 1
    fi
}

install_ollama() {
    if command -v ollama &>/dev/null; then
        log "Ollama already installed: $(ollama --version)"
        return
    fi

    log "Downloading and installing Ollama…"
    curl -fsSL "$OLLAMA_INSTALL_URL" | sh

    # Create ollama system user if it doesn't exist
    if ! id ollama &>/dev/null; then
        useradd -r -s /bin/false -d /usr/share/ollama ollama
        mkdir -p /usr/share/ollama
        chown ollama:ollama /usr/share/ollama
    fi

    log "Ollama installed: $(ollama --version)"
}

start_ollama() {
    if systemctl is-active --quiet ollama 2>/dev/null; then
        log "Ollama service already running."
        return
    fi

    # Copy our custom service file if available
    if [[ -f /usr/lib/llmos/systemd/ollama.service ]]; then
        cp /usr/lib/llmos/systemd/ollama.service /etc/systemd/system/ollama.service
        systemctl daemon-reload
    fi

    systemctl enable ollama
    systemctl start ollama

    log "Waiting for Ollama to become ready…"
    for i in $(seq 1 30); do
        if curl -sf http://localhost:11434/api/tags &>/dev/null; then
            log "Ollama is ready."
            return
        fi
        sleep 2
    done
    echo "Error: Ollama did not start in time." >&2
    exit 1
}

pull_model() {
    local model="$1"
    log "Pulling model '${model}'…"
    # Run as ollama user so models land in the right place
    sudo -u ollama ollama pull "${model}"
    log "Model '${model}' ready."
}

main() {
    require_root
    install_ollama
    start_ollama
    pull_model "$OLLAMA_MODEL"
    log "Ollama setup complete."
}

main "$@"
