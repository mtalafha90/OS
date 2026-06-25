#!/usr/bin/env bash
# Build the LLM-OS live ISO using live-build (Debian/Ubuntu).
#
# Two modes:
#   kiosk  (default) — X11 + Firefox/Chromium kiosk, boots straight to web UI
#   server            — text-only, smaller ISO; access web UI from host browser
#
# Requirements (install with: make iso-deps):
#   sudo apt-get install live-build squashfs-tools xorriso \
#       grub-pc-bin grub-efi-amd64-bin mtools isolinux syslinux-utils syslinux-common
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
Run:  sudo apt-get install live-build squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin mtools isolinux syslinux-utils syslinux-common"
    fi
    ok "Build dependencies present."
}

patch_livebuild_syslinux() {
    # Ubuntu 24.04 dropped all syslinux theme packages. Bypass the entire
    # lb_binary_syslinux stage by injecting exit 0 after the shebang so no
    # theme-package apt-get calls are made. The ISO boots via GRUB.
    # A binary hook (0075) re-creates the minimal isolinux/ catalog that
    # genisoimage still needs, and we install host-side syslinux tools here.
    local script="/usr/lib/live/build/lb_binary_syslinux"
    if [[ -f "$script" ]]; then
        grep -q "# LLMOS-PATCHED" "$script" || {
            cp "$script" "${script}.bak"
            sed -i '1a # LLMOS-PATCHED: syslinux disabled (Ubuntu 24.04 dropped theme pkgs)\nexit 0' "$script"
            ok "Disabled lb_binary_syslinux stage."
        }
    fi

    # Install host-side tools that genisoimage / isohybrid still need.
    log "Installing host syslinux tools (isolinux, syslinux-utils)…"
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        isolinux syslinux-utils syslinux-common 2>/dev/null \
        && ok "Host syslinux tools ready." \
        || warn "Could not install syslinux tools — build may fail at isohybrid step."
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

    cp "$REPO_DIR/config/llmos.yaml" "$overlay/etc/llmos/llmos.yaml"

    cp "$REPO_DIR/scripts/first-boot.sh" "$overlay/usr/lib/llmos/first-boot.sh"
    chmod +x "$overlay/usr/lib/llmos/first-boot.sh"

    if [[ "$MODE" == "kiosk" ]]; then
        cp "$REPO_DIR/scripts/kiosk-start.sh" "$overlay/usr/lib/llmos/kiosk-start.sh"
        chmod +x "$overlay/usr/lib/llmos/kiosk-start.sh"
    fi

    cp "$REPO_DIR/systemd/ollama.service"           "$overlay/etc/systemd/system/"
    cp "$REPO_DIR/systemd/llmos-firstboot.service"  "$overlay/etc/systemd/system/"
    cp "$REPO_DIR/systemd/llmos-web.service"        "$overlay/etc/systemd/system/"

    mkdir -p "$overlay/etc/systemd/system/getty@tty1.service.d"
    cat > "$overlay/etc/systemd/system/getty@tty1.service.d/autologin.conf" << 'GETTY'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin llmos --noclear %I $TERM
GETTY

    local skel="$overlay/etc/skel-llmos"
    mkdir -p "$skel"

    if [[ "$MODE" == "kiosk" ]]; then
        cat > "$skel/.xinitrc" << 'XINITRC'
#!/bin/bash
openbox &
exec /usr/lib/llmos/kiosk-start.sh
XINITRC
        chmod +x "$skel/.xinitrc"

        cat > "$skel/.bash_profile" << 'BASHPROFILE'
[[ -f ~/.bashrc ]] && . ~/.bashrc
if [[ -z "${DISPLAY:-}" && "$(tty)" == /dev/tty1 ]]; then
    exec startx ~/.xinitrc -- :0 vt1 2>/tmp/startx.log
fi
BASHPROFILE
    fi

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

    mkdir -p "$overlay/etc/update-motd.d"
    cat > "$overlay/etc/update-motd.d/10-llmos" << 'MOTD'
#!/bin/sh
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ""
echo "  ╔════════════════════════════════════════════╗"
echo "  ║             L L M - O S                     ║"
echo "  ║     Natural Language Operating System        ║"
echo "  ╠════════════════════════════════════════════╣"
echo "  ║  Credentials:  llmos / llmos                 ║"
echo "  ║  Web UI:       http://${IP:-<vm-ip>}:8080    ║"
echo "  ║  Change pass:  passwd                        ║"
echo "  ╚════════════════════════════════════════════╝"
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
systemctl enable getty@tty1.service      || true
chmod -x /etc/update-motd.d/10-help-text 2>/dev/null || true
chmod -x /etc/update-motd.d/50-motd-news 2>/dev/null || true
echo "[hook] Services enabled."
HOOK
    chmod +x "$hooks/0070-enable-services.hook.chroot"

    # Hook 0075: Set up isolinux boot catalog (binary stage, runs in binary/ dir).
    # lb_binary_syslinux is bypassed to avoid missing Ubuntu theme packages;
    # genisoimage still requires an isolinux/ directory to exist.
    cat > "$hooks/0075-setup-isolinux.hook.binary" << 'HOOK'
#!/bin/bash
echo "[hook] Creating minimal isolinux boot catalog…"
mkdir -p isolinux

ISOBIN=""
for f in /usr/lib/ISOLINUX/isolinux.bin \
          /usr/lib/syslinux/isolinux.bin \
          /usr/share/syslinux/isolinux.bin; do
    [[ -f "$f" ]] && { ISOBIN="$f"; break; }
done
if [[ -z "$ISOBIN" ]]; then
    echo "[hook] ERROR: isolinux.bin not found. Run: sudo apt-get install isolinux"
    exit 1
fi
cp "$ISOBIN" isolinux/

# ldlinux.c32 required by syslinux >= 5
for f in /usr/lib/syslinux/modules/bios/ldlinux.c32 \
          /usr/share/syslinux/ldlinux.c32; do
    [[ -f "$f" ]] && { cp "$f" isolinux/; break; }
done

# menu.c32 for the text menu UI
for f in /usr/lib/syslinux/modules/bios/menu.c32 \
          /usr/share/syslinux/menu.c32; do
    [[ -f "$f" ]] && { cp "$f" isolinux/; break; }
done

[[ -f isolinux/isolinux.cfg ]] || cat > isolinux/isolinux.cfg << 'CFG'
UI menu.c32
MENU TITLE LLM-OS Boot Menu
TIMEOUT 30
DEFAULT live
LABEL live
  MENU LABEL Start LLM-OS
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd boot=live components quiet splash
CFG

echo "[hook] isolinux boot catalog ready."
HOOK
    chmod +x "$hooks/0075-setup-isolinux.hook.binary"
}

build_iso() {
    log "Starting live-build (this takes 15–40 minutes)…"
    cd "$BUILD_DIR"
    lb build 2>&1 | tee "$REPO_DIR/build-iso.log"

    mkdir -p "$OUTPUT_DIR"
    local iso_src="$BUILD_DIR/live-image-${ARCH}.hybrid.iso"
    if [[ -f "$iso_src" ]]; then
        mv "$iso_src" "$OUTPUT_DIR/$ISO_NAME"
        ok "ISO built: $OUTPUT_DIR/$ISO_NAME ($(du -sh \"$OUTPUT_DIR/$ISO_NAME\" | cut -f1))"
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
    [[ -f "$iso" ]] && echo "  Size: $(du -sh \"$iso\" | cut -f1)"
    echo
    echo "  ── VirtualBox ───────────────────────────────────────────"
    echo "  1. File → New → Name: LLM-OS, Type: Linux, Version: Ubuntu 64-bit"
    echo "  2. RAM: 4096 MB+, CPU: 2+ cores"
    echo "  3. Storage → Add → choose $ISO_NAME"
    echo "  4. Start VM"
    echo
    echo "  ── QEMU/KVM ─────────────────────────────────────────────"
    echo "  qemu-system-x86_64 \\\\"
    echo "    -m 4G -smp 2 \\\\"
    echo "    -cdrom $iso \\\\"
    echo "    -net nic -net user,hostfwd=tcp::8080-:8080 \\\\"
    echo "    -enable-kvm -display sdl"
    echo
    if [[ "$MODE" == "kiosk" ]]; then
        echo "  ── Kiosk Mode ───────────────────────────────────────────"
        echo "  The VM boots directly to the LLM-OS web UI."
        echo "  Default lock screen password: llmos"
    else
        echo "  ── Server Mode ──────────────────────────────────────────"
        echo "  Open http://localhost:8080 in your browser after boot."
    fi
    echo
    echo "  Note: First boot pulls model '$DEFAULT_MODEL' (~2 GB)."
    echo "        Ensure internet access on first boot."
    echo
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
