#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/_common.sh
source "${SCRIPT_DIR}/_common.sh"
load_aethelgard_deploy_env

secret_exists "$HF_SECRET_NAME" || {
  printf 'ERROR: secret %s does not exist; run scripts/deploy_secrets.sh first.\n' "$HF_SECRET_NAME" >&2
  exit 1
}

MODELS="${QWEN_MODEL};${TEXT_MODEL};${IMAGE_MODEL}"
printf '[cache] image=%s bucket=gs://%s\n' "$IMAGE" "$MODEL_BUCKET"
printf '[cache] models=%s\n' "$MODELS"

gcloud run jobs deploy "$CACHE_JOB_NAME" \
  --image "$IMAGE" \
  --region "$REGION" \
  --service-account "$SA" \
  --command python \
  --args=-m,aethelgard.model_cache \
  --tasks 1 \
  --max-retries 1 \
  --cpu 2 \
  --memory 4Gi \
  --task-timeout 45m \
  --add-volume "mount-path=${MODEL_MOUNT},type=cloud-storage,bucket=${MODEL_BUCKET},readonly=false" \
  --set-env-vars "HF_HOME=${HF_HOME},HF_HUB_CACHE=${HF_HUB_CACHE},AETHELGARD_CACHE_MODELS=${MODELS}" \
  --set-secrets "HF_TOKEN=${HF_SECRET_NAME}:latest" \
  --project "$PROJECT_ID"

gcloud run jobs execute "$CACHE_JOB_NAME" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --wait

printf '\nModel cache ready at gs://%s\n' "$MODEL_BUCKET"
