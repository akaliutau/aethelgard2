#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/_common.sh
source "${SCRIPT_DIR}/_common.sh"
load_aethelgard_deploy_env

value="${HF_TOKEN:-}"
if [[ -n "$value" ]]; then
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' EXIT
  chmod 600 "$tmp"
  printf '%s' "$value" > "$tmp"

  if secret_exists "$HF_SECRET_NAME"; then
    printf '[secret] adding version: %s <- HF_TOKEN\n' "$HF_SECRET_NAME"
    gcloud secrets versions add "$HF_SECRET_NAME" \
      --data-file="$tmp" --project="$PROJECT_ID" >/dev/null
  else
    printf '[secret] creating: %s <- HF_TOKEN\n' "$HF_SECRET_NAME"
    gcloud secrets create "$HF_SECRET_NAME" \
      --replication-policy=automatic \
      --data-file="$tmp" \
      --project="$PROJECT_ID" >/dev/null
  fi

  rm -f "$tmp"
  trap - EXIT
elif secret_exists "$HF_SECRET_NAME"; then
  printf '[secret] reusing existing: %s\n' "$HF_SECRET_NAME"
else
  printf 'ERROR: HF_TOKEN is unset and secret %s does not exist.\n' "$HF_SECRET_NAME" >&2
  exit 1
fi

gcloud secrets add-iam-policy-binding "$HF_SECRET_NAME" \
  --project="$PROJECT_ID" \
  --member="serviceAccount:${SA}" \
  --role='roles/secretmanager.secretAccessor' >/dev/null

printf '\nSecret ready. Value was not printed.\n'
printf 'Next: scripts/deploy.sh\n'
