.PHONY: help install dev docker iso clean lint test

SHELL   := /bin/bash
MODEL   ?= llama3.2
DOCKER  ?= llmos:latest

help:   ## Show this help
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z_-]+:.*##/{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}' $(MAKEFILE_LIST)

# ── Development ────────────────────────────────────────────────────────────────

install: ## Install LLM-OS on this system (requires Python 3.11+)
	pip3 install --break-system-packages -e ".[web]"

dev: ## Run LLM-OS terminal shell (requires Ollama running locally)
	python3 -m llmos.main --model $(MODEL)

web: ## Run LLM-OS Ubuntu-style web UI (opens in browser)
	python3 -m llmos.main --web --model $(MODEL) --port 8080

dev-verbose: ## Run with tool call output
	python3 -m llmos.main --model $(MODEL)

cmd: ## Run a single command: make cmd PROMPT="list files in /tmp"
	python3 -m llmos.main --cmd "$(PROMPT)"

# ── Docker ─────────────────────────────────────────────────────────────────────

docker-build: ## Build the Docker image
	docker build -t $(DOCKER) -f docker/Dockerfile .

docker-run: ## Run LLM-OS in Docker (Ollama on host)
	docker run -it --rm \
		--add-host host.docker.internal:host-gateway \
		-e OLLAMA_URL=http://host.docker.internal:11434 \
		-e LLMOS_MODEL=$(MODEL) \
		$(DOCKER)

docker-run-bundled: ## Run LLM-OS with Ollama bundled inside container
	docker run -it --rm $(DOCKER) --with-ollama

# ── VM Images (Packer) ─────────────────────────────────────────────────────────

vm: ## Build both VirtualBox OVA and QEMU QCOW2 (requires Packer)
	bash build/build-vm.sh all

vm-virtualbox: ## Build VirtualBox OVA only
	bash build/build-vm.sh virtualbox

vm-qemu: ## Build QEMU/KVM QCOW2 only
	bash build/build-vm.sh qemu

vm-fast: ## Build VM without pre-pulling model (faster build, needs internet on first boot)
	SKIP_MODEL_PULL=1 bash build/build-vm.sh all

vm-run-gpu: ## Launch the QEMU VM with GPU passthrough (run setup-gpu-passthrough.sh first)
	@[[ -f scripts/run-vm-gpu.sh ]] || { echo "Run first: sudo bash scripts/setup-gpu-passthrough.sh"; exit 1; }
	bash scripts/run-vm-gpu.sh

vm-run: ## Launch the QEMU VM without GPU (for testing)
	qemu-system-x86_64 \
	  -name "LLM-OS" -machine q35,accel=kvm -cpu host \
	  -smp 4 -m 8G \
	  -drive file=dist/qemu/llmos.qcow2,format=qcow2,if=virtio \
	  -net nic,model=virtio -net user,hostfwd=tcp::8080-:8080,hostfwd=tcp::2222-:22 \
	  -display sdl

gpu-passthrough: ## Configure host GPU passthrough for QEMU (requires root)
	sudo bash scripts/setup-gpu-passthrough.sh

gpu-passthrough-dry: ## Preview GPU passthrough changes without applying
	sudo bash scripts/setup-gpu-passthrough.sh --dry-run

vm-deps: ## Install Packer and VM build dependencies
	@echo "Installing Packer…"
	@wget -qO /tmp/packer.zip https://releases.hashicorp.com/packer/1.11.2/packer_1.11.2_linux_amd64.zip
	@unzip -o /tmp/packer.zip -d /usr/local/bin/ && chmod +x /usr/local/bin/packer
	@echo "Installing QEMU + KVM…"
	@sudo apt-get install -y qemu-kvm qemu-utils bridge-utils cpu-checker ovmf
	@echo "VirtualBox (optional): https://www.virtualbox.org/wiki/Downloads"

packer-init: ## Initialize Packer plugins
	cd packer && packer init llmos.pkr.hcl

# ── ISO ────────────────────────────────────────────────────────────────────────

iso: ## Build live ISO — kiosk mode (X11 + browser, boots to web UI)
	sudo LLMOS_MODEL=$(MODEL) LLMOS_BUILD_DIR=/tmp/llmos-build bash build/build-iso.sh dist kiosk

iso-server: ## Build live ISO — server mode (text-only, smaller, ~800 MB)
	sudo LLMOS_MODEL=$(MODEL) LLMOS_BUILD_DIR=/tmp/llmos-build bash build/build-iso.sh dist server

iso-run: ## Test kiosk ISO in QEMU (no KVM — safe for any host)
	@ISO=$$(ls -t dist/llmos-*-kiosk.iso 2>/dev/null | head -1); \
	[[ -n "$$ISO" ]] || { echo "No kiosk ISO found in dist/. Run: make iso"; exit 1; }; \
	echo "Booting $$ISO …"; \
	qemu-system-x86_64 -m 4G -smp 2 \
	  -cdrom "$$ISO" \
	  -net nic -net user,hostfwd=tcp::8080-:8080 \
	  -display sdl

iso-deps: ## Install ISO build dependencies
	sudo apt-get install -y live-build squashfs-tools xorriso isolinux syslinux-efi

# ── Quality ────────────────────────────────────────────────────────────────────

lint: ## Run ruff linter
	python3 -m ruff check llmos/

typecheck: ## Run mypy type checker
	python3 -m mypy llmos/

test: ## Run tests
	python3 -m pytest tests/ -v --tb=short

clean: ## Clean build artifacts
	rm -rf .build dist build.log __pycache__ *.egg-info
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
