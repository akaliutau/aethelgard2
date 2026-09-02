from __future__ import annotations

import re
from dataclasses import dataclass

from .domain import Extraction, JSONValue, PolicyResult

_FORBIDDEN_KEYS = {
    'name', 'patient_name', 'first_name', 'last_name', 'mrn', 'medical_record_number',
    'dob', 'date_of_birth', 'address', 'email', 'phone', 'telephone', 'ssn', 'postcode',
    'zip_code', 'exact_date', 'admission_date', 'discharge_date',
}
_PATTERNS = {
    'email': re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I),
    'phone': re.compile(r'(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)'),
    'iso_date': re.compile(r'\b\d{4}-\d{2}-\d{2}\b'),
    'mrn': re.compile(r'\b(?:MRN|Medical Record(?: Number)?)\s*[:#-]?\s*[A-Z0-9-]{4,}\b', re.I),
}


def _sanitize(value: JSONValue, path: str, hits: list[dict]) -> JSONValue:
    if isinstance(value, dict):
        out: dict[str, JSONValue] = {}
        for key, child in value.items():
            child_path = f'{path}.{key}' if path else key
            if key.casefold() in _FORBIDDEN_KEYS:
                hits.append({'type': 'forbidden_key', 'path': child_path})
                continue
            out[key] = _sanitize(child, child_path, hits)
        return out
    if isinstance(value, list):
        return [_sanitize(item, f'{path}[{i}]', hits) for i, item in enumerate(value)]
    if isinstance(value, str):
        text = value
        for name, pattern in _PATTERNS.items():
            if pattern.search(text):
                hits.append({'type': name, 'path': path})
                text = pattern.sub('[REDACTED]', text)
        return text
    return value


@dataclass(frozen=True, slots=True)
class DefaultEvidencePolicy:
    @property
    def fingerprint(self) -> str:
        return 'policy:privacy-default:v2'

    def evaluate(self, extraction: Extraction) -> PolicyResult:
        hits: list[dict] = []
        safe = _sanitize(extraction.evidence, '', hits)
        assert isinstance(safe, dict)
        return PolicyResult(
            evidence=safe,
            report={
                'policy': self.fingerprint,
                'redactions': hits,
                'redaction_count': len(hits),
                'passed': True,
            },
        )
