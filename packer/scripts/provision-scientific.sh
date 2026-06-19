#!/usr/bin/env bash
# Install the scientific computing stack inside the VM.
# Runs during Packer build — no GPU present yet (drivers installed at first boot).
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
LOG="/var/log/llmos-scientific.log"
log() { echo "[$(date +%T)] $*" | tee -a "$LOG"; }

log "=== Scientific Computing Stack Installation ==="

# ── CUDA Toolkit (no driver required to install) ─────────────────────────────
log "Adding NVIDIA CUDA apt repository…"
CUDA_KEYRING="cuda-keyring_1.1-1_all.deb"
wget -q "https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/$CUDA_KEYRING" \
    -O "/tmp/$CUDA_KEYRING" || { log "WARNING: Could not download CUDA keyring (no internet?)"; }

if [[ -f "/tmp/$CUDA_KEYRING" ]]; then
    dpkg -i "/tmp/$CUDA_KEYRING"
    apt-get update -qq
    log "Installing CUDA Toolkit 12.6 (no GPU driver — driver installs at first boot)…"
    apt-get install -y --no-install-recommends \
        cuda-toolkit-12-6 \
        cuda-compiler-12-6 \
        libcuda-dev \
        libcudnn9-cuda-12 \
        libcudnn9-dev-cuda-12 \
        libnccl2 \
        libnccl-dev \
        2>/dev/null || log "WARNING: Some CUDA packages unavailable — will retry at first boot"
fi

# ── ROCm (AMD) runtime ───────────────────────────────────────────────────────
log "Adding AMD ROCm apt repository…"
wget -q https://repo.radeon.com/rocm/rocm.gpg.key -O - 2>/dev/null | \
    gpg --dearmor | tee /etc/apt/keyrings/rocm.gpg > /dev/null || log "WARNING: Could not add ROCm key"

if [[ -f /etc/apt/keyrings/rocm.gpg ]]; then
    cat > /etc/apt/sources.list.d/rocm.list << 'EOF'
deb [arch=amd64 signed-by=/etc/apt/keyrings/rocm.gpg] https://repo.radeon.com/rocm/apt/6.2.2 noble main
EOF
    apt-get update -qq
    apt-get install -y --no-install-recommends rocm-hip-runtime rocm-device-libs 2>/dev/null || \
        log "WARNING: ROCm packages unavailable — will retry at first boot"
fi

# ── MPI ──────────────────────────────────────────────────────────────────────
log "Installing OpenMPI…"
apt-get install -y --no-install-recommends \
    openmpi-bin openmpi-common libopenmpi-dev \
    libhdf5-openmpi-dev \
    2>/dev/null

# ── HDF5 / NetCDF / Compression ──────────────────────────────────────────────
log "Installing data format libraries…"
apt-get install -y --no-install-recommends \
    libhdf5-dev hdf5-tools \
    libnetcdf-dev netcdf-bin \
    libfftw3-dev \
    libblas-dev liblapack-dev \
    libgsl-dev \
    2>/dev/null

# ── Python scientific stack (CPU packages, GPU extensions auto-detect CUDA) ──
log "Installing Python scientific packages…"
pip3 install --break-system-packages --quiet \
    numpy scipy pandas matplotlib seaborn \
    scikit-learn scikit-image \
    sympy statsmodels \
    h5py netCDF4 \
    dask[complete] \
    numba \
    mpi4py \
    plotly \
    tqdm \
    2>/dev/null

# PyTorch with CUDA 12 support (falls back to CPU if no GPU)
log "Installing PyTorch with CUDA 12 support…"
pip3 install --break-system-packages --quiet \
    torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu124 \
    2>/dev/null || \
pip3 install --break-system-packages --quiet torch torchvision torchaudio  # CPU fallback

# CuPy (GPU NumPy) — installs correctly even without GPU present
log "Installing CuPy (GPU-accelerated NumPy)…"
pip3 install --break-system-packages --quiet cupy-cuda12x 2>/dev/null || \
    log "WARNING: CuPy cuda12x unavailable — will install at first boot"

# JAX with CUDA (with CPU fallback)
log "Installing JAX…"
pip3 install --break-system-packages --quiet \
    "jax[cuda12_pip]" \
    -f https://storage.googleapis.com/jax-releases/jax_cuda_releases.html 2>/dev/null || \
pip3 install --break-system-packages --quiet jax  # CPU fallback

# JupyterLab + extensions
log "Installing JupyterLab…"
pip3 install --break-system-packages --quiet \
    jupyterlab \
    ipywidgets \
    jupyterlab-nvdashboard \
    2>/dev/null

# Molecular visualization
pip3 install --break-system-packages --quiet \
    MDAnalysis \
    nglview \
    2>/dev/null || true

# ── GROMACS (molecular dynamics) ─────────────────────────────────────────────
log "Installing GROMACS…"
apt-get install -y --no-install-recommends gromacs 2>/dev/null || \
    log "WARNING: GROMACS not in apt repos — build from source if needed"

# ── LAMMPS (molecular dynamics) ──────────────────────────────────────────────
log "Installing LAMMPS…"
apt-get install -y --no-install-recommends lammps 2>/dev/null || \
    log "WARNING: LAMMPS not found in repos"

# ── ParaView (visualization) ─────────────────────────────────────────────────
log "Installing ParaView…"
apt-get install -y --no-install-recommends paraview 2>/dev/null || \
    log "WARNING: ParaView not available — install from paraview.org"

# ── Conda/Mamba (for environment management) ─────────────────────────────────
log "Installing Miniforge (conda/mamba)…"
MINIFORGE="/tmp/miniforge.sh"
wget -q "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh" \
    -O "$MINIFORGE" && \
    bash "$MINIFORGE" -b -p /opt/conda && \
    ln -sf /opt/conda/bin/conda /usr/local/bin/conda && \
    ln -sf /opt/conda/bin/mamba /usr/local/bin/mamba && \
    rm -f "$MINIFORGE" || \
    log "WARNING: Miniforge download failed — conda not installed"

# Make conda available to all users
if [[ -f /opt/conda/etc/profile.d/conda.sh ]]; then
    ln -sf /opt/conda/etc/profile.d/conda.sh /etc/profile.d/conda.sh
fi

# ── GPU first-boot installer script ──────────────────────────────────────────
log "Writing GPU first-boot installer…"
cat > /usr/lib/llmos/install-gpu-drivers.sh << 'GPU_SCRIPT'
#!/usr/bin/env bash
# Detects GPU and installs the appropriate drivers/runtime at first boot.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

log() { echo "[gpu-firstboot] $*"; }

# Detect GPU vendor
if lspci | grep -qi "NVIDIA"; then
    VENDOR="nvidia"
elif lspci | grep -qi "AMD\|Radeon\|Advanced Micro Devices.*VGA"; then
    VENDOR="amd"
else
    log "No discrete GPU detected. Skipping driver installation."
    exit 0
fi

log "Detected GPU vendor: $VENDOR"

if [[ "$VENDOR" == "nvidia" ]]; then
    log "Installing NVIDIA driver and CUDA runtime…"
    apt-get update -qq
    # Install latest recommended driver
    apt-get install -y --no-install-recommends \
        nvidia-driver-565-open \
        nvidia-utils-565 \
        cuda-runtime-12-6 \
        2>/dev/null || apt-get install -y nvidia-driver-550-open nvidia-utils-550

    log "Configuring Ollama for NVIDIA GPU…"
    mkdir -p /etc/systemd/system/ollama.service.d
    cat > /etc/systemd/system/ollama.service.d/gpu.conf << 'EOF'
[Service]
Environment="CUDA_VISIBLE_DEVICES=all"
Environment="OLLAMA_GPU=nvidia"
EOF

elif [[ "$VENDOR" == "amd" ]]; then
    log "Installing AMD ROCm drivers…"
    apt-get update -qq
    # Install amdgpu-install if not present
    if ! command -v amdgpu-install &>/dev/null; then
        wget -q https://repo.radeon.com/amdgpu-install/6.2.2/ubuntu/noble/amdgpu-install_6.2.60202-1_all.deb \
            -O /tmp/amdgpu-install.deb
        dpkg -i /tmp/amdgpu-install.deb
        apt-get update -qq
    fi
    amdgpu-install -y --accept-eula --usecase=rocm,hip

    log "Configuring Ollama for AMD ROCm…"
    mkdir -p /etc/systemd/system/ollama.service.d
    cat > /etc/systemd/system/ollama.service.d/gpu.conf << 'EOF'
[Service]
Environment="HSA_OVERRIDE_GFX_VERSION=11.0.0"
Environment="OLLAMA_GPU=rocm"
EOF
fi

systemctl daemon-reload
log "GPU driver installation complete. Restart Ollama: sudo systemctl restart ollama"
GPU_SCRIPT
chmod +x /usr/lib/llmos/install-gpu-drivers.sh

log "=== Scientific computing stack installation complete ==="
