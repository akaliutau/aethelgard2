# Architecture

Aethelgard is built around one object: the **Smart Folder**.

```text
medical files
    ↓
extract clinical evidence
    ↓
apply deterministic privacy policy
    ↓
build text + image vectors
    ↓
commit semantic revision
```

## Core pipeline

```text
SOURCE
  ↓
READ / GROUP
  ↓
Qwen3-4B-Instruct-2507
  ↓
atomic clinical facts
  ↓
deterministic evidence assembly
  ↓
privacy policy
  ↓
EmbeddingGemma + MedSigLIP
  ↓
semantic revision
```

Current model stack:

```text
Qwen/Qwen3-4B-Instruct-2507   evidence extraction
google/embeddinggemma-300m   text / fact vectors
google/medsiglip-448          medical-image vectors
```

## Local vs remote

The vault owns the data and history. The executor only decides where processing runs.

```text
Local:
source → local pipeline → local commit

Remote:
source → HTTP GPU worker → derived artifacts → local commit
```

The Cloud Run worker is compute, not the repository.

## Semantic fingerprint

A case is dirty when the source or its interpretation pipeline changes:

```text
source hash
extractor/model
privacy policy
embedding models
fusion/materialization settings
```

That is why Aethelgard behaves like version control for semantic state.

## Search

Search consumes committed artifacts:

```text
query
  ↓
local query encoders
  ↓
cosine search
  ↓
ranked cases + relevant facts
```

Qwen is not called during search.

Protected search adds perturbation after local query encoding:

```text
clean vector → Gaussian perturbation → renormalize → protected vector
```

This is an empirical protection mechanism, not encryption or formal DP.
