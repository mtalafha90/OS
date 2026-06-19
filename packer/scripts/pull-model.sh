#!/usr/bin/env bash
# Pre-pull the default Ollama model into the VM image.
# This makes first-boot instant at the cost of a larger image (~2 GB).
# Set SKIP_MODEL_PULL=1 to skip this step and pull on first boot instead.
set -euo pipefail

LLMOS_MODEL="${LLMOS_MODEL:-llama3.2}"

if [[ "${SKIP_MODEL_PULL:-0}" == "1" ]]; then
    echo "[pull-model] Skipping model pull (SKIP_MODEL_PULL=1). Model will be pulled on first boot."
    exit 0
fi

echo "[pull-model] Starting Ollama to pull $LLMOS_MODEL…"

# Start Ollama as the ollama user in background
sudo -u ollama OLLAMA_MODELS=/usr/share/ollama/.ollama/models ollama serve &>/tmp/ollama-pull.log &
OLLAMA_PID=$!

# Wait for Ollama to be ready
for i in $(seq 1 30); do
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        echo "[pull-model] Ollama ready."
        break
    fi
    echo "[pull-model] Waiting for Ollama ($i/30)…"
    sleep 3
done

# Pull the model
echo "[pull-model] Pulling $LLMOS_MODEL (this may take several minutes)…"
sudo -u ollama OLLAMA_MODELS=/usr/share/ollama/.ollama/models ollama pull "$LLMOS_MODEL"
echo "[pull-model] Model $LLMOS_MODEL pulled successfully."

# Mark first-boot done (so the service doesn't re-pull)
mkdir -p /var/lib/llmos
touch /var/lib/llmos/.firstboot-done

# Stop Ollama
kill "$OLLAMA_PID" 2>/dev/null || true
wait "$OLLAMA_PID" 2>/dev/null || true
echo "[pull-model] Done."
