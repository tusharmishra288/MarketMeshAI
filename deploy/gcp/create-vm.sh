#!/bin/bash
# =============================================================================
# MarketMesh AI — Create GCP e2-micro VM (Always Free eligible)
#
# Prerequisites:
#   - gcloud CLI installed and authenticated  (gcloud auth login)
#   - A GCP project with Compute Engine API enabled
#   - Edit the variables below OR export them as environment variables before
#     running (environment variables take precedence over the defaults below)
#
# Usage:
#   chmod +x deploy/gcp/create-vm.sh
#
#   # Option A — edit variables in this file, then:
#   ./deploy/gcp/create-vm.sh
#
#   # Option B — pass via environment variables:
#   GCP_PROJECT_ID=my-project GITHUB_USERNAME=myuser ./deploy/gcp/create-vm.sh
#
# After the VM is ready:
#   1. Configure your GitHub Secrets (Settings → Secrets and variables → Actions):
#      - GCP_VM_IP, GCP_VM_USER, GCP_SSH_KEY   (deployment)
#      - FINNHUB_API_KEY, ALPHA_VANTAGE_KEY, MARKETAUX_API_KEY,
#        FRED_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, GCP_PROJECT_ID  (app)
#
#   2. Push to main — GitHub Actions writes .env on the VM and deploys.
#      No manual .env transfer needed.
#
# Free-tier constraints honoured:
#   - Machine type  : e2-micro (0.25 vCPU burst / 1 GB RAM)
#   - Region/Zone   : us-central1-a  (us-central1, us-east1, us-west1 are free)
#   - Disk          : 30 GB standard persistent disk (free allowance = 30 GB HDD)
#   - Network       : 1 GB egress to NA/EU per month included
# =============================================================================

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
# Edit the defaults here, OR export the variable before running the script
# (exported env vars always take precedence).
PROJECT_ID="${GCP_PROJECT_ID:-your-gcp-project-id}"     # gcloud config get-value project
GITHUB_USERNAME="${GITHUB_USERNAME:-YOUR_GITHUB_USERNAME}"  # your GitHub username for MarketMeshAI repo
VM_NAME="marketmesh-vm"
ZONE="us-central1-a"                       # must be us-central1, us-east1, or us-west1
DISK_SIZE="30"                             # GB — free tier allows 30 GB standard HDD
# ─────────────────────────────────────────────────────────────────────────────

# Validate required values
if [[ "$PROJECT_ID" == "your-gcp-project-id" ]]; then
  echo "ERROR: Set GCP_PROJECT_ID env var or edit PROJECT_ID in this script before running."
  exit 1
fi
if [[ "$GITHUB_USERNAME" == "YOUR_GITHUB_USERNAME" ]]; then
  echo "ERROR: Set GITHUB_USERNAME env var or edit GITHUB_USERNAME in this script before running."
  exit 1
fi

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

# ── Reserve a static IP (prevents GCP_VM_IP secret from going stale) ─────────
STATIC_IP_NAME="marketmesh-ip"
if ! gcloud compute addresses describe "$STATIC_IP_NAME" \
      --region="${ZONE%-*}" --project="$PROJECT_ID" &>/dev/null; then
  echo "Reserving static IP ($STATIC_IP_NAME)..."
  gcloud compute addresses create "$STATIC_IP_NAME" \
    --region="${ZONE%-*}" --project="$PROJECT_ID"
  # Attach the static IP to the VM
  gcloud compute instances delete-access-config "$VM_NAME" \
    --access-config-name="External NAT" --zone="$ZONE" --project="$PROJECT_ID" || true
  gcloud compute instances add-access-config "$VM_NAME" \
    --access-config-name="External NAT" \
    --address="$(gcloud compute addresses describe "$STATIC_IP_NAME" \
                 --region="${ZONE%-*}" --project="$PROJECT_ID" --format='get(address)')" \
    --zone="$ZONE" --project="$PROJECT_ID"
  echo "Static IP assigned."
else
  echo "Static IP already exists, skipping."
fi

# ── Firewall rules ────────────────────────────────────────────────────────────
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
echo "  External IP : $EXTERNAL_IP  (static — won't change on restart)"
echo "  SSH         : gcloud compute ssh $VM_NAME --zone=$ZONE"
echo ""
echo " Check startup log after SSH:"
echo "  tail -f /var/log/marketmesh-startup.log"
echo ""
echo " Next: configure GitHub Secrets and push to main to deploy."
echo ""
echo " GitHub Secrets to add (Settings → Secrets and variables → Actions):"
echo "  ── Deployment ─────────────────────────────────────────────────"
echo "  GCP_VM_IP          = $EXTERNAL_IP"
echo "  GCP_VM_USER        = <your-gcp-os-username>"
echo "  GCP_SSH_KEY        = <private key, see README for steps>"
echo "  ── Application (copy from your local .env) ─────────────────────"
echo "  FINNHUB_API_KEY    = <value>"
echo "  ALPHA_VANTAGE_KEY  = <value>"
echo "  MARKETAUX_API_KEY  = <value>"
echo "  FRED_API_KEY       = <value>"
echo "  GROQ_API_KEY       = <value>"
echo "  GEMINI_API_KEY     = <value>"
echo "  GCP_PROJECT_ID     = $PROJECT_ID"
echo ""
echo " App URLs (after first GitHub Actions deploy):"
echo "  Frontend : http://$EXTERNAL_IP:8501"
echo "  API docs : http://$EXTERNAL_IP:8000/docs"
echo "  Health   : http://$EXTERNAL_IP:8000/health"
echo "================================================================"
