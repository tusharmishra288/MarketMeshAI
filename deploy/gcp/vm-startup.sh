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
#   1. Configure all 10 GitHub Secrets in your repository
#      (Settings → Secrets and variables → Actions):
#
#      Deployment secrets:
#        GCP_VM_IP, GCP_VM_USER, GCP_SSH_KEY
#
#      Application secrets (written to .env on the VM by GitHub Actions):
#        FINNHUB_API_KEY, ALPHA_VANTAGE_KEY, MARKETAUX_API_KEY,
#        FRED_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, GCP_PROJECT_ID
#
#   2. Push to the main branch — GitHub Actions will:
#        a. SSH into this VM
#        b. Write /opt/marketmesh/.env from the secrets above
#        c. git pull + docker compose build + docker compose up -d
#
#   No manual .env transfer is required.
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

NEXT STEPS (all done from your LOCAL machine / GitHub, NOT the VM):

  1.  Add GitHub Secrets (Settings → Secrets and variables → Actions):

      Deployment:
        GCP_VM_IP          ← shown by create-vm.sh
        GCP_VM_USER        ← gcloud compute ssh marketmesh-vm --command="whoami"
        GCP_SSH_KEY        ← see README for ssh-keygen steps

      Application (GitHub Actions writes these to .env on this VM):
        FINNHUB_API_KEY
        ALPHA_VANTAGE_KEY
        MARKETAUX_API_KEY
        FRED_API_KEY
        GROQ_API_KEY
        GEMINI_API_KEY
        GCP_PROJECT_ID

  2.  Push to the main branch of your MarketMeshAI repo.
      GitHub Actions will SSH in, write .env from the secrets above,
      then run: docker compose -f docker-compose-gcp.yml up -d

The first build takes ~8 minutes on e2-micro.

Health check:  curl http://localhost:8000/health
Frontend:      http://<VM_EXTERNAL_IP>:8501
Backend API:   http://<VM_EXTERNAL_IP>:8000/docs
=======================================================================
EOF

echo "=== Startup script complete $(date) ==="
