from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "utils" / "run_research.py"
SPEC = importlib.util.spec_from_file_location("run_research", MODULE_PATH)
assert SPEC and SPEC.loader
rr = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = rr
SPEC.loader.exec_module(rr)


def test_parse_run_output():
    text = """
    ✓ CASE-00002 extractor=model:qwen redactions=3 109496 ms
    revision 585a98639d2e
    """
    parsed = rr.parse_run_output(text)
    assert parsed["pipeline_ms"] == 109496
    assert parsed["redactions"] == 3
    assert parsed["revision"] == "585a98639d2e"


def test_search_and_protection_parsing():
    text = """
    │ 1 │ CASE-00002 │ 0.44 │
    │ 2 │ CASE-00009 │ 0.41 │
    Top-1 preserved: True  Top-k overlap: 80.0%
    Protected vectors: 2816 B  wire envelope: 4132 B
    clinical_text clean/protected cosine: 0.9891
    """
    assert rr.parse_search_ranking(text) == ["CASE-00002", "CASE-00009"]
    p = rr.parse_protection(text)
    assert p["top1_preserved"] is True
    assert p["topk_overlap_pct"] == 80.0
    assert p["protected_vector_bytes"] == 2816
    assert p["wire_envelope_bytes"] == 4132
    assert p["clinical_text_cosine"] == 0.9891


def test_known_field_and_privacy_evaluation():
    evidence = {
        "demographics": {"age": 87, "sex": "Female"},
        "physical_examination": {
            "vitals": {
                "heart_rate": "115 bpm",
                "blood_pressure": "90/60 mmHg",
                "spo2": "88% on room air",
                "temperature": "38.5 C",
            }
        },
        "assessment": {"diagnosis": "Pneumonia"},
    }
    gt = {
        "demographics": {"age": 87, "sex": "Female"},
        "vitals": {"HR": 115, "BP": "90/60 mmHg", "SpO2": 88, "Temp": 38.5},
        "hidden_diagnosis_label": "Pneumonia",
        "privacy_canaries": {
            "patient_id": "patient00002",
            "mrn": "SYN-38F4E2E0",
            "email": "patient.38f4e2e0@example.test",
        },
    }
    checks = rr.evaluate_known_fields(evidence, gt)
    assert all(checks.values())
    assert rr.privacy_leaks(evidence, gt) == []

    raw = {"patient": "patient00002", "diagnosis": "Pneumonia"}
    assert rr.privacy_leaks(raw, gt) == ["patient00002"]


def test_latest_derived_dir(tmp_path: Path):
    root = tmp_path / ".aethelgard" / "derived" / "CASE-00001"
    a = root / "aaa"
    b = root / "bbb"
    a.mkdir(parents=True)
    b.mkdir()
    (a / "evidence.json").write_text("{}")
    (b / "evidence.json").write_text("{}")
    a.touch()
    b.touch()
    assert rr.latest_derived_dir(tmp_path, "CASE-00001") in {a, b}
