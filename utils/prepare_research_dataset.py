from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import statistics
from io import StringIO
from pathlib import Path
from typing import Iterable

FORMATS = ('admission_txt', 'legacy_txt', 'hl7')
GROUND_TRUTH_KEYS = ('radiographic_labels', 'hidden_diagnosis_label')


def _records(path: Path) -> Iterable[tuple[dict, Path]]:
    files = [path] if path.is_file() else sorted(path.rglob('*.json'))
    for file in files:
        payload = json.loads(file.read_text(encoding='utf-8'))
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f'{file}: expected JSON object records')
            yield item, file


def _case_id(record: dict, index: int) -> str:
    patient_id = str(record.get('patient_id') or f'patient{index:05d}')
    match = re.search(r'(\d+)$', patient_id)
    return f'CASE-{int(match.group(1)):05d}' if match else f'CASE-{index:05d}'


def _canaries(patient_id: str) -> dict[str, str]:
    token = hashlib.sha256(patient_id.encode()).hexdigest()[:8].upper()
    return {
        'patient_id': patient_id,
        'mrn': f'SYN-{token}',
        'email': f'patient.{token.lower()}@example.test',
    }


def _resolve_image(record: dict, json_file: Path, images_root: Path | None) -> Path:
    ref = str(record.get('image_reference') or '')
    if not ref:
        raise ValueError(f'{json_file}: image_reference is missing')
    direct = json_file.parent / ref
    if direct.exists():
        return direct
    if images_root:
        candidate = images_root / ref
        if candidate.exists():
            return candidate
        matches = list(images_root.rglob(Path(ref).name))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f'ambiguous image {ref!r}: {len(matches)} matches under {images_root}')
    raise FileNotFoundError(f'cannot resolve image {ref!r} for {json_file}')


def _safe_source(record: dict, canaries: dict[str, str]) -> dict:
    """Source-side structure only. Never copy hidden/radiographic ground truth keys."""
    return {
        'patient': canaries,
        'demographics': record.get('demographics') or {},
        'clinical_history': record.get('clinical_history') or '',
        'vitals': record.get('vitals') or {},
        'admission_note': record.get('admission_note') or '',
    }


def _render_admission_txt(record: dict, canaries: dict[str, str]) -> str:
    header = (
        f"PATIENT ID: {canaries['patient_id']}\n"
        f"MRN: {canaries['mrn']}\n"
        f"CONTACT: {canaries['email']}\n\n"
    )
    return header + str(record.get('admission_note') or record.get('clinical_history') or '') + '\n'


def _render_legacy_txt(record: dict, canaries: dict[str, str]) -> str:
    demo = record.get('demographics') or {}
    vitals = record.get('vitals') or {}
    lines = [
        'LEGACY EHR TEXT EXPORT',
        f"PATIENT_ID={canaries['patient_id']}",
        f"MRN={canaries['mrn']}",
        f"EMAIL={canaries['email']}",
        f"AGE={demo.get('age', '')}",
        f"SEX={demo.get('sex', '')}",
    ]
    lines.extend(f'{key}={value}' for key, value in vitals.items())
    lines.extend(['', 'CLINICAL HISTORY', str(record.get('clinical_history') or ''), '', 'ADMISSION NOTE', str(record.get('admission_note') or '')])
    return '\n'.join(lines).rstrip() + '\n'


def _render_json(record: dict, canaries: dict[str, str]) -> str:
    return json.dumps(_safe_source(record, canaries), indent=2, ensure_ascii=False, sort_keys=True) + '\n'


def _render_csv(record: dict, canaries: dict[str, str]) -> str:
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(['section', 'field', 'value'])
    for key, value in canaries.items():
        writer.writerow(['patient', key, value])
    for section in ('demographics', 'vitals'):
        for key, value in (record.get(section) or {}).items():
            writer.writerow([section, key, value])
    writer.writerow(['clinical', 'clinical_history', record.get('clinical_history') or ''])
    writer.writerow(['clinical', 'admission_note', record.get('admission_note') or ''])
    return out.getvalue()


def _hl7_escape(value: object) -> str:
    return str(value).replace('\\', '\\E\\').replace('|', '\\F\\').replace('^', '\\S\\').replace('~', '\\R\\').replace('&', '\\T\\').replace('\r', ' ').replace('\n', '\\X0A\\')


def _render_hl7(record: dict, canaries: dict[str, str]) -> str:
    demo = record.get('demographics') or {}
    vitals = record.get('vitals') or {}
    sex = str(demo.get('sex') or '')[:1].upper()
    lines = [
        'MSH|^~\\&|AETHELGARD_SYNTH|DEMO_HOSPITAL|VAULT|LOCAL|202601010000||ORU^R01|SYNTHETIC|P|2.5',
        f"PID|||{_hl7_escape(canaries['mrn'])}||SYNTHETIC^PATIENT||19800101|{_hl7_escape(sex)}|||^^|||||{_hl7_escape(canaries['email'])}",
        f"OBX|1|NM|AGE^Age||{_hl7_escape(demo.get('age', ''))}|years",
    ]
    seq = 2
    for key, value in vitals.items():
        lines.append(f'OBX|{seq}|ST|{_hl7_escape(key)}^{_hl7_escape(key)}||{_hl7_escape(value)}')
        seq += 1
    lines.append(f'NTE|1||{_hl7_escape(record.get("clinical_history") or "")}')
    lines.append(f'NTE|2||{_hl7_escape(record.get("admission_note") or "")}')
    return '\r'.join(lines) + '\r'


RENDERERS = {
    'admission_txt': ('note.txt', _render_admission_txt),
    'legacy_txt': ('note.txt', _render_legacy_txt),
    'json': ('record.json', _render_json),
    'csv': ('record.csv', _render_csv),
    'hl7': ('record.hl7', _render_hl7),
}


def prepare_dataset(input_path: Path, output: Path, *, images_root: Path | None = None, formats: tuple[str, ...] = FORMATS, force: bool = False) -> dict:
    output = output.resolve()
    if output.exists():
        if not force:
            raise FileExistsError(f'{output} already exists; pass force=True / --force to replace it')
        shutil.rmtree(output)
    (output / 'vaults' / 'mixed').mkdir(parents=True)
    (output / 'research' / 'ground_truth').mkdir(parents=True)
    for fmt in formats:
        if fmt not in RENDERERS:
            raise ValueError(f'unknown format: {fmt}')
        (output / 'vaults' / 'by-format' / fmt).mkdir(parents=True)

    manifest: dict[str, object] = {
        'format': 'aethelgard-research-dataset/1',
        'input': str(input_path.resolve()),
        'formats': list(formats),
        'cases': [],
    }
    ground_truth_lines: list[str] = []
    seen: set[str] = set()
    ages: list[int] = []
    diagnosis_counts: dict[str, int] = {}
    sex_counts: dict[str, int] = {}
    mixed_format_counts: dict[str, int] = {fmt: 0 for fmt in formats}
    radiographic_label_counts: dict[str, dict[str, int]] = {}

    for index, (record, json_file) in enumerate(_records(input_path), start=1):
        for key in ('patient_id', 'image_reference', 'radiographic_labels', 'hidden_diagnosis_label'):
            if key not in record:
                raise ValueError(f'{json_file}: missing required field {key!r}')
        case_id = _case_id(record, index)
        if case_id in seen:
            raise ValueError(f'duplicate case id {case_id}')
        seen.add(case_id)

        patient_id = str(record['patient_id'])
        canaries = _canaries(patient_id)
        image = _resolve_image(record, json_file, images_root)
        image_name = 'chest' + image.suffix.lower()
        source_sha = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

        age = (record.get('demographics') or {}).get('age')
        if isinstance(age, int):
            ages.append(age)
        diagnosis = str(record['hidden_diagnosis_label'])
        diagnosis_counts[diagnosis] = diagnosis_counts.get(diagnosis, 0) + 1
        sex = str((record.get('demographics') or {}).get('sex') or 'Unknown')
        sex_counts[sex] = sex_counts.get(sex, 0) + 1
        for group, labels in (record.get('radiographic_labels') or {}).items():
            counts = radiographic_label_counts.setdefault(str(group), {})
            if isinstance(labels, list):
                for label in labels:
                    label = str(label)
                    counts[label] = counts.get(label, 0) + 1

        ground_truth = {
            'case_id': case_id,
            'patient_id': patient_id,
            'demographics': record.get('demographics') or {},
            'vitals': record.get('vitals') or {},
            'radiographic_labels': record['radiographic_labels'],
            'hidden_diagnosis_label': record['hidden_diagnosis_label'],
            'privacy_canaries': canaries,
            'image_reference': record['image_reference'],
            'source_record_sha256': source_sha,
        }
        (output / 'research' / 'ground_truth' / f'{case_id}.json').write_text(
            json.dumps({'ground_truth': ground_truth, 'original_record': record}, indent=2, ensure_ascii=False, sort_keys=True),
            encoding='utf-8',
        )
        ground_truth_lines.append(json.dumps(ground_truth, ensure_ascii=False, sort_keys=True))

        mixed_format = formats[(index - 1) % len(formats)]
        mixed_format_counts[mixed_format] += 1
        case_entry = {
            'case_id': case_id,
            'patient_id': patient_id,
            'mixed_format': mixed_format,
            'image': image_name,
            'ground_truth': f'research/ground_truth/{case_id}.json',
        }
        manifest['cases'].append(case_entry)

        for fmt in formats:
            filename, renderer = RENDERERS[fmt]
            case_dir = output / 'vaults' / 'by-format' / fmt / case_id
            case_dir.mkdir(parents=True)
            (case_dir / filename).write_text(renderer(record, canaries), encoding='utf-8', newline='')
            shutil.copy2(image, case_dir / image_name)

            if fmt == mixed_format:
                mixed_dir = output / 'vaults' / 'mixed' / case_id
                mixed_dir.mkdir(parents=True)
                shutil.copy2(case_dir / filename, mixed_dir / filename)
                shutil.copy2(image, mixed_dir / image_name)

    stats = {
        'cases': len(seen),
        'diagnosis_counts': dict(sorted(diagnosis_counts.items())),
        'sex_counts': dict(sorted(sex_counts.items())),
        'age': {
            'min': min(ages) if ages else None,
            'median': statistics.median(ages) if ages else None,
            'max': max(ages) if ages else None,
        },
        'radiographic_label_counts': {group: dict(sorted(counts.items())) for group, counts in sorted(radiographic_label_counts.items())},
        'mixed_format_counts': mixed_format_counts,
    }
    manifest['stats'] = stats
    (output / 'research' / 'stats.json').write_text(json.dumps(stats, indent=2, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
    (output / 'research' / 'ground_truth.jsonl').write_text('\n'.join(ground_truth_lines) + ('\n' if ground_truth_lines else ''), encoding='utf-8')
    (output / 'research' / 'dataset_manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
    (output / 'README.md').write_text(
        '# Generated Aethelgard research dataset\n\n'
        'Vault-ready inputs live under `vaults/`; ground truth lives under `research/` and must not be used as a vault source.\n\n'
        'Use the heterogeneous demo corpus with:\n\n'
        '```bash\ncd vaults/mixed\naethelgard init\naethelgard run\n```\n\n'
        'For controlled format experiments, use one directory under `vaults/by-format/`.\n',
        encoding='utf-8',
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description='Convert fixed-schema synthetic multimodal JSON into Aethelgard demo/research corpora.')
    parser.add_argument('input', type=Path, help='JSON file or directory containing generated JSON records')
    parser.add_argument('-o', '--output', type=Path, default=Path('research-dataset'))
    parser.add_argument('--images-root', type=Path, help='Optional root used to resolve image_reference values')
    parser.add_argument('--formats', nargs='+', choices=FORMATS, default=list(FORMATS))
    parser.add_argument('--force', action='store_true', help='Replace the output directory if it already exists')
    args = parser.parse_args()
    manifest = prepare_dataset(args.input, args.output, images_root=args.images_root, formats=tuple(args.formats), force=args.force)
    print(f"Wrote {len(manifest['cases'])} cases to {args.output}")
    print(f"Mixed vault: {args.output / 'vaults' / 'mixed'}")
    print(f"Ground truth: {args.output / 'research' / 'ground_truth.jsonl'}")


if __name__ == '__main__':
    main()
