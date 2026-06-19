#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  LLM-OS GPU Passthrough Setup — runs on the HOST machine               ║
# ║                                                                          ║
# ║  Configures IOMMU + VFIO so a physical GPU can be passed through        ║
# ║  exclusively to the LLM-OS QEMU/KVM virtual machine.                    ║
# ║                                                                          ║
# ║  Usage:  sudo ./scripts/setup-gpu-passthrough.sh [--dry-run]           ║
# ║                                                                          ║
# ║  After running, reboot the host, then launch the VM with:               ║
# ║    make vm-run-gpu                                                       ║
# ╚══════════════════════════════════════════════════════════════════════════╝
set -euo pipefail

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

log()  { echo -e "\033[1;36m[gpu-passthrough]\033[0m $*"; }
ok()   { echo -e "\033[1;32m  ✓\033[0m $*"; }
warn() { echo -e "\033[1;33m  !\033[0m $*"; }
err()  { echo -e "\033[1;31m  ✗\033[0m $*" >&2; exit 1; }
run()  { $DRY_RUN && echo "  [DRY RUN] $*" || eval "$*"; }

require_root() {
    [[ $EUID -eq 0 ]] || err "Run as root: sudo $0 $*"
}

# ── Step 1: Detect GPU ────────────────────────────────────────────────────────
detect_gpus() {
    log "Detecting GPUs via lspci…"
    echo ""
    echo "  All VGA/3D controllers:"
    lspci -nn | grep -E "VGA|3D|Display" || echo "  (none found)"
    echo ""

    mapfile -t GPU_LINES < <(lspci -nn | grep -E "VGA|3D|Display")
    if [[ ${#GPU_LINES[@]} -eq 0 ]]; then
        err "No GPU found. Is a GPU installed in this machine?"
    fi

    # Let user pick which GPU to pass through if multiple
    if [[ ${#GPU_LINES[@]} -gt 1 ]]; then
        echo "  Multiple GPUs found:"
        for i in "${!GPU_LINES[@]}"; do
            echo "    [$i] ${GPU_LINES[$i]}"
        done
        read -rp "  Enter index of GPU to pass through [0]: " GPU_IDX
        GPU_IDX="${GPU_IDX:-0}"
    else
        GPU_IDX=0
    fi

    SELECTED_GPU="${GPU_LINES[$GPU_IDX]}"
    GPU_PCI=$(echo "$SELECTED_GPU" | awk '{print $1}')
    GPU_IDS=$(echo "$SELECTED_GPU" | grep -oP '\[\K[0-9a-f]{4}:[0-9a-f]{4}(?=\])')
    VENDOR_ID=$(echo "$GPU_IDS" | cut -d: -f1)
    DEVICE_ID=$(echo "$GPU_IDS" | cut -d: -f2)

    log "Selected GPU: $SELECTED_GPU"
    log "PCI address: $GPU_PCI"
    log "Vendor:Device IDs: $VENDOR_ID:$DEVICE_ID"

    # Find audio device in same IOMMU group (usually accompanies GPU)
    GPU_AUDIO_PCI=$(lspci -nn | grep -A2 "$GPU_PCI" | grep -i audio | awk '{print $1}' || true)
    if [[ -n "$GPU_AUDIO_PCI" ]]; then
        GPU_AUDIO_IDS=$(lspci -nn | grep "$GPU_AUDIO_PCI" | grep -oP '\[\K[0-9a-f]{4}:[0-9a-f]{4}(?=\])')
        log "Associated audio: $GPU_AUDIO_PCI ($GPU_AUDIO_IDS) — will also bind to VFIO"
    fi
}

# ── Step 2: Check/enable IOMMU ───────────────────────────────────────────────
check_iommu() {
    log "Checking IOMMU support…"

    if [[ -d /sys/kernel/iommu_groups ]]; then
        GROUP_COUNT=$(ls /sys/kernel/iommu_groups/ | wc -l)
        if [[ $GROUP_COUNT -gt 0 ]]; then
            ok "IOMMU already active ($GROUP_COUNT groups)."
            return
        fi
    fi

    warn "IOMMU not active. Enabling in GRUB…"

    CPU_VENDOR=$(grep -m1 vendor_id /proc/cpuinfo | awk '{print $3}')
    if [[ "$CPU_VENDOR" == "GenuineIntel" ]]; then
        IOMMU_PARAM="intel_iommu=on iommu=pt"
    elif [[ "$CPU_VENDOR" == "AuthenticAMD" ]]; then
        IOMMU_PARAM="amd_iommu=on iommu=pt"
    else
        err "Unknown CPU vendor: $CPU_VENDOR. Set IOMMU manually in /etc/default/grub."
    fi

    log "Adding GRUB parameters: $IOMMU_PARAM"
    GRUB_FILE="/etc/default/grub"
    GRUB_BACKUP="${GRUB_FILE}.bak.$(date +%s)"
    run "cp $GRUB_FILE $GRUB_BACKUP"

    if grep -q "GRUB_CMDLINE_LINUX_DEFAULT" "$GRUB_FILE"; then
        run "sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=\"/GRUB_CMDLINE_LINUX_DEFAULT=\"$IOMMU_PARAM /' $GRUB_FILE"
    else
        run "echo 'GRUB_CMDLINE_LINUX_DEFAULT=\"$IOMMU_PARAM quiet splash\"' >> $GRUB_FILE"
    fi

    run "update-grub"
    warn "IOMMU configured. A REBOOT is required before continuing."
    warn "Run this script again after rebooting."
}

# ── Step 3: Bind GPU to VFIO ─────────────────────────────────────────────────
bind_vfio() {
    log "Binding GPU to vfio-pci driver…"

    VFIO_CONF="/etc/modprobe.d/vfio.conf"
    IDS="$VENDOR_ID:$DEVICE_ID"
    [[ -n "${GPU_AUDIO_IDS:-}" ]] && IDS="$IDS,$GPU_AUDIO_IDS"

    log "Writing $VFIO_CONF with IDs: $IDS"
    run "echo 'options vfio-pci ids=$IDS' > $VFIO_CONF"
    run "echo 'softdep drm pre: vfio-pci' >> /etc/modprobe.d/vfio.conf"

    # Add vfio modules to initramfs
    MODULES_FILE="/etc/modules"
    for mod in vfio vfio_iommu_type1 vfio_pci vfio_virqfd; do
        grep -q "^$mod" "$MODULES_FILE" 2>/dev/null || run "echo $mod >> $MODULES_FILE"
    done

    # Blacklist GPU driver on host so VFIO gets it first
    GPU_DRIVER=$(lspci -k | grep -A3 "$GPU_PCI" | grep "Kernel driver" | awk '{print $NF}')
    if [[ -n "$GPU_DRIVER" && "$GPU_DRIVER" != "vfio-pci" ]]; then
        log "Blacklisting host GPU driver: $GPU_DRIVER"
        run "echo 'blacklist $GPU_DRIVER' > /etc/modprobe.d/blacklist-gpu.conf"
    fi

    run "update-initramfs -u"
    ok "VFIO configuration written."
}

# ── Step 4: Write VM launch script ───────────────────────────────────────────
write_launch_script() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    LAUNCH_SCRIPT="$SCRIPT_DIR/scripts/run-vm-gpu.sh"

    log "Writing GPU VM launch script to $LAUNCH_SCRIPT…"

    VFIO_DEVICE="-device vfio-pci,host=${GPU_PCI}"
    [[ -n "${GPU_AUDIO_PCI:-}" ]] && VFIO_DEVICE="$VFIO_DEVICE -device vfio-pci,host=${GPU_AUDIO_PCI}"

    cat > "$LAUNCH_SCRIPT" << SCRIPT
#!/usr/bin/env bash
# LLM-OS GPU VM launcher — auto-generated by setup-gpu-passthrough.sh
# GPU: $SELECTED_GPU
set -euo pipefail

QCOW2="\${1:-$SCRIPT_DIR/dist/qemu/llmos.qcow2}"
[[ -f "\$QCOW2" ]] || { echo "Error: VM image not found at \$QCOW2"; echo "Run: make vm-qemu"; exit 1; }

echo "Starting LLM-OS with GPU passthrough..."
echo "  GPU: $SELECTED_GPU"
echo "  Image: \$QCOW2"
echo "  Web UI will be available at: http://localhost:8080"
echo ""

exec qemu-system-x86_64 \\
    -name "LLM-OS" \\
    -machine q35,accel=kvm \\
    -cpu host \\
    -smp cpus=4,sockets=1,cores=4,threads=1 \\
    -m 16G \\
    -drive file="\$QCOW2",format=qcow2,if=virtio,cache=writeback \\
    -net nic,model=virtio \\
    -net user,hostfwd=tcp::8080-:8080,hostfwd=tcp::2222-:22 \\
    $VFIO_DEVICE \\
    -display sdl \\
    -vga std \\
    "\$@"
SCRIPT
    chmod +x "$LAUNCH_SCRIPT"
    ok "Launch script written: $LAUNCH_SCRIPT"
}

# ── Step 5: Verify IOMMU grouping ────────────────────────────────────────────
show_iommu_groups() {
    log "IOMMU groups containing the selected GPU:"
    for group in /sys/kernel/iommu_groups/*/devices/*; do
        [[ -e "$group" ]] || continue
        addr=$(basename "$group")
        if [[ "$addr" == "$GPU_PCI"* ]]; then
            GROUP_DIR=$(dirname "$group")
            echo ""
            echo "  IOMMU Group $(basename "$GROUP_DIR"):"
            for dev in "$GROUP_DIR"/devices/*; do
                echo "    $(basename "$dev") — $(lspci -nns "$(basename "$dev")" | head -1)"
            done
        fi
    done
    echo ""
    warn "All devices in the same IOMMU group must be passed through together."
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    $DRY_RUN && warn "DRY RUN mode — no changes will be made."

    require_root
    detect_gpus
    check_iommu
    bind_vfio
    write_launch_script

    if ls /sys/kernel/iommu_groups/ 2>/dev/null | grep -q .; then
        show_iommu_groups
    fi

    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║         GPU Passthrough Setup Complete                      ║"
    echo "╠══════════════════════════════════════════════════════════════╣"
    echo "║  Next steps:                                                ║"
    echo "║  1. Reboot the host:    sudo reboot                        ║"
    echo "║  2. Build the VM:       make vm-qemu  (if not done yet)    ║"
    echo "║  3. Launch with GPU:    make vm-run-gpu                    ║"
    echo "║     Or directly:        bash scripts/run-vm-gpu.sh         ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
}

main "$@"
