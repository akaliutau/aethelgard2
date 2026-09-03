#!/usr/bin/env python3
"""
Run a minimal end-to-end Aethelgard research benchmark.

Designed for a vault root that already contains:
    .aethelgard/
    CASE-00001/
    ...
    CASE-00030/

The runner intentionally does only the high-signal experiments:
1. process every case independently;
2. collect derived evidence + latency/reliability;
3. compare a few known ground-truth fields when ground_truth.jsonl is available;
4. measure synthetic privacy-canary leakage;
5. run diagnosis text retrieval;
6. run one fixed protected-query comparison per diagnosis.

Outputs are flat JSONL/CSV plus summary.json for later notebook analysis.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CASE_RE = re.compile(r"^CASE-\d+$")
PIPELINE_MS_RE = re.compile(r"(\d+)\s*ms\b")
REDACTIONS_RE = re.compile(r"\bredactions=(\d+)\b")
REVISION_RE = re.compile(r"(?m)^\s*revision\s+([0-9a-fA-F]+)\s*$")
SEARCH_ROW_RE = re.compile(r"│\s*(\d+)\s*│\s*(CASE-\d+)\s*│")
TOP1_RE = re.compile(r"Top-1 preserved:\s*(True|False)")
OVERLAP_RE = re.compile(r"Top-k overlap:\s*([0-9.]+)%")
WIRE_RE = re.compile(r"wire envelope:\s*(\d+)\s*B")
VECTOR_RE = re.compile(r"Protected vectors:\s*(\d+)\s*B")
COSINE_RE = re.compile(r"clinical_text clean/protected cosine:\s*([0-9.]+)")


@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    wall_ms: int
    stdout: str
    stderr: str
    timed_out: bool = False


def run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
) -> CommandResult:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandResult(
            command=command,
            returncode=proc.returncode,
            wall_ms=round((time.perf_counter() - started) * 1000),
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=command,
            returncode=124,
            wall_ms=round((time.perf_counter() - started) * 1000),
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
            timed_out=True,
        )


def case_ids(vault: Path) -> list[str]:
    return sorted(
        p.name for p in vault.iterdir()
        if p.is_dir() and CASE_RE.match(p.name)
    )


def load_ground_truth(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    result: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            cid = str(row.get("case_id", "")).strip()
            if cid:
                result[cid] = row
    return result


def discover_ground_truth(vault: Path) -> Path | None:
    candidates = [
        vault / "ground_truth.jsonl",
        vault.parent / "ground_truth.jsonl",
        vault.parent / "research" / "ground_truth.jsonl",
        vault.parent.parent / "research" / "ground_truth.jsonl",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def latest_derived_dir(vault: Path, case_id: str) -> Path | None:
    case_root = vault / ".aethelgard" / "derived" / case_id
    if not case_root.exists():
        return None
    dirs = [p for p in case_root.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime_ns)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def flatten_json(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            out.extend(flatten_json(child, child_prefix))
    elif isinstance(value, list):
        for child in value:
            out.extend(flatten_json(child, prefix))
    else:
        out.append((prefix, value))
    return out


def normalize_text(value: Any) -> str:
    text = str(value).lower().strip()
    text = text.replace("°", "")
    text = re.sub(r"\s+", " ", text)
    return text


def numeric_tokens(value: Any) -> list[str]:
    return re.findall(r"-?\d+(?:\.\d+)?", normalize_text(value))


def path_matches(path: str, aliases: Iterable[str]) -> bool:
    compact = path.lower().replace("-", "_").replace(" ", "_")
    return any(alias in compact for alias in aliases)


def any_value_match(
    flat: list[tuple[str, Any]],
    expected: Any,
    *,
    aliases: Iterable[str] | None = None,
    numeric: bool = False,
) -> bool:
    expected_norm = normalize_text(expected)
    expected_numbers = numeric_tokens(expected) if numeric else []
    candidates = flat
    if aliases:
        candidates = [(p, v) for p, v in flat if path_matches(p, aliases)]
    for _, value in candidates:
        value_norm = normalize_text(value)
        if expected_norm and expected_norm in value_norm:
            return True
        if numeric and expected_numbers:
            actual_numbers = numeric_tokens(value)
            if all(number in actual_numbers for number in expected_numbers):
                return True
    return False


def evaluate_known_fields(
    evidence: Any,
    gt: dict[str, Any] | None,
) -> dict[str, bool | None]:
    if not isinstance(evidence, (dict, list)) or not gt:
        return {}
    flat = flatten_json(evidence)
    demographics = gt.get("demographics") or {}
    vitals = gt.get("vitals") or {}

    checks: dict[str, bool | None] = {}

    if demographics.get("age") is not None:
        checks["age"] = any_value_match(
            flat, demographics["age"], aliases=("age",), numeric=True
        )
    if demographics.get("sex") is not None:
        checks["sex"] = any_value_match(
            flat, demographics["sex"], aliases=("sex", "gender")
        )

    vital_specs = [
        ("heart_rate", ("HR", "heart_rate", "heart rate"), ("heart_rate", ".hr"), True),
        ("blood_pressure", ("BP", "blood_pressure", "blood pressure"), ("blood_pressure", ".bp"), True),
        ("spo2", ("SpO2", "spo2", "oxygen_saturation"), ("spo2", "oxygen_saturation", "saturation"), True),
        ("temperature", ("Temp", "temperature"), ("temperature", ".temp"), True),
    ]
    for result_name, gt_keys, aliases, numeric in vital_specs:
        expected = next((vitals[k] for k in gt_keys if k in vitals), None)
        if expected is not None:
            checks[result_name] = any_value_match(
                flat, expected, aliases=aliases, numeric=numeric
            )

    diagnosis = gt.get("hidden_diagnosis_label")
    if diagnosis:
        checks["diagnosis"] = any_value_match(flat, diagnosis)

    return checks


def recursive_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for child in value.values():
            out.extend(recursive_strings(child))
        return out
    if isinstance(value, list):
        out: list[str] = []
        for child in value:
            out.extend(recursive_strings(child))
        return out
    return []


def privacy_leaks(document: Any, gt: dict[str, Any] | None) -> list[str]:
    if document is None or not gt:
        return []
    canaries = recursive_strings(gt.get("privacy_canaries") or {})
    if not canaries:
        return []
    haystack = json.dumps(document, ensure_ascii=False).lower()
    return sorted({
        c for c in canaries
        if c and c.lower() in haystack
    })


def parse_run_output(text: str) -> dict[str, Any]:
    pipeline_ms = None
    match = PIPELINE_MS_RE.search(text)
    if match:
        pipeline_ms = int(match.group(1))

    redactions = None
    match = REDACTIONS_RE.search(text)
    if match:
        redactions = int(match.group(1))

    revision = None
    match = REVISION_RE.search(text)
    if match:
        revision = match.group(1)

    return {
        "pipeline_ms": pipeline_ms,
        "redactions": redactions,
        "revision": revision,
    }


def parse_search_ranking(text: str) -> list[str]:
    rows = sorted(
        ((int(rank), case_id) for rank, case_id in SEARCH_ROW_RE.findall(text)),
        key=lambda item: item[0],
    )
    seen: set[str] = set()
    result: list[str] = []
    for _, case_id in rows:
        if case_id not in seen:
            result.append(case_id)
            seen.add(case_id)
    return result


def parse_protection(text: str) -> dict[str, Any]:
    def _one(regex: re.Pattern[str], conv):
        match = regex.search(text)
        return conv(match.group(1)) if match else None

    return {
        "top1_preserved": _one(TOP1_RE, lambda x: x == "True"),
        "topk_overlap_pct": _one(OVERLAP_RE, float),
        "protected_vector_bytes": _one(VECTOR_RE, int),
        "wire_envelope_bytes": _one(WIRE_RE, int),
        "clinical_text_cosine": _one(COSINE_RE, float),
    }


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                keys.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: (
                    json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                )
                for key, value in row.items()
            })


def summarize_cases(rows: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [r for r in rows if r["success"]]
    pipeline_ms = [float(r["pipeline_ms"]) for r in successes if r.get("pipeline_ms") is not None]
    wall_ms = [float(r["wall_ms"]) for r in successes if r.get("wall_ms") is not None]

    checks = []
    for row in successes:
        field_checks = row.get("field_checks") or {}
        checks.extend(v for v in field_checks.values() if isinstance(v, bool))

    raw_leak_cases = sum(bool(r.get("raw_privacy_leaks")) for r in successes)
    safe_leak_cases = sum(bool(r.get("safe_privacy_leaks")) for r in successes)
    fact_counts = [r["fact_count"] for r in successes if isinstance(r.get("fact_count"), int)]

    return {
        "cases_total": len(rows),
        "cases_successful": len(successes),
        "success_rate": (len(successes) / len(rows)) if rows else None,
        "pipeline_latency_ms": {
            "median": statistics.median(pipeline_ms) if pipeline_ms else None,
            "p95": percentile(pipeline_ms, 0.95),
            "min": min(pipeline_ms) if pipeline_ms else None,
            "max": max(pipeline_ms) if pipeline_ms else None,
        },
        "wall_latency_ms": {
            "median": statistics.median(wall_ms) if wall_ms else None,
            "p95": percentile(wall_ms, 0.95),
        },
        "known_field_accuracy": (
            sum(checks) / len(checks) if checks else None
        ),
        "known_field_checks": len(checks),
        "raw_privacy_leak_cases": raw_leak_cases,
        "safe_privacy_leak_cases": safe_leak_cases,
        "safe_privacy_case_rate": (
            1.0 - safe_leak_cases / len(successes) if successes else None
        ),
        "fact_count_median": statistics.median(fact_counts) if fact_counts else None,
    }


def summarize_search(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in rows if r.get("success")]
    if not ok:
        return {
            "queries": len(rows),
            "successful_queries": 0,
            "mean_recall_at_5": None,
            "mean_mrr": None,
            "top1_hit_rate": None,
        }
    return {
        "queries": len(rows),
        "successful_queries": len(ok),
        "mean_recall_at_5": statistics.mean(r["recall_at_5"] for r in ok),
        "mean_mrr": statistics.mean(r["mrr"] for r in ok),
        "top1_hit_rate": statistics.mean(1.0 if r["top1_hit"] else 0.0 for r in ok),
    }


def summarize_protection(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in rows if r.get("success")]
    if not ok:
        return {
            "queries": len(rows),
            "successful_queries": 0,
            "top1_preservation_rate": None,
            "mean_topk_overlap_pct": None,
            "mean_clinical_text_cosine": None,
        }

    preserved = [r["top1_preserved"] for r in ok if isinstance(r.get("top1_preserved"), bool)]
    overlaps = [r["topk_overlap_pct"] for r in ok if r.get("topk_overlap_pct") is not None]
    cosines = [r["clinical_text_cosine"] for r in ok if r.get("clinical_text_cosine") is not None]

    return {
        "queries": len(rows),
        "successful_queries": len(ok),
        "top1_preservation_rate": (
            statistics.mean(1.0 if x else 0.0 for x in preserved) if preserved else None
        ),
        "mean_topk_overlap_pct": statistics.mean(overlaps) if overlaps else None,
        "mean_clinical_text_cosine": statistics.mean(cosines) if cosines else None,
        "wire_envelope_bytes": next(
            (r.get("wire_envelope_bytes") for r in ok if r.get("wire_envelope_bytes") is not None),
            None,
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run the minimal Aethelgard 30-case research benchmark."
    )
    p.add_argument("--vault", type=Path, default=Path("."), help="Initialized vault root.")
    p.add_argument("--remote", required=True, help="Aethelgard HTTP worker URL.")
    p.add_argument(
        "--ground-truth",
        type=Path,
        default=None,
        help="Optional ground_truth.jsonl. Auto-discovered when omitted.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory. Default: <vault>/.research/latest",
    )
    p.add_argument(
        "--case-timeout",
        type=int,
        default=1800,
        help="Timeout per remote case request in seconds.",
    )
    p.add_argument(
        "--search-timeout",
        type=int,
        default=300,
        help="Timeout per local search/protection query in seconds.",
    )
    p.add_argument(
        "--skip-processing",
        action="store_true",
        help="Only collect/evaluate an already processed vault.",
    )
    p.add_argument(
        "--skip-search",
        action="store_true",
        help="Skip diagnosis retrieval and protection checks.",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    vault = args.vault.resolve()
    if not (vault / ".aethelgard").exists():
        raise SystemExit(f"Not an initialized vault: {vault}")

    cases = case_ids(vault)
    if not cases:
        raise SystemExit(f"No CASE-* directories found in {vault}")

    gt_path = args.ground_truth.resolve() if args.ground_truth else discover_ground_truth(vault)
    gt = load_ground_truth(gt_path)

    output = (args.output or (vault / ".research" / "latest")).resolve()
    output.mkdir(parents=True, exist_ok=True)

    run_meta = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "vault": str(vault),
        "remote": args.remote,
        "ground_truth": str(gt_path) if gt_path else None,
        "case_count": len(cases),
        "cases": cases,
        "python": sys.version,
    }

    print(f"[research] vault={vault}")
    print(f"[research] cases={len(cases)} output={output}")
    print(f"[research] ground_truth={gt_path or 'not found; GT metrics disabled'}")

    process_results: dict[str, CommandResult] = {}
    run_details: dict[str, dict[str, Any]] = {}

    if not args.skip_processing:
        for index, case_id in enumerate(cases, 1):
            print(f"[{index:02d}/{len(cases):02d}] process {case_id}", flush=True)
            result = run_command(
                ["aethelgard", "run", case_id, "--remote", args.remote],
                cwd=vault,
                timeout_seconds=args.case_timeout,
            )
            process_results[case_id] = result
            parsed = parse_run_output(result.stdout + "\n" + result.stderr)
            run_details[case_id] = parsed
            state = "OK" if result.returncode == 0 else "FAIL"
            latency = parsed.get("pipeline_ms") or result.wall_ms
            print(f"             {state} {latency} ms", flush=True)

    case_rows: list[dict[str, Any]] = []
    for case_id in cases:
        result = process_results.get(case_id)
        derived = latest_derived_dir(vault, case_id)

        raw = read_json(derived / "evidence.raw.json") if derived else None
        safe = read_json(derived / "evidence.json") if derived else None
        manifest = read_json(derived / "manifest.json") if derived else None
        privacy = read_json(derived / "privacy.json") if derived else None

        details = run_details.get(case_id, {})
        success = (
            (result.returncode == 0 if result else derived is not None)
            and safe is not None
        )
        flat = flatten_json(safe) if safe is not None else []
        ground = gt.get(case_id)

        row = {
            "case_id": case_id,
            "success": success,
            "returncode": result.returncode if result else None,
            "timed_out": result.timed_out if result else None,
            "wall_ms": result.wall_ms if result else None,
            "pipeline_ms": details.get("pipeline_ms"),
            "redactions": details.get("redactions"),
            "revision": details.get("revision"),
            "derived_dir": str(derived) if derived else None,
            "fact_count": len(flat) if safe is not None else None,
            "field_checks": evaluate_known_fields(safe, ground),
            "raw_privacy_leaks": privacy_leaks(raw, ground),
            "safe_privacy_leaks": privacy_leaks(safe, ground),
            "hidden_diagnosis_label": ground.get("hidden_diagnosis_label") if ground else None,
            "manifest_fingerprint": (
                manifest.get("semantic_fingerprint")
                if isinstance(manifest, dict)
                else None
            ),
            "privacy_report": privacy,
            "error": (
                ((result.stderr or result.stdout)[-4000:])
                if result and result.returncode != 0
                else None
            ),
        }
        case_rows.append(row)

    search_rows: list[dict[str, Any]] = []
    protection_rows: list[dict[str, Any]] = []

    if not args.skip_search and gt:
        diagnoses: dict[str, set[str]] = {}
        for case_id, ground in gt.items():
            if case_id not in cases:
                continue
            diagnosis = str(ground.get("hidden_diagnosis_label") or "").strip()
            if diagnosis:
                diagnoses.setdefault(diagnosis, set()).add(case_id)

        for diagnosis, relevant in sorted(diagnoses.items()):
            print(f"[search] {diagnosis}", flush=True)
            result = run_command(
                ["aethelgard", "search", diagnosis],
                cwd=vault,
                timeout_seconds=args.search_timeout,
            )
            ranking = parse_search_ranking(result.stdout + "\n" + result.stderr)
            top5 = ranking[:5]
            first_relevant_rank = next(
                (i for i, cid in enumerate(ranking, 1) if cid in relevant),
                None,
            )
            search_rows.append({
                "query": diagnosis,
                "relevant_cases": sorted(relevant),
                "ranking": ranking,
                "success": result.returncode == 0 and bool(ranking),
                "returncode": result.returncode,
                "wall_ms": result.wall_ms,
                "recall_at_5": (
                    len(set(top5) & relevant) / len(relevant)
                    if relevant else 0.0
                ),
                "mrr": (1.0 / first_relevant_rank) if first_relevant_rank else 0.0,
                "top1_hit": bool(ranking and ranking[0] in relevant),
                "error": (
                    ((result.stderr or result.stdout)[-2000:])
                    if result.returncode != 0
                    else None
                ),
            })

            print(f"[protect] {diagnosis}", flush=True)
            protected = run_command(
                [
                    "aethelgard", "search", diagnosis,
                    "--compare-protection", "--seed", "42",
                ],
                cwd=vault,
                timeout_seconds=args.search_timeout,
            )
            metrics = parse_protection(protected.stdout + "\n" + protected.stderr)
            protection_rows.append({
                "query": diagnosis,
                "success": protected.returncode == 0,
                "returncode": protected.returncode,
                "wall_ms": protected.wall_ms,
                **metrics,
                "error": (
                    ((protected.stderr or protected.stdout)[-2000:])
                    if protected.returncode != 0
                    else None
                ),
            })

    verify = run_command(
        ["aethelgard", "verify"],
        cwd=vault,
        timeout_seconds=300,
    )
    status = run_command(
        ["aethelgard", "status"],
        cwd=vault,
        timeout_seconds=60,
    )

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "processing": summarize_cases(case_rows),
        "retrieval": summarize_search(search_rows),
        "protection": summarize_protection(protection_rows),
        "vault_verify_ok": verify.returncode == 0,
        "ground_truth_available": bool(gt),
    }

    run_meta["finished_at"] = datetime.now(timezone.utc).isoformat()
    run_meta["verify_returncode"] = verify.returncode

    (output / "run.json").write_text(
        json.dumps(run_meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output / "status.txt").write_text(
        status.stdout + ("\n" + status.stderr if status.stderr else ""),
        encoding="utf-8",
    )
    (output / "verify.txt").write_text(
        verify.stdout + ("\n" + verify.stderr if verify.stderr else ""),
        encoding="utf-8",
    )

    write_jsonl(output / "cases.jsonl", case_rows)
    write_jsonl(output / "search.jsonl", search_rows)
    write_jsonl(output / "protection.jsonl", protection_rows)
    write_csv(output / "cases.csv", case_rows)
    write_csv(output / "search.csv", search_rows)
    write_csv(output / "protection.csv", protection_rows)

    print("\n=== Aethelgard minimal research summary ===")
    p = summary["processing"]
    print(f"cases:                 {p['cases_successful']}/{p['cases_total']}")
    if p["success_rate"] is not None:
        print(f"processing success:    {p['success_rate'] * 100:.1f}%")
    if p["pipeline_latency_ms"]["median"] is not None:
        print(f"median pipeline:       {p['pipeline_latency_ms']['median'] / 1000:.1f}s")
    if p["pipeline_latency_ms"]["p95"] is not None:
        print(f"p95 pipeline:          {p['pipeline_latency_ms']['p95'] / 1000:.1f}s")
    if p["known_field_accuracy"] is not None:
        print(f"known-field accuracy:  {p['known_field_accuracy'] * 100:.1f}%")
    if p["safe_privacy_case_rate"] is not None:
        print(f"safe cases no canary:  {p['safe_privacy_case_rate'] * 100:.1f}%")

    r = summary["retrieval"]
    if r["successful_queries"]:
        print(f"mean Recall@5:         {r['mean_recall_at_5'] * 100:.1f}%")
        print(f"mean MRR:              {r['mean_mrr']:.3f}")

    pr = summary["protection"]
    if pr["successful_queries"]:
        if pr["top1_preservation_rate"] is not None:
            print(f"protected top-1 keep:  {pr['top1_preservation_rate'] * 100:.1f}%")
        if pr["mean_topk_overlap_pct"] is not None:
            print(f"protected top-k ovlp:  {pr['mean_topk_overlap_pct']:.1f}%")

    print(f"vault verify:          {'OK' if summary['vault_verify_ok'] else 'FAIL'}")
    print(f"\nresults: {output}")
    return 0 if p["cases_successful"] == p["cases_total"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
