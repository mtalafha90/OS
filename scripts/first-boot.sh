#!/usr/bin/env bash
# LLM-OS first-boot initialisation.
# Runs once on the first boot of a fresh installation.
set -euo pipefail

DONE_FLAG="/var/lib/llmos/.firstboot-done"
JOURNAL_TAG="llmos-firstboot"
DEFAULT_MODEL="${LLMOS_MODEL:-llama3.2}"

log()  { echo "[$JOURNAL_TAG] $*" | tee -a /var/log/llmos-firstboot.log; systemd-cat -t "$JOURNAL_TAG" echo "$*" 2>/dev/null || true; }
err()  { log "ERROR: $*"; exit 1; }

wait_for_network() {
    log "Waiting for network…"
    for i in $(seq 1 20); do
        if curl -sf --max-time 3 https://ollama.com &>/dev/null; then
            log "Network available."
            return
        fi
        sleep 3
    done
    err "No network after 60 seconds."
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
    log "Pulling default model: $DEFAULT_MODEL…"
    sudo -u ollama ollama pull "$DEFAULT_MODEL" || err "Failed to pull $DEFAULT_MODEL"
    log "Model $DEFAULT_MODEL pulled successfully."
}

enable_services() {
    systemctl enable --now ollama.service   || log "Warning: could not enable ollama"
    systemctl enable --now llmos.service    || log "Warning: could not enable llmos"
}

main() {
    log "=== LLM-OS First Boot ==="
    wait_for_network
    configure_llmos_user
    pull_default_model
    enable_services
    mkdir -p "$(dirname $DONE_FLAG)"
    touch "$DONE_FLAG"
    log "=== First boot setup complete. System ready. ==="
}

main "$@"
