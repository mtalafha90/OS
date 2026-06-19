# LLM-OS Packer default variable overrides.
# Pass to Packer with: packer build -var-file=variables.pkrvars.hcl llmos.pkr.hcl

# Model to pre-install in the image
ollama_model = "llama3.2"

# VM resources (increase for better performance)
memory_mb = 4096
cpus      = 2

# Disk (20 GB minimum; llama3.2 takes ~2 GB)
disk_size_mb = 20480

# Set to false to skip model pre-pull and save build time (~15 min)
# The model will be downloaded on first boot instead
# skip_model_pull = false

# Output directory (relative to packer/)
output_dir = "../dist"
