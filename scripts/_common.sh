#!/usr/bin/env bash
set -euo pipefail

load_env_file() {
  local file="${ENV_FILE:-.env.cloud}"
  [[ -f "$file" ]] || return 0

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" == *"="* ]] || continue

    local key="${line%%=*}"
    local value="${line#*=}"
    key="$(printf '%s' "$key" | xargs)"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    [[ -n "${!key-}" ]] && continue

    value="${value#${value%%[![:space:]]*}}"
    value="${value%${value##*[![:space:]]}}"
    if [[ "$value" =~ ^\".*\"$ || "$value" =~ ^\'.*\'$ ]]; then
      value="${value:1:${#value}-2}"
    fi
    export "$key=$value"
  done < "$file"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'ERROR: required command is not installed: %s\n' "$1" >&2
    exit 1
  }
}

load_aethelgard_deploy_env() {
  load_env_file
  require_command gcloud

  PROJECT_ID="${PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}"
  PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID or GOOGLE_CLOUD_PROJECT}"
  REGION="${REGION:-us-central1}"
  REPOSITORY="${REPOSITORY:-aethelgard}"
  SERVICE_NAME="${SERVICE_NAME:-aethelgard-vault-worker}"
  CACHE_JOB_NAME="${CACHE_JOB_NAME:-aethelgard-model-cache}"
  SA_NAME="${SA_NAME:-aethelgard-worker}"
  SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
  MODEL_BUCKET="${MODEL_BUCKET:-${PROJECT_ID}-aethelgard-model-cache}"
  HF_SECRET_NAME="${HF_SECRET_NAME:-aethelgard-hf-token}"

  ACCELERATOR="${ACCELERATOR:-gpu}"
  MIN_INSTANCES="${MIN_INSTANCES:-0}"
  MAX_INSTANCES="${MAX_INSTANCES:-1}"
  CONCURRENCY="${CONCURRENCY:-1}"
  PUBLIC="${PUBLIC:-true}"

  QWEN_MODEL="${QWEN_MODEL:-Qwen/Qwen3-4B-Instruct-2507}"
  TEXT_MODEL="${TEXT_MODEL:-google/embeddinggemma-300m}"
  IMAGE_MODEL="${IMAGE_MODEL:-google/medsiglip-448}"
  MODEL_MOUNT="${MODEL_MOUNT:-/models}"
  HF_HOME="${HF_HOME:-${MODEL_MOUNT}/huggingface}"
  HF_HUB_CACHE="${HF_HUB_CACHE:-${HF_HOME}/hub}"

  TAG="${TAG:-latest}"
  IMAGE="${IMAGE:-${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/worker:${TAG}}"

  case "$ACCELERATOR" in
    gpu)
      CPU="${CPU:-8}"
      MEMORY="${MEMORY:-32Gi}"
      WORKER_DEVICE="${WORKER_DEVICE:-cuda}"
      GPU_TYPE="${GPU_TYPE:-nvidia-l4}"
      ;;
    cpu)
      CPU="${CPU:-8}"
      MEMORY="${MEMORY:-32Gi}"
      WORKER_DEVICE="${WORKER_DEVICE:-cpu}"
      GPU_TYPE=""
      ;;
    *)
      printf 'ERROR: ACCELERATOR must be gpu or cpu, got %s\n' "$ACCELERATOR" >&2
      exit 2
      ;;
  esac

  export PROJECT_ID REGION REPOSITORY SERVICE_NAME CACHE_JOB_NAME SA_NAME SA MODEL_BUCKET
  export HF_SECRET_NAME ACCELERATOR MIN_INSTANCES MAX_INSTANCES CONCURRENCY PUBLIC
  export QWEN_MODEL TEXT_MODEL IMAGE_MODEL MODEL_MOUNT HF_HOME HF_HUB_CACHE
  export TAG IMAGE CPU MEMORY WORKER_DEVICE GPU_TYPE
}

secret_exists() {
  gcloud secrets describe "$1" --project "$PROJECT_ID" >/dev/null 2>&1
}

service_url() {
  gcloud run services describe "$SERVICE_NAME" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --format='value(status.url)'
}
