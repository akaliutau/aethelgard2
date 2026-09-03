# Cloud Run

Use Cloud Run when you want the heavy semantic build to run on a GPU.

## Topology

```text
local Smart Folder
      │
      │ one dirty case
      ▼
Cloud Run worker (L4)
      │
      │ derived artifacts
      ▼
local semantic commit
```

Models are cached in a private GCS bucket and loaded by the worker in offline mode.

## Deploy

```bash
cp .env.cloud.example .env.cloud
# edit PROJECT_ID / REGION
```

```bash
ENV_FILE=.env.cloud scripts/deploy_infra.sh
ENV_FILE=.env.cloud scripts/deploy.sh
```

Deploy code without rebuilding the model cache:

```bash
SKIP_MODEL_CACHE=true \
ENV_FILE=.env.cloud \
scripts/deploy.sh
```

## Get the URL

```bash
WORKER_URL="$(
  gcloud run services describe aethelgard-vault-worker \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --format='value(status.url)'
)"
```

## Test

```bash
curl "$WORKER_URL/healthz"
```

```bash
aethelgard run CASE-00002 --remote "$WORKER_URL"
```

## Recommended demo profile

```text
GPU          NVIDIA L4
CPU          8
memory       32 GiB
concurrency  1
```

Keep request timeouts long enough for model initialization and generation.

## Warm before a demo

```bash
ENV_FILE=.env.cloud scripts/warm_service.sh --keep
```

Run one real synthetic case once. A health check does not load the full model stack.

After the demo:

```bash
ENV_FILE=.env.cloud scripts/warm_service.sh --cool
```

## Model cache

The current deployment uses a private GCS model cache so the runtime does not need to download gated models on every cold start.

Production direction:

```text
approved upstream snapshot
        ↓
private versioned GCS model registry
        ↓
read-only runtime service account
```

Keep model identity separate from storage path.

## Important

A public worker is suitable only for synthetic demo data.

Real PHI needs authenticated transport, access control, retention policy, and deployment-specific compliance controls.
