#!/usr/bin/env bash
# Build LLM-OS virtual machine images using Packer.
#
# Outputs:
#   dist/virtualbox/llmos.ova   — import into VirtualBox
#   dist/qemu/llmos.qcow2       — use with QEMU/KVM/Proxmox
#
# Requirements:
#   - Packer >= 1.10        (https://developer.hashicorp.com/packer/install)
#   - VirtualBox >= 7.0     (for OVA build)
#   - QEMU + KVM            (for QCOW2 build)  [Linux only]
#
# Usage:
#   ./build/build-vm.sh [virtualbox|qemu|all]  [--skip-model-pull]
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKER_DIR="$REPO_DIR/packer"
DIST_DIR="$REPO_DIR/dist"
TARGET="${1:-all}"
SKIP_MODEL_PULL="${SKIP_MODEL_PULL:-0}"

# Shift if first arg is a target
[[ "$TARGET" == "--skip-model-pull" ]] && { SKIP_MODEL_PULL=1; TARGET="all"; }
[[ "${2:-}" == "--skip-model-pull" ]] && SKIP_MODEL_PULL=1

log()  { echo -e "\033[1;36m[build-vm]\033[0m $*"; }
ok()   { echo -e "\033[1;32m  ✓\033[0m $*"; }
err()  { echo -e "\033[1;31m  ✗\033[0m $*" >&2; exit 1; }
warn() { echo -e "\033[1;33m  !\033[0m $*"; }

check_deps() {
    log "Checking build dependencies…"
    command -v packer &>/dev/null || err "Packer not found. Install from https://developer.hashicorp.com/packer/install"

    PACKER_VER=$(packer version | grep -oP '\d+\.\d+' | head -1)
    log "Packer version: $PACKER_VER"

    if [[ "$TARGET" == "virtualbox" || "$TARGET" == "all" ]]; then
        command -v VBoxManage &>/dev/null || err "VirtualBox not found. Install VirtualBox 7.0+ first."
    fi

    if [[ "$TARGET" == "qemu" || "$TARGET" == "all" ]]; then
        command -v qemu-system-x86_64 &>/dev/null || err "QEMU not found. Install: sudo apt-get install qemu-kvm"
        if ! kvm-ok &>/dev/null 2>&1; then
            warn "KVM not available — QEMU build will be very slow (no hardware acceleration)."
        fi
    fi

    ok "All dependencies present."
}

init_packer() {
    log "Initialising Packer plugins…"
    cd "$PACKER_DIR"
    packer init llmos.pkr.hcl
    ok "Packer plugins ready."
}

build() {
    local source="$1"
    local friendly_name="$2"
    local output="$3"

    log "Building $friendly_name image…"
    cd "$PACKER_DIR"

    PACKER_LOG=1 PACKER_LOG_PATH="$REPO_DIR/build-${source}.log" \
    SKIP_MODEL_PULL="$SKIP_MODEL_PULL" \
    packer build \
        -only="${source}.llmos" \
        -var "output_dir=$DIST_DIR" \
        -var-file="variables.pkrvars.hcl" \
        llmos.pkr.hcl

    if [[ -f "$output" ]]; then
        SIZE=$(du -sh "$output" | cut -f1)
        ok "$friendly_name image built: $output ($SIZE)"
    else
        err "$friendly_name image not found at $output"
    fi
}

print_usage_instructions() {
    local vbox_ova="$DIST_DIR/virtualbox/llmos.ova"
    local qemu_img="$DIST_DIR/qemu/llmos.qcow2"

    echo
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║          LLM-OS VM Build Complete!                  ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo

    if [[ -f "$vbox_ova" ]]; then
        echo "  VirtualBox:"
        echo "    File:  $vbox_ova"
        echo "    Import: File → Import Appliance → select llmos.ova"
        echo "            Or: VBoxManage import $vbox_ova"
        echo
    fi

    if [[ -f "$qemu_img" ]]; then
        echo "  QEMU / KVM:"
        echo "    File: $qemu_img"
        echo "    Run:"
        echo "      qemu-system-x86_64 \\"
        echo "        -m 4G -smp 2 \\"
        echo "        -drive file=$qemu_img,format=qcow2 \\"
        echo "        -net nic -net user,hostfwd=tcp::8080-:8080 \\"
        echo "        -enable-kvm"
        echo
        echo "  Proxmox / libvirt:"
        echo "    cp $qemu_img /var/lib/libvirt/images/llmos.qcow2"
        echo "    # Then create VM pointing to that disk image"
        echo
    fi

    echo "  First login:"
    echo "    Username: llmos"
    echo "    Password: llmos   (change with: passwd)"
    echo
    echo "  Web UI:    http://<vm-ip>:8080  (opens automatically on login)"
    echo "  Terminal:  llmos"
    echo
    if [[ "$SKIP_MODEL_PULL" == "1" ]]; then
        warn "Model was NOT pre-pulled. Ensure the VM has internet access on first boot."
    fi
}

main() {
    log "LLM-OS VM Builder"
    log "Target: $TARGET  |  Skip model pull: $SKIP_MODEL_PULL"
    mkdir -p "$DIST_DIR"
    check_deps
    init_packer

    case "$TARGET" in
        virtualbox)
            build "virtualbox-iso" "VirtualBox OVA" "$DIST_DIR/virtualbox/llmos.ova"
            ;;
        qemu)
            build "qemu" "QEMU QCOW2" "$DIST_DIR/qemu/llmos.qcow2"
            ;;
        all)
            build "virtualbox-iso" "VirtualBox OVA" "$DIST_DIR/virtualbox/llmos.ova"
            build "qemu" "QEMU QCOW2" "$DIST_DIR/qemu/llmos.qcow2"
            ;;
        *)
            err "Unknown target '$TARGET'. Use: virtualbox | qemu | all"
            ;;
    esac

    print_usage_instructions
}

main
