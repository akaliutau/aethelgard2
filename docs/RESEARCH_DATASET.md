# Research Dataset

Create the benchmark dataset with:

```bash
python utils/prepare_research_dataset.py \
  dataset/Hospital_A \
  --images-root dataset/Hospital_A \
  --force
```

Default output:

```text
aethelgard-research/
├── vaults/
│   ├── mixed/
│   └── by-format/
└── research/
    ├── ground_truth.jsonl
    ├── stats.json
    ├── dataset_manifest.json
    └── ground_truth/
```

For the current PoC, use only:

```text
aethelgard-research/vaults/mixed
```

The `research/` directory is ground truth and must **not** be inside the vault source.

## Images

Each generated case keeps the resolved source image filename:

```text
CASE-00002/
├── note.txt
└── <original-image-name>.jpg
```

`image_reference` in generated ground truth and manifest points to that copied filename.

## Privacy canaries

The generator injects deterministic synthetic identifiers:

```text
patient ID
synthetic MRN
example.test email
```

The benchmark checks whether they appear in:

```text
evidence.raw.json
evidence.json
```

This gives a reproducible privacy leakage signal without using real PHI.
