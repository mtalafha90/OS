#!/usr/bin/env bash
# Clean up the VM image to reduce file size before export.
set -euo pipefail

echo "[cleanup] Starting VM cleanup…"

export DEBIAN_FRONTEND=noninteractive

# Remove apt cache
apt-get clean
apt-get autoremove -y
rm -rf /var/lib/apt/lists/*

# Remove pip cache
pip3 cache purge 2>/dev/null || true

# Remove cloud-init artifacts that would cause re-init on clone
# (we keep the config but remove the cache)
cloud-init clean --logs 2>/dev/null || true

# Remove SSH host keys (regenerated on first boot of each clone)
rm -f /etc/ssh/ssh_host_*

# Add key regen to rc.local for cloned VMs
cat > /etc/rc.local << 'RC'
#!/bin/bash
# Regenerate SSH host keys if missing (happens after cloning)
if ! ls /etc/ssh/ssh_host_*_key 2>/dev/null | grep -q .; then
    dpkg-reconfigure openssh-server 2>/dev/null || true
fi
exit 0
RC
chmod +x /etc/rc.local

# Remove Packer temp files
rm -rf /tmp/llmos-src
rm -f /tmp/ollama-pull.log

# Remove bash history
unset HISTFILE
history -c
rm -f /home/llmos/.bash_history /root/.bash_history

# Remove cloud-init data (avoids reuse on clone)
rm -rf /var/lib/cloud/*

# Truncate logs
find /var/log -type f | xargs truncate -s 0 2>/dev/null || true
journalctl --rotate --vacuum-size=1M 2>/dev/null || true

# Zero out free space so qcow2/OVA compresses well
echo "[cleanup] Zeroing free space (reduces image size)…"
dd if=/dev/zero of=/tmp/zero bs=1M 2>/dev/null || true
sync
rm -f /tmp/zero

echo "[cleanup] VM cleanup complete."
