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
# Resolve a relative OUTPUT_DIR against REPO_DIR now — build_iso() cd's into
# BUILD_DIR, so a relative path would otherwise land under /tmp/llmos-build.
[[ "$OUTPUT_DIR" = /* ]] || OUTPUT_DIR="$REPO_DIR/$OUTPUT_DIR"
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
        --bootappend-live "boot=casper quiet splash ---" \
        --iso-application "LLM-OS" \
        --iso-publisher "LLM-OS Project" \
        --iso-volume "LLMOS_1_0"

    # Use GRUB only — syslinux theme packages were dropped from Ubuntu 24.04.
    # Write directly to the generated config file; --bootloaders is not
    # recognised in all live-build versions.
    local binary_cfg="$BUILD_DIR/config/binary"

    if grep -q "^LB_BOOTLOADERS=" "$binary_cfg" 2>/dev/null; then
        sed -i 's/^LB_BOOTLOADERS=.*/LB_BOOTLOADERS="grub-pc grub-efi-amd64"/' "$binary_cfg"
    else
        echo 'LB_BOOTLOADERS="grub-pc grub-efi-amd64"' >> "$binary_cfg"
    fi
    ok "Bootloaders set to grub-pc + grub-efi-amd64."

    # Use plain ISO (not iso-hybrid) so live-build never calls isohybrid.
    # isohybrid is only needed for USB-stick boot; QEMU/VirtualBox work fine
    # with a regular ISO.  Users who need USB boot can run isohybrid manually.
    if grep -q "^LB_BINARY_IMAGES=" "$binary_cfg" 2>/dev/null; then
        sed -i 's/^LB_BINARY_IMAGES=.*/LB_BINARY_IMAGES="iso"/' "$binary_cfg"
    else
        echo 'LB_BINARY_IMAGES="iso"' >> "$binary_cfg"
    fi
    ok "Binary image type set to iso (skips isohybrid step)."

    # The squashfs (Ollama + Firefox + Python deps) exceeds 4 GiB. ISO-9660
    # cannot represent a single >4 GiB file unless mkisofs/xorriso is told
    # -allow-limited-size, otherwise the binary stage aborts.
    if grep -q "^LB_MKISOFS_OPTIONS=" "$binary_cfg" 2>/dev/null; then
        sed -i 's/^LB_MKISOFS_OPTIONS=.*/LB_MKISOFS_OPTIONS="-allow-limited-size"/' "$binary_cfg"
    else
        echo 'LB_MKISOFS_OPTIONS="-allow-limited-size"' >> "$binary_cfg"
    fi
    ok "mkisofs option -allow-limited-size set (squashfs > 4 GiB)."
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
    # This live-build (3.0~aXX, Ubuntu fork) reads local hooks from
    # config/hooks/*.chroot and config/hooks/*.binary (FLAT) — not the newer
    # Debian config/hooks/normal/ subdirectory. Putting them in normal/ means
    # they silently never run (no Ollama, no user, no services).
    local hooks="$BUILD_DIR/config/hooks"
    mkdir -p "$hooks"

    # Hook 0050: Install Ollama
    cat > "$hooks/0050-install-ollama.hook.chroot" << 'HOOK'
#!/bin/bash
set -uo pipefail
echo "[hook] Installing Ollama…"
# Ollama's installer tries to start the systemd service and probe NVIDIA at the
# end. Inside the live-build chroot systemd is not running, so those final steps
# exit non-zero even though the binary is fully installed. Don't let that abort
# the hook — verify success by checking for the binary instead.
curl -fsSL https://ollama.com/install.sh | OLLAMA_MODELS=/usr/share/ollama/.ollama/models sh || \
    echo "[hook] Ollama installer returned non-zero (expected: no systemd in chroot); verifying binary…"
if ! command -v ollama >/dev/null 2>&1 && [ ! -x /usr/local/bin/ollama ] && [ ! -x /usr/bin/ollama ]; then
    echo "[hook] ERROR: ollama binary not found after install." >&2
    exit 1
fi
id ollama &>/dev/null || useradd -r -s /bin/false -d /usr/share/ollama ollama
mkdir -p /usr/share/ollama/.ollama/models
chown -R ollama:ollama /usr/share/ollama
echo "[hook] Ollama OK."
HOOK
    chmod +x "$hooks/0050-install-ollama.hook.chroot"

    # Hook 0055: Install Firefox (kiosk mode only)
    # Use the Ubuntu archive deb directly — avoids needing add-apt-repository
    # (software-properties-common) which is not installed in the minimal chroot.
    if [[ "$MODE" == "kiosk" ]]; then
        cat > "$hooks/0055-install-firefox.hook.chroot" << 'HOOK'
#!/bin/bash
set -euo pipefail
echo "[hook] Installing Firefox…"
# Prefer the snap-free deb from the Mozilla PPA key + sources list.
# add-apt-repository is not available; wire it up manually.
apt-get install -y --no-install-recommends software-properties-common gnupg curl
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://packages.mozilla.org/apt/repo-signing-key.gpg \
    | gpg --dearmor -o /etc/apt/keyrings/mozilla.gpg
echo "deb [signed-by=/etc/apt/keyrings/mozilla.gpg] https://packages.mozilla.org/apt mozilla main" \
    > /etc/apt/sources.list.d/mozilla.list
echo 'Package: *
Pin: origin packages.mozilla.org
Pin-Priority: 1001' > /etc/apt/preferences.d/mozilla

apt-get update -qq
apt-get install -y --no-install-recommends firefox
# Remove snap stub if it slipped in
apt-get remove -y --purge firefox-snap 2>/dev/null || true
echo "[hook] Firefox OK."
HOOK
        chmod +x "$hooks/0055-install-firefox.hook.chroot"
    fi

    # Hook 0060: Install LLM-OS Python package
    cat > "$hooks/0060-install-llmos.hook.chroot" << 'HOOK'
#!/bin/bash
set -euo pipefail
echo "[hook] Installing LLM-OS…"
# python3-pip is not guaranteed in the minimal chroot base
apt-get install -y --no-install-recommends python3-pip python3-venv 2>/dev/null || true
# --ignore-installed: do NOT try to uninstall Debian-managed packages (e.g.
# typing_extensions) — they have no pip RECORD file so the uninstall fails.
# pip installs its own copies alongside; later imports resolve the pip version.
pip3 install --break-system-packages --ignore-installed \
    "httpx>=0.27" "rich>=13.7" "prompt_toolkit>=3.0" "pyyaml>=6.0" "psutil>=5.9" \
    "fastapi>=0.111" "uvicorn[standard]>=0.29" "websockets>=12.0"
if [[ -d /usr/lib/llmos/llmos-src ]]; then
    pip3 install --break-system-packages --ignore-installed /usr/lib/llmos/llmos-src/ || \
        echo "[hook] Warning: llmos package install failed, deps already present."
fi
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
    # systemd is not running in the chroot but systemctl enable still works via
    # symlinks. Use || true on every call since some units may not exist yet.
    cat > "$hooks/0070-enable-services.hook.chroot" << 'HOOK'
#!/bin/bash
set -uo pipefail
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

    # NOTE: isolinux.cfg is NOT written by a binary hook anymore. Binary-hook
    # execution order vs. config/includes.binary copying is version-dependent and
    # unreliable. Instead, build_iso() splits the build, detects the real kernel
    # version from the chroot, and writes the correct versioned isolinux.cfg into
    # config/includes.binary/ before the binary stage runs (see build_iso).
}

write_isolinux_cfg_for_kernel() {
    # Detect the real kernel version installed in the chroot and write an
    # isolinux.cfg that points at the exact versioned filenames casper will
    # place in /casper/ (there are NO plain vmlinuz/initrd symlinks there, which
    # is why a static /casper/vmlinuz path hangs the boot).
    local isodir="$BUILD_DIR/config/includes.binary/isolinux"
    mkdir -p "$isodir"

    local kver
    kver=$(ls -1 "$BUILD_DIR"/chroot/boot/vmlinuz-* 2>/dev/null \
           | sed 's@.*/vmlinuz-@@' | sort -V | tail -1)

    if [[ -z "$kver" ]]; then
        warn "Could not detect kernel version in chroot/boot — isolinux.cfg keeps generic fallback (boot may fail)."
        return
    fi

    local vmlinuz="vmlinuz-$kver"
    local initrd="initrd.img-$kver"
    log "Detected kernel: $kver"
    log "Writing isolinux.cfg -> KERNEL=/casper/$vmlinuz  initrd=/casper/$initrd"

    cat > "$isodir/isolinux.cfg" <<CFG
UI menu.c32
MENU TITLE LLM-OS
PROMPT 0
TIMEOUT 50
DEFAULT live
LABEL live
  MENU LABEL Start LLM-OS
  KERNEL /casper/$vmlinuz
  APPEND initrd=/casper/$initrd boot=casper quiet splash ---
CFG
}

build_iso() {
    log "Starting live-build (this takes 15–40 minutes)…"
    cd "$BUILD_DIR"

    # Split the build so we can inject the correct isolinux.cfg between the
    # chroot stage (which installs the kernel) and the binary stage (which
    # copies config/includes.binary/ into the ISO tree and masters the ISO).
    local lb_exit=0
    set +o pipefail
    { lb bootstrap && lb chroot; } 2>&1 | tee "$REPO_DIR/build-iso.log"
    lb_exit=${PIPESTATUS[0]}
    set -o pipefail
    if [[ $lb_exit -ne 0 ]]; then
        err "lb chroot stage failed (exit $lb_exit). Check $REPO_DIR/build-iso.log"
    fi

    # Now the kernel is installed in chroot/boot — write the matching cfg.
    write_isolinux_cfg_for_kernel

    set +o pipefail
    lb binary 2>&1 | tee -a "$REPO_DIR/build-iso.log"
    lb_exit=${PIPESTATUS[0]}
    set -o pipefail
    if [[ $lb_exit -ne 0 ]]; then
        err "lb binary stage failed (exit $lb_exit). Check $REPO_DIR/build-iso.log"
    fi

    mkdir -p "$OUTPUT_DIR"
    local iso_src=""

    # Try the two standard live-build output names first.
    for candidate in \
        "$BUILD_DIR/live-image-${ARCH}.hybrid.iso" \
        "$BUILD_DIR/live-image-${ARCH}.iso"; do
        [[ -f "$candidate" ]] && { iso_src="$candidate"; break; }
    done

    # Fallback: any .iso live-build may have named differently.
    if [[ -z "$iso_src" ]]; then
        log "Standard ISO paths not found; scanning $BUILD_DIR for any .iso…"
        iso_src=$(find "$BUILD_DIR" -maxdepth 2 -name "*.iso" 2>/dev/null | head -1)
    fi

    if [[ -n "$iso_src" ]]; then
        # Remove any stale ISO first. A previous sudo build leaves it owned by
        # root, mode 0444 — a plain `mv` would then prompt "overwrite, overriding
        # mode 0444?" and, getting no answer in this non-interactive context,
        # leave the OLD ISO in place. That makes every rebuild look like a no-op
        # (you keep booting the same broken ISO).
        rm -f "$OUTPUT_DIR/$ISO_NAME"
        mv -f "$iso_src" "$OUTPUT_DIR/$ISO_NAME"
        # Make it readable/writable by the invoking user so they can replace or
        # delete it later without sudo.
        chmod 0644 "$OUTPUT_DIR/$ISO_NAME"
        if [[ -n "${SUDO_UID:-}" ]]; then
            chown "${SUDO_UID}:${SUDO_GID:-$SUDO_UID}" "$OUTPUT_DIR/$ISO_NAME" 2>/dev/null || true
        fi
        ok "ISO built: $OUTPUT_DIR/$ISO_NAME ($(du -sh "$OUTPUT_DIR/$ISO_NAME" | cut -f1))"
    else
        warn "No .iso found. Contents of $BUILD_DIR:"
        ls -lh "$BUILD_DIR"/ 2>&1 | head -30 || true
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
    echo "  ── VirtualBox ──────────────────────────────────────────"
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
    # Ubuntu 24.04 dropped the syslinux theme packages
    # (syslinux-themes-ubuntu-*, gfxboot-theme-ubuntu) that lb_binary_syslinux
    # still tries to apt-get install — which aborts the whole build.
    #
    # Fix in two parts:
    #   1. Bypass lb_binary_syslinux (inject `exit 0`) so it never installs
    #      those packages. As a side effect it no longer populates binary/isolinux/.
    #   2. genisoimage is still invoked with `-b isolinux/isolinux.bin`, so we
    #      supply that directory ourselves via config/includes.binary/isolinux/
    #      (see setup_isolinux_includes) using isolinux.bin from the host.
    #
    # The ISO boots through GRUB; isolinux is present only to satisfy
    # genisoimage's El Torito boot-catalog requirement.
    local syslinux_script="/usr/lib/live/build/lb_binary_syslinux"
    if [[ -f "$syslinux_script" ]]; then
        grep -q "# LLMOS-PATCHED" "$syslinux_script" || {
            cp "$syslinux_script" "${syslinux_script}.bak"
            sed -i '2i # LLMOS-PATCHED: syslinux disabled (Ubuntu 24.04 dropped theme pkgs)\nexit 0' "$syslinux_script"
            ok "Disabled lb_binary_syslinux stage."
        }
    fi

    # Install host-side tools: isolinux provides isolinux.bin, syslinux-utils
    # provides isohybrid, syslinux-common provides the *.c32 modules.
    log "Installing host syslinux tools (isolinux, syslinux-utils, syslinux-common)…"
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        isolinux syslinux-utils syslinux-common 2>/dev/null \
        && ok "Host syslinux tools ready." \
        || warn "Could not install syslinux tools — genisoimage may fail."
}

setup_isolinux_includes() {
    # Provide binary/isolinux/ via config/includes.binary/ (copied into the
    # binary tree before genisoimage runs). lb_binary_syslinux is bypassed, so
    # without this genisoimage aborts: "can't find boot catalog directory".
    log "Staging isolinux boot catalog via config/includes.binary…"
    local isodir="$BUILD_DIR/config/includes.binary/isolinux"
    mkdir -p "$isodir"

    local isobin=""
    for f in /usr/lib/ISOLINUX/isolinux.bin \
             /usr/lib/syslinux/isolinux.bin \
             /usr/share/syslinux/isolinux.bin; do
        [[ -f "$f" ]] && { isobin="$f"; break; }
    done
    [[ -n "$isobin" ]] || err "isolinux.bin not found. Run: make iso-deps"
    cp "$isobin" "$isodir/"

    # Copy the *.c32 modules referenced by isolinux.cfg (best-effort).
    for f in ldlinux.c32 libcom32.c32 libutil.c32 menu.c32 vesamenu.c32; do
        for d in /usr/lib/syslinux/modules/bios /usr/share/syslinux; do
            [[ -f "$d/$f" ]] && { cp "$d/$f" "$isodir/"; break; }
        done
    done

    # Fallback cfg — the 0080 binary hook overwrites this with the real detected
    # paths. Using casper defaults since we target Ubuntu Noble (casper puts
    # the kernel/initrd in /casper/, not /live/).
    cat > "$isodir/isolinux.cfg" << 'CFG'
UI menu.c32
MENU TITLE LLM-OS
PROMPT 0
TIMEOUT 50
DEFAULT live
LABEL live
  MENU LABEL Start LLM-OS
  KERNEL /casper/vmlinuz
  APPEND initrd=/casper/initrd boot=casper quiet splash ---
CFG
    ok "isolinux boot catalog staged."
}

main() {
    log "LLM-OS ISO Builder  |  mode=$MODE  |  model=$DEFAULT_MODEL"
    require_root
    check_deps
    patch_livebuild_syslinux
    init_build
    setup_isolinux_includes
    write_package_list
    write_firefox_pin
    copy_overlay
    copy_llmos_source
    write_chroot_hooks
    build_iso
    print_summary
}

main "$@"
