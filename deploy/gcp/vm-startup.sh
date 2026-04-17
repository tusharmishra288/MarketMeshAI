#!/bin/bash
# =============================================================================
# MarketMesh AI — GCP e2-micro VM startup script
#
# This script is passed as --metadata-from-file=startup-script when creating
# the VM (see create-vm.sh). It runs once automatically on the first boot.
#
# What it does:
#   1. Creates a 2 GB swap file (critical for 1 GB RAM instance)
#   2. Installs Docker + Docker Compose plugin
#   3. Clones the MarketMeshAI GitHub repository to /opt/marketmesh
#   4. Prints next-step instructions to the startup log
#
# After the VM is ready:
#   1. Transfer your local .env to the VM (it is .gitignore'd, not in the repo):
#        gcloud compute scp .env marketmesh-vm:/opt/marketmesh/.env \
#          --zone=us-central1-a
#   2. Then SSH in and start the app:
#        gcloud compute ssh marketmesh-vm --zone=us-central1-a
#        cd /opt/marketmesh
#        docker compose -f docker-compose-gcp.yml up -d
# =============================================================================

set -euo pipefail
exec > /var/log/marketmesh-startup.log 2>&1

echo "=== MarketMesh AI: VM startup $(date) ==="

# ── 1. Swap (2 GB) ────────────────────────────────────────────────────────────
echo "--- Configuring 2 GB swap ---"
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "Swap enabled: $(swapon --show)"
else
  echo "Swap already exists, skipping."
fi

# Tune swappiness for low-RAM server (prefer swap only under real pressure)
sysctl -w vm.swappiness=10
echo 'vm.swappiness=10' >> /etc/sysctl.conf

# ── 2. Docker ─────────────────────────────────────────────────────────────────
echo "--- Installing Docker ---"
apt-get update -y
apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg git nginx certbot python3-certbot-nginx

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable docker
systemctl start docker

# Allow the default GCP user to run docker without sudo
DEFAULT_USER=$(getent passwd 1000 | cut -d: -f1 || echo "ubuntu")
usermod -aG docker "$DEFAULT_USER" || true
echo "Docker installed: $(docker --version)"

# ── 3. Clone repository ───────────────────────────────────────────────────────
echo "--- Cloning MarketMeshAI repository ---"
REPO_URL="https://github.com/$(curl -sf http://metadata.google.internal/computeMetadata/v1/instance/attributes/github-owner \
  -H 'Metadata-Flavor: Google' 2>/dev/null || echo 'YOUR_GITHUB_USERNAME')/MarketMeshAI.git"

if [ -d /opt/marketmesh/.git ]; then
  echo "Repo already cloned, pulling latest."
  git -C /opt/marketmesh pull origin main || true
else
  git clone "$REPO_URL" /opt/marketmesh || \
    git clone https://github.com/YOUR_GITHUB_USERNAME/MarketMeshAI.git /opt/marketmesh
fi

chown -R "$DEFAULT_USER":"$DEFAULT_USER" /opt/marketmesh

# ── 4. Next steps reminder ────────────────────────────────────────────────────
cat << 'EOF'
=======================================================================
MarketMesh AI VM setup complete!

NEXT STEPS:
  1.  Transfer your local .env to the VM (run this on your LOCAL machine):
        gcloud compute scp .env marketmesh-vm:/opt/marketmesh/.env --zone=us-central1-a

  2.  SSH in and start the app:
        gcloud compute ssh marketmesh-vm --zone=us-central1-a
        cd /opt/marketmesh && docker compose -f docker-compose-gcp.yml up -d

The first build takes ~8 minutes on e2-micro.
Logs: docker compose -f docker-compose-gcp.yml logs -f

Health check:  curl http://localhost:8000/health
Frontend:      http://<VM_EXTERNAL_IP>:8501
Backend API:   http://<VM_EXTERNAL_IP>:8000/docs
=======================================================================
EOF

echo "=== Startup script complete $(date) ==="
