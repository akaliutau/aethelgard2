#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/_common.sh
source "${SCRIPT_DIR}/_common.sh"
load_aethelgard_deploy_env

printf '[infra] project=%s region=%s service=%s cache=gs://%s\n' \
  "$PROJECT_ID" "$REGION" "$SERVICE_NAME" "$MODEL_BUCKET"

gcloud config set project "$PROJECT_ID" >/dev/null

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com \
  logging.googleapis.com \
  --project "$PROJECT_ID"

if ! gcloud artifacts repositories describe "$REPOSITORY" \
  --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPOSITORY" \
    --repository-format=docker \
    --location="$REGION" \
    --description='Aethelgard Cloud Run images' \
    --project="$PROJECT_ID"
fi

if ! gcloud iam service-accounts describe "$SA" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name='Aethelgard worker' \
    --project="$PROJECT_ID"
fi

BUILD_SA="$(gcloud builds get-default-service-account --project "$PROJECT_ID" 2>/dev/null || true)"
if [[ -n "$BUILD_SA" ]]; then
  gcloud artifacts repositories add-iam-policy-binding "$REPOSITORY" \
    --location="$REGION" \
    --member="serviceAccount:${BUILD_SA}" \
    --role='roles/artifactregistry.writer' \
    --project="$PROJECT_ID" >/dev/null
fi

if ! gcloud storage buckets describe "gs://${MODEL_BUCKET}" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${MODEL_BUCKET}" \
    --location="$REGION" \
    --default-storage-class=STANDARD \
    --uniform-bucket-level-access \
    --project="$PROJECT_ID"
fi

# The one-shot cache job writes the bucket; the service mounts the same bucket read-only.
gcloud storage buckets add-iam-policy-binding "gs://${MODEL_BUCKET}" \
  --member="serviceAccount:${SA}" \
  --role='roles/storage.objectUser' \
  --project="$PROJECT_ID" >/dev/null

printf '\nInfrastructure ready.\n'
printf '  Artifact Registry: %s-docker.pkg.dev/%s/%s\n' "$REGION" "$PROJECT_ID" "$REPOSITORY"
printf '  Model cache:       gs://%s\n' "$MODEL_BUCKET"
printf '  Runtime identity:  %s\n' "$SA"
printf 'Next: scripts/deploy_secrets.sh\n'
