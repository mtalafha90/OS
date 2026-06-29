#!/usr/bin/env bash
# LLM-OS first-boot initialisation.
# Runs once on the first boot of a fresh installation.
set -euo pipefail

DONE_FLAG="/var/lib/llmos/.firstboot-done"
JOURNAL_TAG="llmos-firstboot"
DEFAULT_MODEL="${LLMOS_MODEL:-$(cat /etc/llmos/default-model 2>/dev/null || echo llama3.2)}"

log()  { echo "[$JOURNAL_TAG] $*" | tee -a /var/log/llmos-firstboot.log; systemd-cat -t "$JOURNAL_TAG" echo "$*" 2>/dev/null || true; }
err()  { log "ERROR: $*"; exit 1; }

# Returns 0 if the default model is already available (e.g. bundled into the
# image at build time), so we can skip the network wait and download entirely.
model_present() {
    local base="${DEFAULT_MODEL%%:*}"
    # Fast path: manifest on disk (works before ollama serve is even ready).
    if ls /usr/share/ollama/.ollama/models/manifests/registry.ollama.ai/library/"$base"/* >/dev/null 2>&1; then
        return 0
    fi
    sudo -u ollama ollama list 2>/dev/null | grep -q "$base"
}

# Non-fatal network wait: returns 0 if online, 1 otherwise. An offline laptop
# with the model already bundled must still finish first boot cleanly.
wait_for_network() {
    log "Waiting for network…"
    for i in $(seq 1 20); do
        if curl -sf --max-time 3 https://ollama.com &>/dev/null; then
            log "Network available."
            return 0
        fi
        sleep 3
    done
    log "No network after 60 seconds (continuing — model may be bundled)."
    return 1
}

configure_llmos_user() {
    if ! id llmos &>/dev/null; then
        log "Creating llmos system user…"
        useradd -m -s /usr/local/bin/llmos -c "LLM-OS User" llmos
    fi
    mkdir -p /home/llmos/.config/llmos
    cp /etc/llmos/llmos.yaml /home/llmos/.config/llmos/config.yaml 2>/dev/null || true
    chown -R llmos:llmos /home/llmos/.config
}

pull_default_model() {
    if model_present; then
        log "Model $DEFAULT_MODEL already present (bundled) — skipping download."
        return 0
    fi
    log "Pulling default model: $DEFAULT_MODEL…"
    if sudo -u ollama ollama pull "$DEFAULT_MODEL"; then
        log "Model $DEFAULT_MODEL pulled successfully."
    else
        log "WARNING: could not pull $DEFAULT_MODEL (offline?). It will be pulled on demand from the UI later."
    fi
}

enable_services() {
    systemctl enable --now ollama.service   || log "Warning: could not enable ollama"
    systemctl enable --now llmos.service    || log "Warning: could not enable llmos"
}

install_gpu_drivers() {
    if [[ -x /usr/lib/llmos/install-gpu-drivers.sh ]]; then
        log "Detecting GPU and installing drivers…"
        bash /usr/lib/llmos/install-gpu-drivers.sh || log "WARNING: GPU driver installation failed — check /var/log/llmos-firstboot.log"
    fi
}

main() {
    log "=== LLM-OS First Boot ==="
    # Only block on the network if we actually need to download the model. With
    # the model bundled into the image, first boot completes offline.
    if model_present; then
        log "Default model is bundled — no network required for first boot."
    else
        wait_for_network || true
    fi
    install_gpu_drivers
    configure_llmos_user
    pull_default_model
    enable_services
    mkdir -p "$(dirname $DONE_FLAG)"
    touch "$DONE_FLAG"
    log "=== First boot setup complete. System ready. ==="
}

main "$@"
