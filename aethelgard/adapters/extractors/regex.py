from __future__ import annotations

import re
from dataclasses import dataclass

from ...domain import CaseBundle, Extraction, ExtractionContext


@dataclass(frozen=True, slots=True)
class RegexEvidenceExtractor:
    """Tiny deterministic extension used for smoke tests and as a plugin example."""

    @property
    def fingerprint(self) -> str:
        return 'extractor:regex-demo:v1'

    def extract(self, bundle: CaseBundle, context: ExtractionContext) -> Extraction:
        text = '\n'.join(part.text or '' for part in bundle.text_parts)
        evidence: dict = {}
        for label, pattern in {
            'diagnosis': r'(?im)^\s*(?:diagnosis|assessment)\s*:\s*(.+)$',
            'treatment': r'(?im)^\s*(?:treatment|procedure|plan)\s*:\s*(.+)$',
            'outcome': r'(?im)^\s*outcome\s*:\s*(.+)$',
        }.items():
            match = re.search(pattern, text)
            if match:
                evidence[label] = match.group(1).strip()
        if not evidence:
            evidence['document_excerpt'] = text[:1200].strip()
        return Extraction(
            evidence=evidence,
            provenance={'artifacts': [a.uri for a in bundle.artifacts], 'case_id': bundle.case_id},
            model=self.fingerprint,
        )
