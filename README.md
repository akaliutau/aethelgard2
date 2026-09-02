# Aethelgard Vault

**Semantic Git for heterogeneous medical documents.**

Aethelgard turns an ordinary folder of medical evidence into a local, reproducible semantic vault. Drop in free-text EHR exports, PDFs, JSON/CSV/HL7-like text and medical images; Aethelgard discovers changes, groups artifacts into cases, uses a pluggable extractor to produce flexible clinical evidence, applies deterministic privacy policy, materializes optional multimodal embeddings, and versions the complete semantic state.

This version deliberately contains **no peer network, Pub/Sub federation, global query routing or orchestrator**. It does include a local search/protection layer that consumes committed vault artifacts. Networking remains a future access/transport layer. The vault is intended to remain useful and testable by itself, like Git remains useful without GitHub.

## The data flow

```text
working folder / cloud folder
        │
        ▼
     DISCOVER
        │ content hashes
        ▼
      GROUP
        │ case bundles
        ▼
       READ
        │ text + image parts
        ▼
 AI EVIDENCE EXTRACTOR
 Qwen3-4B + constrained JSON by default
        │ atomic facts → arbitrary nested JSON dictionary
        ▼
 DETERMINISTIC PRIVACY POLICY
        │
        ├──────────────► evidence.json
        │
        ▼
   MATERIALIZERS
        │
        ├── EmbeddingGemma → clinical text vector
        ├── EmbeddingGemma → evidence-fact vectors
        ├── MedSigLIP      → medical image vector
        └── weighted stack → multimodal vector
        │
        ▼
 SEMANTIC REVISION
 .aethelgard/derived/...
        │
        ├──────────────► aethelgard search
        │
        └──────────────► aethelgard protect
```

A case in the demo is intentionally simple:

```text
demo/
├── CASE-001/
│   ├── note.txt      # simulation of PDF→text / EHR text dump
│   └── chest.jpg
└── CASE-002/
    ├── note.txt
    └── chest.jpg
```

The evidence itself has **no rigid clinical schema**. One extractor may emit:

```json
{
  "presentation": {
    "symptoms": ["acute dyspnea", "pleuritic chest pain"],
    "oxygen_saturation": 87
  },
  "radiology": {
    "finding": "right-sided pneumothorax"
  },
  "interventions": [
    {"procedure": "tube thoracostomy", "response": "rapid improvement"}
  ]
}
```

Another hospital-specific plugin may use completely different keys. Only the Aethelgard envelopes/manifests are rigid.

---

## Install

For the complete local AI pipeline:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[models,pdf]"
```

For cloud-assisted execution as well:

```bash
pip install -e ".[all]"
```

The lightweight core deliberately does not require Torch. Commands such as `status`, `show`, `diff`, `log` and `verify` do not load model weights.

---

## Hugging Face model access and `GatedRepoError: 401`

The default extractor is now public and does **not** require gated-model approval:

- `Qwen/Qwen3-4B` — evidence extraction with constrained structured generation

The default multimodal materializers still use Google checkpoints:

- `google/embeddinggemma-300m` — clinical-text embeddings
- `google/medsiglip-448` — medical image embeddings

The Google checkpoints require accepting their corresponding terms on Hugging Face before the files can be downloaded. A token by itself is **not enough until the model terms have been accepted by that Hugging Face account**.

If you see an error such as:

```text
huggingface_hub.errors.GatedRepoError: 401 Client Error
Cannot access gated repo ... google/embeddinggemma-300m ...
```

### 1. Log into Hugging Face and accept access

Open these while logged into the account that owns your token:

```text
https://huggingface.co/google/embeddinggemma-300m
https://huggingface.co/google/medsiglip-448
```

Review and accept the requested terms for each model you intend to run.

### 2. Create a Hugging Face read token

Create a token in Hugging Face settings, then export it:

```bash
export HF_TOKEN='hf_...'
```

Aethelgard loads `.env` automatically, so this also works:

```bash
cp .env.example .env
# edit .env and set HF_TOKEN=hf_...
```

Never commit `.env` or the token.

### 3. Optional: save the token using the current Hugging Face CLI

```bash
hf auth login --token "$HF_TOKEN"
hf auth whoami
```

`HF_TOKEN` has priority over a token saved in the local Hugging Face cache, so it is the recommended mechanism for Docker/Cloud Run and reproducible environments.

### 4. Retry

```bash
aethelgard run
```

If one model still returns 401, open that **specific** model page and verify that its terms were accepted by the same account associated with `HF_TOKEN`.

---

# Git-like workflow

## 1. Initialize a vault

Copy the example data somewhere writable:

```bash
cp -R demo /tmp/my-med-vault
cd /tmp/my-med-vault
```

Initialize the full model profile:

```bash
aethelgard init
```

This creates only local metadata:

```text
.aethelgard/
├── config.toml
├── state.db
└── derived/
```

The directory is created with private filesystem permissions where supported.

For a zero-model architecture smoke test:

```bash
aethelgard init --profile smoke
```

`smoke` explicitly selects a deterministic regex extractor and disables embeddings; it is not an automatic fallback.

## 2. Inspect semantic status

```bash
aethelgard status
```

Example:

```text
+  CASE-001   new case
+  CASE-002   new case

2 case(s) require processing; 0 clean.
```

## 3. Process all dirty cases

```bash
aethelgard run
```

A full run performs:

1. free-text/image parsing;
2. Qwen3-4B evidence extraction with constrained JSON generation;
3. deterministic privacy validation/redaction;
4. EmbeddingGemma text embedding;
5. MedSigLIP image embedding;
6. normalized weighted multimodal stacking;
7. immutable semantic materialization;
8. semantic revision commit.

You can process one case:

```bash
aethelgard run CASE-001
```

## 4. Inspect exactly what AI extracted

```bash
aethelgard show CASE-001
```

This displays the privacy-reviewed evidence dictionary.

To inspect the model output *before* deterministic privacy filtering:

```bash
aethelgard show CASE-001 --view raw
```

Other useful views:

```bash
aethelgard show CASE-001 --view provenance
aethelgard show CASE-001 --view privac
aethelgard show CASE-001 --view derived
aethelgard show CASE-001 --view manifest
```

This is one of the intended competition demos: judges can literally inspect the local free-text record and then inspect the semantic representation produced from it.

## 5. Change a record

Edit `CASE-001/note.txt`, then:

```bash
aethelgard status
```

Aethelgard reports:

```text
M  CASE-001   source changed
```

Run it again and inspect how evidence changed:

```bash
aethelgard run CASE-001
aethelgard diff CASE-001
```

## 6. Change the semantic processor

Edit `.aethelgard/config.toml`, for example changing the extraction checkpoint or embedding profile, without touching the source documents.

Then:

```bash
aethelgard status
```

The case becomes dirty because its **semantic processor changed**, even though the source bytes are identical.

This is the defining SmartFolder behavior: Aethelgard tracks the semantic build state, not merely modification times.

## 7. Revision history and integrity

```bash
aethelgard log
aethelgard verify
```

`verify` checks the hashes of every currently materialized derived artifact against its manifest.

---

# Semantic fingerprint

The current semantic identity of a case depends on:

```text
source content hashes
+ reader versions
+ case resolver version
+ evidence extractor/model fingerprint
+ deterministic privacy-policy fingerprint
+ materializer/encoder fingerprints
+ multimodal fusion parameters
```

Changing any of these causes a semantic rebuild.

Derived artifacts are stored under:

```text
.aethelgard/derived/<CASE>/<semantic-fingerprint-prefix>/
```

Typical full-profile output:

```text
evidence.raw.json
evidence.json
provenance.json
privacy.json
embeddings.npz
embeddings.json
manifest.json
```

The working medical documents remain the source of truth; `.aethelgard` contains versioned semantic products and state.

---


# Search and vector protection

Search is a **consumer of committed vault artifacts**. It does not run Qwen and it does not change vault history.

After upgrading to v0.5, run:

```bash
aethelgard status
aethelgard run
```

once so each case receives the new search artifacts:

```text
evidence_facts.json
evidence_facts.npz
```

The case resolver also now uses the immediate parent directory, so a source layout such as
`demo/CASE-001/note.txt` and `demo/CASE-002/note.txt` remains two independent cases.

## Text search

```bash
aethelgard search \
  "spontaneous pneumothorax with hypoxemia; what treatment worked?"
```

The online path is deliberately lightweight:

```text
query text
    ↓
EmbeddingGemma query vector
    ↓
exact local cosine search
    ↓
rank matching cases
    ↓
rank precomputed evidence facts
    ↓
minimal relevant evidence summary
```

No generative model is called at query time.

## Multimodal search

Add an image:

```bash
aethelgard search \
  "find clinically and radiographically similar cases" \
  --image query.jpg
```

Aethelgard independently computes:

```text
clinical-text similarity
medical-image similarity
```

and combines them using the configured modality weights. The component scores are shown separately for explainability.

## Vector protection

```bash
aethelgard protect \
  "spontaneous pneumothorax with hypoxemia" \
  --image query.jpg \
  --output protected-query.json
```

Protection occurs **after local query encoding**. Local search can use clean vectors; a future transport layer can receive only the protected envelope.

The current reference protector applies independent normalized Gaussian perturbation to text and image vectors and serializes them as float16/Base64. The envelope contains no raw query text and no raw query image bytes.

This is **empirical vector perturbation, not encryption and not a proof that inversion is impossible**.

The default sigmas are intentionally conservative starting values (`text=0.01`, `image=0.02`). They are experiment parameters, not privacy guarantees; use `--compare-protection` and synthetic benchmark queries to tune the privacy/utility curve.

For reproducible experiments:

```bash
aethelgard protect "pneumothorax" --seed 42
```

## Privacy / utility experiment

The GOAI-oriented demo command is:

```bash
aethelgard search \
  "spontaneous pneumothorax with hypoxemia; what treatment worked?" \
  --image query.jpg \
  --compare-protection \
  --seed 42
```

It runs the same query twice:

```text
clean vector      → local vault search
protected vector  → local vault search simulating an external peer
```

and reports:

```text
clean ranking
protected ranking
Top-1 preservation
Top-k overlap
clean/protected cosine by modality
relevant evidence facts
```

This provides an empirical privacy/utility measurement before any networking code exists.

The two search-layer ports intended for future federation are especially important:

```python
class QueryEncoder(Protocol): ...
class VectorProtector(Protocol): ...
class SearchIndex(Protocol): ...
class EvidenceSelector(Protocol): ...
```

A future transport package should consume the protected query envelope; it should not be added to the vault pipeline.

---

# Models and extension boundaries

Aethelgard deliberately separates the medical task from the runtime.

## Evidence extraction

Protocol:

```python
class EvidenceExtractor(Protocol):
    @property
    def fingerprint(self) -> str: ...
    def extract(self, bundle: CaseBundle, context: ExtractionContext) -> Extraction: ...
```

Default:

```text
StructuredEvidenceExtractor
    ↓
QwenStructuredModel
    ↓
Qwen/Qwen3-4B
    ↓
Outlines constrained generation
    ↓
atomic semantic facts
    ↓
deterministic facts_to_evidence()
    ↓
flexible evidence dictionary
```

The model is not asked to invent an arbitrary JSON tree directly. It emits a constrained list of atomic facts such as `presentation.symptoms = dyspnea`; Aethelgard deterministically assembles repeated dot-path facts into the final schema-free nested evidence dictionary. This keeps the evidence schema flexible while making the model-output contract much more reliable.

The same protocol can later host:

```text
Qwen3-1.7B / Qwen3-8B
MedGemma 1.5 4B / 27B
Phi-4-mini
fine-tuned FunctionGemma
FHIR deterministic extractor
hospital-specific Python extractor
```

FunctionGemma remains useful as a future fine-tuned edge experiment, but the 270M base checkpoint is no longer the default because zero-shot heterogeneous EHR extraction proved too brittle.

## Multimodal materialization

Text:

```text
privacy-reviewed evidence.json
    ↓
EmbeddingGemma
    ↓
256-d clinical vector
```

Image:

```text
one or more JPG images
    ↓
MedSigLIP
    ↓
medical image vector(s)
    ↓ mean normalized pooling
```

Fusion:

```text
sqrt(text_weight)  × normalized(text)
       STACK
sqrt(image_weight) × normalized(image)
```

The default weights are 0.45 text / 0.55 medical image and are part of the semantic fingerprint.

Local search and vector protection are implemented as consumers of the vault. Federation is intentionally **not implemented**. The future transport layer should send the protected query envelope and execute the same search interface at the destination.

---

# Plugins

The core is Protocol-driven rather than inheritance-driven. External packages can register normal Python entry points, for example:

```toml
[project.entry-points."aethelgard.extractors"]
hospital-x = "hospital_x.extractor:HospitalExtractor"
```

Extractor entry points are factories with one argument: the validated `ExtractorConfig`. For example:

```python
def create(config):
    return MyHospitalExtractor(model=config.model)
```

The factory must return an object satisfying `EvidenceExtractor`. A plugin does not inherit from an Aethelgard base class. Future plugin groups can use the same pattern for readers, policies, materializers and sources.

---

# Local folders and cloud folders

Storage location is independent from compute location.

A local vault can use a normal working tree:

```bash
aethelgard init --source .
```

Or it can maintain its local semantic state while reading documents through `fsspec` from a cloud path:

```bash
pip install -e ".[gcs,models]"
aethelgard init --source gs://my-bucket/clinical-demo
```

For a deliberately public synthetic bucket:

```bash
aethelgard init \
  --source gs://public-demo-bucket/records \
  --anonymous
```

The current cloud-source implementation uses `fsspec`; GCS support is supplied by optional `gcsfs`. Future S3/Azure adapters do not require changes to the vault pipeline.

---

# Cloud-assisted model execution

Heavy models should not force every judge/user to own powerful local hardware.

Aethelgard therefore separates:

```text
WHERE DOCUMENTS LIVE
from
WHERE SEMANTIC PROCESSING RUNS
```

Normal local processing:

```bash
aethelgard run
```

Credential-free remote processing against an Aethelgard worker:

```bash
aethelgard run --remote https://YOUR-WORKER.run.app
```

The CLI:

1. computes which cases are dirty;
2. packages only those source artifacts plus the semantic configuration;
3. uploads the job to the worker;
4. the worker runs the exact same extractor/policy/materializer pipeline;
5. derived artifacts are returned as a ZIP response;
6. the local CLI verifies/commits them into the local `.aethelgard` vault.

The judge therefore needs **no GCP credentials and no Hugging Face token** when using your already-configured remote worker. The worker owns the model credentials.

The HTTP executor is intended for small competition/synthetic documents. Do **not** expose a public unauthenticated worker for real PHI.

## Run the worker locally

```bash
pip install -e ".[all]"
export HF_TOKEN=hf_...
aethelgard worker --host 0.0.0.0 --port 8080
```

Then from another machine/vault:

```bash
aethelgard run --remote http://SERVER:8080
```

The worker caches heavyweight model objects in-process across requests.

---

# Cloud Run reference deployment

The supplied `Dockerfile` runs the same worker service. The image intentionally does not bake a Hugging Face token into a Docker layer.

A typical deployment is:

```bash
gcloud run deploy aethelgard-vault-worker \
  --source . \
  --region YOUR_REGION \
  --memory 16Gi \
  --cpu 4 \
  --timeout 900 \
  --set-secrets HF_TOKEN=HF_TOKEN:latest
```

For a public competition worker you may additionally configure unauthenticated invocation in Cloud Run IAM. Keep at least one warm instance if model cold-start latency matters.

The heavy components are Qwen3-4B and MedSigLIP; CPU-only operation is supported by the architecture but can be slow. For a fast public demo, use a sufficiently provisioned cloud worker. If local latency matters more than extraction quality, configure `Qwen/Qwen3-1.7B` without changing the extractor architecture.

Again: the public worker should accept **synthetic/non-sensitive demo data only** unless you add appropriate authentication, retention controls and healthcare-compliance measures.

---

# Current CLI surface

The user-facing vault commands are intentionally small:

```text
init      create a semantic vault
status    show semantic working-tree state
run       process dirty cases locally or through an execution backend
show      inspect evidence/provenance/privacy/derived products
diff      compare the two latest semantic evidence revisions
log       show semantic revision history
verify    verify derived-artifact integrity
search    rank local semantic cases and relevant evidence
protect   create/inspect a protected future-transport query envelope
```

The hidden `worker` command is an operational deployment entry point, not part of the normal vault workflow.

---

# What is deliberately outside this version

Not implemented here:

- peer discovery;
- GCP Pub/Sub federation;
- network query routing;
- global search;
- consensus;
- actual network transport of protected vectors;
- remote hospital-node protocols.

Those should become a separate package/layer later and consume only public vault interfaces/derived artifacts.

The intended dependency direction is:

```text
future aethelgard-network
          │
          ▼
     VaultCatalog
          │
          ▼
   Aethelgard Vault
```

—not the reverse.

---

# Competition demo sequence

A compact live demo can be only six commands:

```bash
cp -R demo /tmp/aethelgard-demo
cd /tmp/aethelgard-demo

aethelgard init
aethelgard status
aethelgard run --remote https://YOUR-WORKER.run.app
aethelgard show CASE-001
aethelgard show CASE-001 --view provenance
aethelgard show CASE-001 --view derived
aethelgard search "spontaneous pneumothorax with hypoxemia; what treatment worked?"
aethelgard search "similar radiographic case" --image CASE-001/chest.jpg --compare-protection --seed 42
aethelgard protect "similar radiographic case" --image CASE-001/chest.jpg --output protected-query.json
```

Then edit `CASE-001/note.txt` and show:

```bash
aethelgard status
aethelgard run --remote https://YOUR-WORKER.run.app
aethelgard diff CASE-001
```

This demonstrates the complete idea without any networking architecture diagram: **drop medical documents → understand them → inspect evidence → generate multimodal artifacts → search them → measure clean-vs-protected retrieval → track semantic changes reproducibly.**
