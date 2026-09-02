#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/_common.sh
source "${SCRIPT_DIR}/_common.sh"
load_aethelgard_deploy_env

MODE="${1:-warm}"
if [[ "$MODE" == '--cool' || "$MODE" == 'cool' ]]; then
  gcloud run services update "$SERVICE_NAME" \
    --region "$REGION" --project "$PROJECT_ID" --min 0 >/dev/null
  printf 'Scale-to-zero restored for %s.\n' "$SERVICE_NAME"
  exit 0
fi

if [[ "$MODE" == '--keep' || "$MODE" == 'keep' ]]; then
  printf '[warm] keeping one instance warm after this request\n'
  gcloud run services update "$SERVICE_NAME" \
    --region "$REGION" --project "$PROJECT_ID" --min 1 >/dev/null
fi

URL="$(service_url)"
tmp="$(mktemp --suffix=.zip)"
trap 'rm -f "$tmp"' EXIT

QWEN_MODEL="$QWEN_MODEL" TEXT_MODEL="$TEXT_MODEL" IMAGE_MODEL="$IMAGE_MODEL" OUT="$tmp" python - <<'PY'
import base64
import json
import os
import zipfile
from pathlib import Path

# Valid 1x1 JPEG; enough to force the image encoder to load.
jpeg = base64.b64decode(
    '/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/EH//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EH//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EH//2Q=='
)

job = {
    'config': {
        'source': {'kind': 'local', 'uri': '.', 'anonymous': False},
        'extractor': {
            'kind': 'qwen',
            'model': os.environ['QWEN_MODEL'],
            'device': 'cpu',
            'max_new_tokens': 256,
        },
        'embeddings': {
            'enabled': True,
            'text_model': os.environ['TEXT_MODEL'],
            'text_dimensions': 256,
            'image_model': os.environ['IMAGE_MODEL'],
            'device': 'cpu',
            'text_weight': 0.45,
            'image_weight': 0.55,
        },
    },
    'case_ids': ['CASE-WARM'],
}

with zipfile.ZipFile(Path(os.environ['OUT']), 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.writestr('job.json', json.dumps(job))
    zf.writestr(
        'source/CASE-WARM/note.txt',
        'Synthetic warm-up case. Diagnosis: mild atelectasis. Treatment: observation. Outcome: stable.',
    )
    zf.writestr('source/CASE-WARM/chest.jpg', jpeg)
PY

printf '[warm] POST %s/v1/process\n' "$URL"
headers=(-H 'content-type: application/zip')
if [[ "$PUBLIC" != 'true' ]]; then
  token="$(gcloud auth print-identity-token)"
  headers+=(-H "Authorization: Bearer ${token}")
fi
http_code="$(curl -sS -o /tmp/aethelgard-warm-response.zip -w '%{http_code}' \
  "${headers[@]}" \
  --data-binary "@${tmp}" \
  "${URL}/v1/process")"

if [[ "$http_code" != '200' ]]; then
  printf 'Warm-up failed with HTTP %s\n' "$http_code" >&2
  cat /tmp/aethelgard-warm-response.zip >&2 || true
  exit 1
fi

rm -f /tmp/aethelgard-warm-response.zip
printf 'Warm-up complete. Models are loaded in the active instance.\n'
if [[ "$MODE" != '--keep' && "$MODE" != 'keep' ]]; then
  printf 'Service may scale to zero. For a live demo use: %s --keep\n' "$0"
fi
