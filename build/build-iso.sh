#!/usr/bin/env bash
# Build the LLM-OS live ISO using live-build (Debian/Ubuntu).
#
# Two modes:
#   kiosk  (default) — X11 + Firefox/Chromium kiosk, boots straight to web UI
#   server            — text-only, smaller ISO; access web UI from host browser
#
# Requirements (install with: make iso-deps):
#   sudo apt-get install live-build squashfs-tools xorriso isolinux syslinux-efi
#
# Usage:
#   sudo bash build/build-iso.sh [OUTPUT_DIR] [kiosk|server]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="${1:-$REPO_DIR/dist}"
MODE="${2:-kiosk}"        # kiosk | server
# Build dir must be on a filesystem mounted with dev+exec (not an external drive).
# Override with: sudo LLMOS_BUILD_DIR=/tmp/llmos-build bash build/build-iso.sh
BUILD_DIR="${LLMOS_BUILD_DIR:-/tmp/llmos-build}"
DIST="noble"              # Ubuntu 24.04 LTS
ARCH="amd64"
VERSION="1.0.0"
ISO_NAME="llmos-${VERSION}-${ARCH}-${MODE}.iso"
DEFAULT_MODEL="${LLMOS_MODEL:-llama3.2}"

log()  { echo -e "\033[1;36m[build-iso]\033[0m $*"; }
ok()   { echo -e "\033[1;32m[build-iso]\033[0m ✓ $*"; }
err()  { echo -e "\033[1;31m[build-iso ERROR]\033[0m $*" >&2; exit 1; }
warn() { echo -e "\033[1;33m[build-iso]\033[0m ⚠ $*"; }

require_root() {
    [[ $EUID -eq 0 ]] || err "ISO build must run as root. Use: sudo bash $0"
}

check_deps() {
    log "Checking build dependencies…"
    local missing=()
    for cmd in lb debootstrap mksquashfs xorriso; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Missing tools: ${missing[*]}
Run:  sudo apt-get install live-build squashfs-tools xorriso isolinux syslinux-efi"
    fi
    ok "Build dependencies present."
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
        --iso-volume "LLMOS_1_0"

    # Use GRUB only — syslinux theme packages were dropped from Ubuntu 24.04.
    # Write to the generated config file directly; --bootloaders is not
    # recognised in all live-build versions.
    local binary_cfg="$BUILD_DIR/config/binary"
    if grep -q "^LB_BOOTLOADERS=" "$binary_cfg" 2>/dev/null; then
        sed -i 's/^LB_BOOTLOADERS=.*/LB_BOOTLOADERS="grub-pc grub-efi-amd64"/' "$binary_cfg"
    else
        echo 'LB_BOOTLOADERS="grub-pc grub-efi-amd64"' >> "$binary_cfg"
    fi
    ok "Bootloaders set to grub-pc + grub-efi-amd64."
}

write_package_list() {
    log "Writing package lists (mode: $MODE)…"
    mkdir -p "$BUILD_DIR/config/package-lists"

    # Base packages for all modes
    cat > "$BUILD_DIR/config/package-lists/llmos-base.list.chroot" << 'EOF'
python3
python3-pip
python3-venv
curl
wget
git
net-tools
iputils-ping
iputils-tracepath
dnsutils
iproute2
nmap
htop
iotop
lsof
sysstat
nano
vim
less
jq
tree
unzip
pciutils
usbutils
ca-certificates
gnupg
EOF

    # Kiosk-specific packages (X11 + browser)
    if [[ "$MODE" == "kiosk" ]]; then
        cat > "$BUILD_DIR/config/package-lists/llmos-kiosk.list.chroot" << 'EOF'
xorg
openbox
x11-xserver-utils
x11-utils
xdotool
unclutter
fonts-ubuntu
fonts-noto
fonts-noto-color-emoji
EOF
    fi
}

write_firefox_pin() {
    # Prioritise the Mozilla team PPA so apt-get installs the real deb, not a snap stub
    if [[ "$MODE" == "kiosk" ]]; then
        mkdir -p "$BUILD_DIR/config/includes.chroot/etc/apt/preferences.d"
        cat > "$BUILD_DIR/config/includes.chroot/etc/apt/preferences.d/mozilla-firefox" << 'EOF'
Package: firefox*
Pin: release o=LP-PPA-mozillateam
Pin-Priority: 1001
EOF
    fi
}

copy_overlay() {
    log "Copying LLM-OS overlay to chroot…"
    local overlay="$BUILD_DIR/config/includes.chroot"
    mkdir -p "$overlay/etc/llmos"
    mkdir -p "$overlay/etc/systemd/system"
    mkdir -p "$overlay/usr/lib/llmos"

    # Default config
    cp "$REPO_DIR/config/llmos.yaml" "$overlay/etc/llmos/llmos.yaml"

    # Scripts
    cp "$REPO_DIR/scripts/first-boot.sh" "$overlay/usr/lib/llmos/first-boot.sh"
    chmod +x "$overlay/usr/lib/llmos/first-boot.sh"

    if [[ "$MODE" == "kiosk" ]]; then
        cp "$REPO_DIR/scripts/kiosk-start.sh" "$overlay/usr/lib/llmos/kiosk-start.sh"
        chmod +x "$overlay/usr/lib/llmos/kiosk-start.sh"
    fi

    # Systemd units
    cp "$REPO_DIR/systemd/ollama.service"           "$overlay/etc/systemd/system/"
    cp "$REPO_DIR/systemd/llmos-firstboot.service"  "$overlay/etc/systemd/system/"
    cp "$REPO_DIR/systemd/llmos-web.service"        "$overlay/etc/systemd/system/"

    # Auto-login on tty1 (passwordless for llmos user — the web UI has its own lock screen)
    mkdir -p "$overlay/etc/systemd/system/getty@tty1.service.d"
    cat > "$overlay/etc/systemd/system/getty@tty1.service.d/autologin.conf" << 'GETTY'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin llmos --noclear %I $TERM
GETTY

    # llmos user home skeleton
    local skel="$overlay/etc/skel-llmos"
    mkdir -p "$skel"

    if [[ "$MODE" == "kiosk" ]]; then
        # .xinitrc: minimal WM + kiosk
        cat > "$skel/.xinitrc" << 'XINITRC'
#!/bin/bash
openbox &
exec /usr/lib/llmos/kiosk-start.sh
XINITRC
        chmod +x "$skel/.xinitrc"

        # .bash_profile: auto-start X on tty1 login
        cat > "$skel/.bash_profile" << 'BASHPROFILE'
[[ -f ~/.bashrc ]] && . ~/.bashrc
if [[ -z "${DISPLAY:-}" && "$(tty)" == /dev/tty1 ]]; then
    exec startx ~/.xinitrc -- :0 vt1 2>/tmp/startx.log
fi
BASHPROFILE
    fi

    # .bashrc: MOTD + web UI fallback for server mode
    cat > "$skel/.bashrc" << 'BASHRC'
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
    echo "  Web UI: http://${IP:-localhost}:8080"
    echo "  Default password: llmos"
    echo ""
fi
BASHRC

    # MOTD
    mkdir -p "$overlay/etc/update-motd.d"
    cat > "$overlay/etc/update-motd.d/10-llmos" << 'MOTD'
#!/bin/sh
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║             L L M - O S                     ║"
echo "  ║     Natural Language Operating System        ║"
echo "  ╠══════════════════════════════════════════════╣"
echo "  ║  Credentials:  llmos / llmos                 ║"
echo "  ║  Web UI:       http://${IP:-<vm-ip>}:8080    ║"
echo "  ║  Change pass:  passwd                        ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""
MOTD
    chmod +x "$overlay/etc/update-motd.d/10-llmos"
}

copy_llmos_source() {
    log "Copying LLM-OS source into chroot overlay…"
    local dest="$BUILD_DIR/config/includes.chroot/usr/lib/llmos/llmos-src"
    mkdir -p "$dest"
    cp -r "$REPO_DIR/llmos" "$dest/"
    cp "$REPO_DIR/pyproject.toml" "$dest/"
    [[ -f "$REPO_DIR/requirements.txt" ]] && cp "$REPO_DIR/requirements.txt" "$dest/" || true
}

write_chroot_hooks() {
    log "Writing chroot hooks…"
    local hooks="$BUILD_DIR/config/hooks/normal"
    mkdir -p "$hooks"

    # Hook 0050: Install Ollama
    cat > "$hooks/0050-install-ollama.hook.chroot" << 'HOOK'
#!/bin/bash
set -euo pipefail
echo "[hook] Installing Ollama…"
curl -fsSL https://ollama.com/install.sh | OLLAMA_MODELS=/usr/share/ollama/.ollama/models sh
id ollama &>/dev/null || useradd -r -s /bin/false -d /usr/share/ollama ollama
mkdir -p /usr/share/ollama/.ollama/models
chown -R ollama:ollama /usr/share/ollama
echo "[hook] Ollama OK."
HOOK
    chmod +x "$hooks/0050-install-ollama.hook.chroot"

    # Hook 0055: Install Firefox via Mozilla PPA (kiosk mode only)
    if [[ "$MODE" == "kiosk" ]]; then
        cat > "$hooks/0055-install-firefox.hook.chroot" << 'HOOK'
#!/bin/bash
set -euo pipefail
echo "[hook] Installing Firefox via Mozilla PPA…"
add-apt-repository -y ppa:mozillateam/ppa
apt-get update -qq
apt-get install -y --no-install-recommends firefox
# Remove snap stub if it exists
apt-get remove -y firefox-snap 2>/dev/null || true
echo "[hook] Firefox OK."
HOOK
        chmod +x "$hooks/0055-install-firefox.hook.chroot"
    fi

    # Hook 0060: Install LLM-OS Python package
    cat > "$hooks/0060-install-llmos.hook.chroot" << 'HOOK'
#!/bin/bash
set -euo pipefail
echo "[hook] Installing LLM-OS…"
pip3 install --break-system-packages \
    httpx>=0.27 rich>=13.7 prompt_toolkit>=3.0 pyyaml>=6.0 psutil>=5.9 \
    fastapi>=0.111 uvicorn[standard]>=0.29 websockets>=12.0
pip3 install --break-system-packages /usr/lib/llmos/llmos-src/ || \
    pip3 install --break-system-packages \
        httpx rich prompt_toolkit pyyaml psutil fastapi uvicorn websockets
echo "[hook] LLM-OS OK."
HOOK
    chmod +x "$hooks/0060-install-llmos.hook.chroot"

    # Hook 0065: Create llmos user and set up home directory
    cat > "$hooks/0065-create-user.hook.chroot" << 'HOOK'
#!/bin/bash
set -euo pipefail
echo "[hook] Creating llmos user…"
if ! id llmos &>/dev/null; then
    useradd -m -s /bin/bash -G sudo,audio,video,plugdev llmos
fi
echo "llmos:llmos" | chpasswd
HOME_DIR="/home/llmos"

# Apply skeleton files
if [[ -d /etc/skel-llmos ]]; then
    cp -rn /etc/skel-llmos/. "$HOME_DIR/"
fi

chown -R llmos:llmos "$HOME_DIR"
echo "[hook] User llmos ready."
HOOK
    chmod +x "$hooks/0065-create-user.hook.chroot"

    # Hook 0070: Enable systemd services
    cat > "$hooks/0070-enable-services.hook.chroot" << 'HOOK'
#!/bin/bash
set -euo pipefail
echo "[hook] Enabling services…"
systemctl enable ollama.service          || true
systemctl enable llmos-web.service       || true
systemctl enable llmos-firstboot.service || true
# Disable default getty@tty1 override (replaced by autologin)
systemctl enable getty@tty1.service      || true
# Suppress noisy MOTD entries
chmod -x /etc/update-motd.d/10-help-text 2>/dev/null || true
chmod -x /etc/update-motd.d/50-motd-news 2>/dev/null || true
echo "[hook] Services enabled."
HOOK
    chmod +x "$hooks/0070-enable-services.hook.chroot"
}

build_iso() {
    log "Starting live-build (this takes 15–40 minutes)…"
    cd "$BUILD_DIR"
    lb build 2>&1 | tee "$REPO_DIR/build-iso.log"

    mkdir -p "$OUTPUT_DIR"
    local iso_src="$BUILD_DIR/live-image-${ARCH}.hybrid.iso"
    if [[ -f "$iso_src" ]]; then
        mv "$iso_src" "$OUTPUT_DIR/$ISO_NAME"
        ok "ISO built: $OUTPUT_DIR/$ISO_NAME ($(du -sh "$OUTPUT_DIR/$ISO_NAME" | cut -f1))"
    else
        err "ISO not found after build. Check $REPO_DIR/build-iso.log"
    fi
}

print_summary() {
    local iso="$OUTPUT_DIR/$ISO_NAME"
    echo
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║            LLM-OS ISO Build Complete!                   ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo
    echo "  ISO:  $iso"
    [[ -f "$iso" ]] && echo "  Size: $(du -sh "$iso" | cut -f1)"
    echo
    echo "  ── VirtualBox ─────────────────────────────────────────"
    echo "  1. File → New → Name: LLM-OS, Type: Linux, Version: Ubuntu 64-bit"
    echo "  2. RAM: 4096 MB+, CPU: 2+ cores"
    echo "  3. Storage → Add → choose $ISO_NAME"
    echo "  4. Start VM"
    echo
    echo "  ── QEMU/KVM ───────────────────────────────────────────"
    echo "  qemu-system-x86_64 \\"
    echo "    -m 4G -smp 2 \\"
    echo "    -cdrom $iso \\"
    echo "    -net nic -net user,hostfwd=tcp::8080-:8080 \\"
    echo "    -enable-kvm -display sdl"
    echo
    if [[ "$MODE" == "kiosk" ]]; then
        echo "  ── Kiosk Mode ─────────────────────────────────────────"
        echo "  The VM boots directly to the LLM-OS web UI."
        echo "  Default lock screen password: llmos"
    else
        echo "  ── Server Mode ────────────────────────────────────────"
        echo "  Open http://localhost:8080 in your browser after boot."
    fi
    echo
    echo "  Note: First boot pulls model '$DEFAULT_MODEL' (~2 GB)."
    echo "        Ensure internet access on first boot."
    echo
}

patch_livebuild_syslinux() {
    # Ubuntu 24.04 dropped syslinux-themes-ubuntu-oneiric and gfxboot-theme-ubuntu.
    # live-build's lb_binary_syslinux script still tries to install them and fails.
    # Patch the script in-place (build already requires root) to skip those packages.
    local script="/usr/lib/live/build/lb_binary_syslinux"
    [[ -f "$script" ]] || return 0
    if grep -q "syslinux-themes-ubuntu\|gfxboot-theme-ubuntu" "$script"; then
        cp "$script" "${script}.bak"
        sed -i \
            -e '/syslinux-themes-ubuntu/d' \
            -e '/gfxboot-theme-ubuntu/d' \
            "$script"
        ok "Patched lb_binary_syslinux to skip obsolete Ubuntu theme packages."
    fi
}

main() {
    log "LLM-OS ISO Builder  |  mode=$MODE  |  model=$DEFAULT_MODEL"
    require_root
    check_deps
    patch_livebuild_syslinux
    init_build
    write_package_list
    write_firefox_pin
    copy_overlay
    copy_llmos_source
    write_chroot_hooks
    build_iso
    print_summary
}

main "$@"
