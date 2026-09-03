# 🧮 Reproduce the Research Run

Generate the corpus:

```bash
python utils/prepare_research_dataset.py \
  dataset/Hospital_A \
  --images-root dataset/Hospital_A \
  --force
```

This creates:

```text
aethelgard-research/
├── vaults/mixed/
└── research/ground_truth.jsonl
```

Initialize and run:

```bash
cd aethelgard-research/vaults/mixed
aethelgard init

python /path/to/aethelgard/utils/run_research.py \
  --vault . \
  --remote "$WORKER_URL" \
  --ground-truth ../../research/ground_truth.jsonl
```

Notebook-ready outputs:

```text
.research/latest/
├── summary.json
├── cases.csv
├── search.csv
├── protection.csv
└── *.jsonl
```

All records were committed to this repository

