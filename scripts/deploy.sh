#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/_common.sh
source "${SCRIPT_DIR}/_common.sh"
load_aethelgard_deploy_env

printf '[build] image=%s\n' "$IMAGE"
build_dir="$(mktemp -d)"
trap 'rm -rf "$build_dir"' EXIT
cp pyproject.toml README.md "$build_dir/"
cp -R aethelgard "$build_dir/aethelgard"
cp "${SCRIPT_DIR}/../deploy/cloudrun/Dockerfile" "$build_dir/Dockerfile"
gcloud builds submit --tag "$IMAGE" --project "$PROJECT_ID" "$build_dir"
rm -rf "$build_dir"
trap - EXIT

if [[ "${SKIP_MODEL_CACHE:-false}" != 'true' ]]; then
  IMAGE="$IMAGE" "${SCRIPT_DIR}/cache_models.sh"
fi

printf '[deploy] service=%s accelerator=%s cpu=%s memory=%s min=%s max=%s\n' \
  "$SERVICE_NAME" "$ACCELERATOR" "$CPU" "$MEMORY" "$MIN_INSTANCES" "$MAX_INSTANCES"

args=(
  gcloud run deploy "$SERVICE_NAME"
  --image "$IMAGE"
  --region "$REGION"
  --service-account "$SA"
  --port 8080
  --cpu "$CPU"
  --memory "$MEMORY"
  --timeout 900s
  --concurrency "$CONCURRENCY"
  --min "$MIN_INSTANCES"
  --max "$MAX_INSTANCES"
  --cpu-boost
  --execution-environment gen2
  --add-volume "mount-path=${MODEL_MOUNT},type=cloud-storage,bucket=${MODEL_BUCKET},readonly=true,mount-options=metadata-cache-ttl-secs=3600;stat-cache-max-size-mb=64;type-cache-max-size-mb=8"
  --set-env-vars "HF_HOME=${HF_HOME},HF_HUB_CACHE=${HF_HUB_CACHE},HF_HUB_OFFLINE=1,AETHELGARD_WORKER_DEVICE=${WORKER_DEVICE}"
  --project "$PROJECT_ID"
)

if [[ "$ACCELERATOR" == 'gpu' ]]; then
  args+=(
    --gpu 1
    --gpu-type "$GPU_TYPE"
    --no-gpu-zonal-redundancy
    --no-cpu-throttling
  )
fi

if [[ "$PUBLIC" == 'true' ]]; then
  args+=(--allow-unauthenticated)
else
  args+=(--no-allow-unauthenticated)
fi

"${args[@]}"

URL="$(service_url)"
printf '\nDeployed: %s\n' "$URL"
printf 'Warm now: ENV_FILE=%s %s/warm_service.sh\n' "${ENV_FILE:-.env.cloud}" "$SCRIPT_DIR"
printf 'Client:   aethelgard run --remote %s\n' "$URL"
