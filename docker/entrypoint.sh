#!/usr/bin/env bash
set -euo pipefail

WITH_OLLAMA=false
for arg in "$@"; do
    [[ "$arg" == "--with-ollama" ]] && WITH_OLLAMA=true
done

if [[ "$WITH_OLLAMA" == "true" ]]; then
    echo "[entrypoint] Starting bundled Ollama server…"
    curl -fsSL https://ollama.com/install.sh | sh &>/dev/null
    ollama serve &>/var/log/ollama.log &
    OLLAMA_PID=$!

    echo "[entrypoint] Waiting for Ollama…"
    for i in $(seq 1 20); do
        curl -sf http://localhost:11434/api/tags &>/dev/null && break
        sleep 2
    done

    echo "[entrypoint] Pulling ${LLMOS_MODEL}…"
    ollama pull "${LLMOS_MODEL}" || true

    export OLLAMA_URL="http://localhost:11434"
fi

exec llmos --ollama-url "${OLLAMA_URL:-http://localhost:11434}" "$@"
