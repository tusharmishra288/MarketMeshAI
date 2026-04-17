#!/bin/bash
# =============================================================================
# MarketMesh AI — Create GCP e2-micro VM (Always Free eligible)
#
# Prerequisites:
#   - gcloud CLI installed and authenticated  (gcloud auth login)
#   - A GCP project with Compute Engine API enabled
#   - Edit the variables below before running
#
# Usage:
#   chmod +x deploy/gcp/create-vm.sh
#   ./deploy/gcp/create-vm.sh
#
# Free-tier constraints honoured:
#   - Machine type  : e2-micro (0.25 vCPU burst / 1 GB RAM)
#   - Region/Zone   : us-central1-a  (us-central1, us-east1, us-west1 are free)
#   - Disk          : 30 GB standard persistent disk (free allowance = 30 GB HDD)
#   - Network       : 1 GB egress to NA/EU per month included
# =============================================================================

set -euo pipefail

# ── Configuration — edit these ────────────────────────────────────────────────
PROJECT_ID="your-gcp-project-id"           # gcloud config get-value project
VM_NAME="marketmesh-vm"
ZONE="us-central1-a"                       # must be us-central1, us-east1, or us-west1
GITHUB_USERNAME="YOUR_GITHUB_USERNAME"     # your GitHub username for the MarketMeshAI repo
DISK_SIZE="30"                             # GB — free tier allows 30 GB standard HDD
# ─────────────────────────────────────────────────────────────────────────────

echo "Creating VM: $VM_NAME in $ZONE (project: $PROJECT_ID)"

# ── Create the VM ─────────────────────────────────────────────────────────────
gcloud compute instances create "$VM_NAME" \
  --project="$PROJECT_ID" \
  --zone="$ZONE" \
  --machine-type=e2-micro \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size="${DISK_SIZE}GB" \
  --boot-disk-type=pd-standard \
  --boot-disk-device-name="$VM_NAME" \
  --network-interface=network-tier=PREMIUM,subnet=default \
  --maintenance-policy=MIGRATE \
  --tags=marketmesh-server \
  --metadata="github-owner=${GITHUB_USERNAME}" \
  --metadata-from-file=startup-script=deploy/gcp/vm-startup.sh \
  --scopes=https://www.googleapis.com/auth/cloud-platform

echo "VM created. Waiting for startup script to complete (~3 min)..."

# ── Firestore: enable API and grant IAM role to VM service account ────────────
echo "--- Enabling Firestore API ---"
gcloud services enable firestore.googleapis.com --project="$PROJECT_ID" || true

# Get the Compute Engine default service account email
SA_EMAIL=$(gcloud iam service-accounts list \
  --project="$PROJECT_ID" \
  --filter="displayName:Compute Engine default service account" \
  --format="value(email)" 2>/dev/null || \
  echo "${PROJECT_ID}-compute@developer.gserviceaccount.com")

echo "Granting Firestore access to service account: $SA_EMAIL"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/datastore.user" \
  --quiet || true

# Create Firestore database in Native mode (one-time per project)
gcloud firestore databases create \
  --project="$PROJECT_ID" \
  --location=nam5 \
  --type=firestore-native 2>/dev/null || \
  echo "Firestore database already exists or creation skipped."

echo "Firestore ready."

# ── Firewall rules ────────────────────────────────────────────────────────────
# Check if rule already exists
if ! gcloud compute firewall-rules describe allow-marketmesh \
      --project="$PROJECT_ID" &>/dev/null; then
  echo "Creating firewall rules..."
  gcloud compute firewall-rules create allow-marketmesh \
    --project="$PROJECT_ID" \
    --direction=INGRESS \
    --priority=1000 \
    --network=default \
    --action=ALLOW \
    --rules=tcp:80,tcp:443,tcp:8000,tcp:8501 \
    --source-ranges=0.0.0.0/0 \
    --target-tags=marketmesh-server
  echo "Firewall rules created."
else
  echo "Firewall rule already exists, skipping."
fi

# ── Fetch external IP ─────────────────────────────────────────────────────────
EXTERNAL_IP=$(gcloud compute instances describe "$VM_NAME" \
  --project="$PROJECT_ID" \
  --zone="$ZONE" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

echo ""
echo "================================================================"
echo " VM ready!"
echo "  External IP : $EXTERNAL_IP"
echo "  SSH         : gcloud compute ssh $VM_NAME --zone=$ZONE"
echo ""
echo " After SSH, check startup log:"
echo "  tail -f /var/log/marketmesh-startup.log"
echo ""
echo " Then transfer .env and start:"
echo "  # On your LOCAL machine (not the VM):"
echo "  gcloud compute scp .env marketmesh-vm:/opt/marketmesh/.env --zone=$ZONE"
echo ""
echo "  # Then SSH in:"
echo "  gcloud compute ssh marketmesh-vm --zone=$ZONE"
echo "  cd /opt/marketmesh && docker compose -f docker-compose-gcp.yml up -d"
echo ""
echo " App URLs (after startup):"
echo "  Frontend : http://$EXTERNAL_IP:8501"
echo "  API docs : http://$EXTERNAL_IP:8000/docs"
echo "  Health   : http://$EXTERNAL_IP:8000/health"
echo "================================================================"
