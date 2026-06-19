packer {
  required_version = ">= 1.10"
  required_plugins {
    virtualbox = {
      version = ">= 1.0.0"
      source  = "github.com/hashicorp/virtualbox"
    }
    qemu = {
      version = ">= 1.1.0"
      source  = "github.com/hashicorp/qemu"
    }
  }
}

# ── Variables ─────────────────────────────────────────────────────────────────

variable "ubuntu_iso_url" {
  description = "Ubuntu 24.04 Server ISO URL"
  default     = "https://releases.ubuntu.com/24.04.2/ubuntu-24.04.2-live-server-amd64.iso"
}

variable "ubuntu_iso_checksum" {
  description = "SHA256 checksum of the ISO"
  default     = "sha256:d6dab0c3a657988501b4bd76f1297c053df710e06e0c3aece60dead24f270b4d"
}

variable "vm_name" {
  default = "llmos"
}

variable "disk_size_mb" {
  description = "VM disk size in MB (default 20 GB)"
  default     = 20480
}

variable "memory_mb" {
  description = "VM RAM in MB (default 4 GB)"
  default     = 4096
}

variable "cpus" {
  default = 2
}

variable "ollama_model" {
  description = "Ollama model to pre-pull"
  default     = "llama3.2"
}

variable "ssh_username" {
  default = "llmos"
}

variable "ssh_password" {
  sensitive = true
  default   = "llmos"
}

variable "output_dir" {
  default = "../dist"
}

# ── Locals ────────────────────────────────────────────────────────────────────

locals {
  iso_target_path = "iso_cache/ubuntu-24.04.2-server-amd64.iso"
  boot_command_prefix = [
    "<wait3>",
    "c",
    "<wait>",
    "linux /casper/vmlinuz autoinstall ds=nocloud-net\\;s=http://{{ .HTTPIP }}:{{ .HTTPPort }}/ ",
    "--- <enter>",
    "<wait>",
    "initrd /casper/initrd <enter>",
    "<wait>",
    "boot <enter>"
  ]
}

# ── Sources ───────────────────────────────────────────────────────────────────

source "virtualbox-iso" "llmos" {
  vm_name          = var.vm_name
  iso_url          = var.ubuntu_iso_url
  iso_checksum     = var.ubuntu_iso_checksum
  iso_target_path  = local.iso_target_path

  disk_size        = var.disk_size_mb
  memory           = var.memory_mb
  cpus             = var.cpus
  guest_os_type    = "Ubuntu_64"
  guest_additions_mode = "disable"

  # Network: NAT (internet access for Ollama download)
  vboxmanage = [
    ["modifyvm", "{{.Name}}", "--natpf1", "ssh,tcp,,2222,,22"],
    ["modifyvm", "{{.Name}}", "--audio", "none"],
    ["modifyvm", "{{.Name}}", "--usb", "off"],
    ["modifyvm", "{{.Name}}", "--vram", "16"],
  ]

  # Boot into GRUB and inject autoinstall kernel parameters
  boot_wait    = "5s"
  boot_command = local.boot_command_prefix

  # HTTP server serves the user-data & meta-data from packer/http/
  http_directory = "${path.root}/http"

  # SSH connection (used by provisioners)
  ssh_username         = var.ssh_username
  ssh_password         = var.ssh_password
  ssh_timeout          = "60m"
  ssh_handshake_attempts = 100

  shutdown_command = "echo '${var.ssh_password}' | sudo -S shutdown -P now"

  # Export as OVA
  format           = "ova"
  output_directory = "${var.output_dir}/virtualbox"
  output_filename  = "${var.vm_name}"
}

source "qemu" "llmos" {
  vm_name          = "${var.vm_name}.qcow2"
  iso_url          = var.ubuntu_iso_url
  iso_checksum     = var.ubuntu_iso_checksum
  iso_target_path  = local.iso_target_path

  disk_size        = "${var.disk_size_mb}M"
  memory           = var.memory_mb
  cpus             = var.cpus

  accelerator      = "kvm"
  disk_interface   = "virtio"
  net_device       = "virtio-net"
  format           = "qcow2"

  http_directory   = "${path.root}/http"
  boot_wait        = "5s"
  boot_command     = local.boot_command_prefix

  ssh_username         = var.ssh_username
  ssh_password         = var.ssh_password
  ssh_timeout          = "60m"
  ssh_handshake_attempts = 100

  shutdown_command = "echo '${var.ssh_password}' | sudo -S shutdown -P now"

  output_directory = "${var.output_dir}/qemu"
}

# ── Build ─────────────────────────────────────────────────────────────────────

build {
  name    = "llmos"
  sources = [
    "source.virtualbox-iso.llmos",
    "source.qemu.llmos",
  ]

  # 1. Wait for cloud-init to fully complete
  provisioner "shell" {
    inline = [
      "echo '${var.ssh_password}' | sudo -S cloud-init status --wait",
      "echo '[packer] Cloud-init complete.'"
    ]
  }

  # 2. Upload the LLM-OS source tree
  provisioner "file" {
    source      = "${path.root}/../"
    destination = "/tmp/llmos-src"
    generated   = true
  }

  # 3. Install LLM-OS (Ollama + Python package + services)
  provisioner "shell" {
    environment_vars = [
      "LLMOS_MODEL=${var.ollama_model}",
      "DEBIAN_FRONTEND=noninteractive",
    ]
    execute_command  = "echo '${var.ssh_password}' | sudo -S bash -c '{{.Vars}} bash {{.Path}}'"
    script           = "${path.root}/scripts/provision.sh"
    timeout          = "60m"
  }

  # 4. Pre-pull the model inside the image (optional — can skip to reduce image size)
  provisioner "shell" {
    environment_vars = ["LLMOS_MODEL=${var.ollama_model}"]
    execute_command  = "echo '${var.ssh_password}' | sudo -S bash -c '{{.Vars}} bash {{.Path}}'"
    script           = "${path.root}/scripts/pull-model.sh"
    timeout          = "30m"
  }

  # 5. Clean up for smaller image size
  provisioner "shell" {
    execute_command = "echo '${var.ssh_password}' | sudo -S bash -c 'bash {{.Path}}'"
    script          = "${path.root}/scripts/cleanup.sh"
  }

  # Checksums
  post-processor "checksum" {
    checksum_types = ["sha256"]
    output         = "${var.output_dir}/{{.ChecksumType}}sums.txt"
  }

  # VirtualBox only: also produce a manifest
  post-processor "manifest" {
    output     = "${var.output_dir}/manifest.json"
    strip_path = true
  }
}
