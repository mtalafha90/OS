#!/usr/bin/env bash
# Build the LLM-OS live ISO using live-build (Debian/Ubuntu).
#
# Requirements (install on build host):
#   sudo apt-get install live-build squashfs-tools xorriso isolinux syslinux-efi
#
# Usage:
#   sudo ./build/build-iso.sh [OUTPUT_DIR]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="${1:-$REPO_DIR/dist}"
BUILD_DIR="$REPO_DIR/.build"
DIST="noble"          # Ubuntu 24.04 LTS
ARCH="amd64"
ISO_NAME="llmos-1.0.0-${ARCH}.iso"
DEFAULT_MODEL="llama3.2"

log() { echo -e "\033[1;36m[build-iso]\033[0m $*"; }
err() { echo -e "\033[1;31m[build-iso ERROR]\033[0m $*" >&2; exit 1; }

require_root() {
    [[ $EUID -eq 0 ]] || err "ISO build must run as root. Use: sudo $0"
}

check_deps() {
    log "Checking build dependencies…"
    local missing=()
    for cmd in lb debootstrap mksquashfs xorriso; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Missing tools: ${missing[*]}
Install with:
  apt-get install live-build squashfs-tools xorriso isolinux syslinux-efi"
    fi
}

init_build() {
    log "Initialising live-build workspace in $BUILD_DIR…"
    rm -rf "$BUILD_DIR"
    mkdir -p "$BUILD_DIR"
    cd "$BUILD_DIR"

    lb config \
        --distribution "$DIST" \
        --architectures "$ARCH" \
        --archive-areas "main restricted universe multiverse" \
        --mirror-bootstrap "http://archive.ubuntu.com/ubuntu/" \
        --mirror-chroot "http://archive.ubuntu.com/ubuntu/" \
        --apt-indices false \
        --apt-source-archives false \
        --bootappend-live "boot=live components quiet splash" \
        --iso-application "LLM-OS" \
        --iso-publisher "LLM-OS Project" \
        --iso-volume "LLMOS_1_0" \
        --linux-packages "linux-image-generic linux-headers-generic"
}

write_package_list() {
    log "Writing package lists…"
    mkdir -p "$BUILD_DIR/config/package-lists"
    cat > "$BUILD_DIR/config/package-lists/llmos.list.chroot" << 'EOF'
# Base system
python3
python3-pip
python3-venv
curl
wget
git
# Network tools
net-tools
iputils-ping
iputils-tracepath
dnsutils
iproute2
nmap
# System monitoring
htop
iotop
lsof
sysstat
# Editors / utilities
nano
vim
less
jq
tree
unzip
# Hardware support
pciutils
usbutils
EOF
}

copy_overlay() {
    log "Copying LLM-OS overlay to chroot includes…"
    local overlay="$BUILD_DIR/config/includes.chroot"
    mkdir -p "$overlay/etc/llmos"
    mkdir -p "$overlay/usr/lib/llmos/systemd"
    mkdir -p "$overlay/etc/systemd/system"

    # Config
    cp "$REPO_DIR/config/llmos.yaml" "$overlay/etc/llmos/llmos.yaml"

    # Scripts
    mkdir -p "$overlay/usr/lib/llmos"
    cp "$REPO_DIR/scripts/first-boot.sh" "$overlay/usr/lib/llmos/"
    chmod +x "$overlay/usr/lib/llmos/first-boot.sh"

    # Systemd units
    cp "$REPO_DIR/systemd/"*.service "$overlay/etc/systemd/system/"

    # MOTD
    mkdir -p "$overlay/etc/update-motd.d"
    cat > "$overlay/etc/update-motd.d/10-llmos" << 'MOTD'
#!/bin/sh
echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║          L L M - O S            ║"
echo "  ║  Natural Language Operating System  ║"
echo "  ╚══════════════════════════════════╝"
echo ""
echo "  Type in plain English. The LLM does the rest."
echo "  Commands: exit  |  models  |  history clear"
echo ""
MOTD
    chmod +x "$overlay/etc/update-motd.d/10-llmos"

    # Disable getty on tty1 and replace with llmos
    mkdir -p "$overlay/etc/systemd/system/getty@tty1.service.d"
    cat > "$overlay/etc/systemd/system/getty@tty1.service.d/override.conf" << 'GETTY'
[Service]
ExecStart=
ExecStart=-/usr/local/bin/llmos
GETTY
}

write_chroot_hooks() {
    log "Writing chroot hooks…"
    local hooks="$BUILD_DIR/config/hooks/normal"
    mkdir -p "$hooks"

    # Hook: install Ollama
    cat > "$hooks/0050-install-ollama.hook.chroot" << 'HOOK'
#!/bin/bash
set -euo pipefail
echo "[hook] Installing Ollama…"
curl -fsSL https://ollama.com/install.sh | OLLAMA_MODELS=/usr/share/ollama/.ollama/models sh
useradd -r -s /bin/false -d /usr/share/ollama ollama 2>/dev/null || true
mkdir -p /usr/share/ollama/.ollama/models
chown -R ollama:ollama /usr/share/ollama
echo "[hook] Ollama installed."
HOOK
    chmod +x "$hooks/0050-install-ollama.hook.chroot"

    # Hook: install LLM-OS Python package
    cat > "$hooks/0060-install-llmos.hook.chroot" << HOOK
#!/bin/bash
set -euo pipefail
echo "[hook] Installing LLM-OS Python package…"
pip3 install --break-system-packages \
    httpx>=0.27 rich>=13.7 prompt_toolkit>=3.0 pyyaml>=6.0 psutil>=5.9
# Install from local copy baked into the ISO
pip3 install --break-system-packages /usr/lib/llmos/llmos-src/ || true
echo "[hook] LLM-OS installed."
HOOK
    chmod +x "$hooks/0060-install-llmos.hook.chroot"

    # Hook: enable services
    cat > "$hooks/0070-enable-services.hook.chroot" << 'HOOK'
#!/bin/bash
set -euo pipefail
echo "[hook] Enabling services…"
systemctl enable ollama.service         || true
systemctl enable llmos-firstboot.service || true
systemctl disable getty@tty1.service    || true
echo "[hook] Services configured."
HOOK
    chmod +x "$hooks/0070-enable-services.hook.chroot"
}

copy_llmos_source() {
    log "Copying LLM-OS source into chroot overlay…"
    local src_dest="$BUILD_DIR/config/includes.chroot/usr/lib/llmos/llmos-src"
    mkdir -p "$src_dest"
    cp -r "$REPO_DIR/llmos" "$src_dest/"
    cp "$REPO_DIR/pyproject.toml" "$src_dest/"
    cp "$REPO_DIR/requirements.txt" "$src_dest/"
}

build_iso() {
    log "Starting live-build (this will take 15-30 minutes)…"
    cd "$BUILD_DIR"
    lb build 2>&1 | tee "$REPO_DIR/build.log"

    mkdir -p "$OUTPUT_DIR"
    if [[ -f "$BUILD_DIR/live-image-${ARCH}.hybrid.iso" ]]; then
        mv "$BUILD_DIR/live-image-${ARCH}.hybrid.iso" "$OUTPUT_DIR/$ISO_NAME"
        log "ISO built: $OUTPUT_DIR/$ISO_NAME"
        ls -lh "$OUTPUT_DIR/$ISO_NAME"
    else
        err "ISO not found. Check $REPO_DIR/build.log for errors."
    fi
}

main() {
    require_root
    check_deps
    init_build
    write_package_list
    copy_overlay
    copy_llmos_source
    write_chroot_hooks
    build_iso

    echo
    echo "=============================="
    echo "  LLM-OS ISO build complete!"
    echo "=============================="
    echo
    echo "  ISO:    $OUTPUT_DIR/$ISO_NAME"
    echo
    echo "  Flash to USB:"
    echo "    sudo dd if=$OUTPUT_DIR/$ISO_NAME of=/dev/sdX bs=4M status=progress"
    echo "  Or test in QEMU:"
    echo "    qemu-system-x86_64 -m 4G -cdrom $OUTPUT_DIR/$ISO_NAME -enable-kvm"
    echo
    echo "  Note: First boot will pull the '$DEFAULT_MODEL' model (~2GB)."
    echo "        Ensure the machine has internet access on first boot."
    echo
}

main "$@"
