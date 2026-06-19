# LLM-OS — Docker image for development and testing.
# Ollama runs as a sidecar; connect with --ollama-url or OLLAMA_URL env var.
#
# Build:
#   docker build -t llmos -f docker/Dockerfile .
#
# Run (requires Ollama accessible on host):
#   docker run -it --rm \
#     -e OLLAMA_URL=http://host.docker.internal:11434 \
#     llmos
#
# Or with bundled Ollama (GPU passthrough):
#   docker run -it --rm --gpus all llmos --with-ollama

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    curl \
    wget \
    net-tools \
    iputils-ping \
    dnsutils \
    iproute2 \
    htop \
    nano \
    git \
    jq \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install LLM-OS Python package (including web UI dependencies)
WORKDIR /opt/llmos
COPY requirements.txt pyproject.toml ./
COPY llmos/ ./llmos/
RUN pip3 install --no-cache-dir --break-system-packages ".[web]"

EXPOSE 8080

# Configuration
COPY config/llmos.yaml /etc/llmos/llmos.yaml
RUN mkdir -p /root/.config/llmos && \
    cp /etc/llmos/llmos.yaml /root/.config/llmos/config.yaml

# Scripts
COPY scripts/ /usr/lib/llmos/scripts/
RUN chmod +x /usr/lib/llmos/scripts/*.sh

# Environment
ENV OLLAMA_URL="http://host.docker.internal:11434"
ENV LLMOS_MODEL="llama3.2"

# Entrypoint wrapper: accept --with-ollama flag to start Ollama inside container
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD []
