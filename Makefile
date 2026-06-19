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

# ── ISO ────────────────────────────────────────────────────────────────────────

iso: ## Build the live ISO (requires live-build, must run as root)
	sudo LLMOS_MODEL=$(MODEL) bash build/build-iso.sh

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
