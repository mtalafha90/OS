#!/usr/bin/env bash
# LLM-OS kiosk launcher: wait for the web server, then open browser fullscreen.
set -euo pipefail

URL="http://localhost:8080"
MAX_WAIT=180
WAIT=0

# Disable screen blanking and power management
xset s off s noblank dpms 0 0 0 2>/dev/null || true

# Hide mouse cursor when idle
command -v unclutter &>/dev/null && unclutter -idle 3 -root &

# Wait for LLM-OS web server
echo "[kiosk] Waiting for LLM-OS at $URL …"
while ! curl -sf --max-time 2 "$URL" >/dev/null 2>&1; do
    sleep 3
    WAIT=$((WAIT + 3))
    if [[ $WAIT -ge $MAX_WAIT ]]; then
        echo "[kiosk] Server not ready after ${MAX_WAIT}s — opening anyway"
        break
    fi
done
echo "[kiosk] Server ready. Launching browser."

# Try Firefox first, fall back to Chromium
if command -v firefox &>/dev/null; then
    exec firefox \
        --kiosk \
        --no-remote \
        --disable-pinch \
        "$URL"
elif command -v chromium-browser &>/dev/null; then
    exec chromium-browser \
        --kiosk \
        --no-sandbox \
        --disable-infobars \
        --disable-session-crashed-bubble \
        --disable-restore-session-state \
        --noerrdialogs \
        --disable-translate \
        --disable-features=TranslateUI \
        --check-for-update-interval=31536000 \
        "$URL"
elif command -v chromium &>/dev/null; then
    exec chromium \
        --kiosk \
        --no-sandbox \
        --disable-infobars \
        --disable-session-crashed-bubble \
        --disable-restore-session-state \
        --noerrdialogs \
        "$URL"
else
    echo "[kiosk] No browser found. Install firefox or chromium-browser."
    exit 1
fi
