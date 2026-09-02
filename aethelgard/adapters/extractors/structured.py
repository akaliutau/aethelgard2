from __future__ import annotations

import json
from dataclasses import dataclass

from ...domain import CaseBundle, Extraction, ExtractionContext
from ...ports import StructuredToolModel


@dataclass(frozen=True, slots=True)
class StructuredEvidenceExtractor:
    """Model-agnostic clinical evidence extractor over a structured model port."""

    model: StructuredToolModel
    max_chars: int = 48_000

    @property
    def fingerprint(self) -> str:
        return f'extractor:structured-evidence:v1:{self.model.fingerprint}'

    def extract(self, bundle: CaseBundle, context: ExtractionContext) -> Extraction:
        text = '\n\n'.join(
            f'--- SOURCE {part.source.name} ---\n{part.text}'
            for part in bundle.text_parts
            if part.text
        )[: self.max_chars]
        prompt = (
            'Build a faithful, clinically useful structured representation of this heterogeneous EHR text. '
            'The record may be old, abbreviated, inconsistent, or locally formatted. '
            'Preserve documented measurements, findings, interventions, outcomes, temporal relationships, '
            'negation and uncertainty. Do not invent or infer undocumented facts. '
            'Do not include patient names, MRNs, addresses, emails, phone numbers, or exact dates.\n\n'
            f'OBJECTIVE: {context.objective}\n'
            f'HINTS: {json.dumps(dict(context.hints), ensure_ascii=False)}\n\n'
            f'SOURCE MATERIAL:\n{text}'
        )
        response = self.model.call(
            prompt=prompt,
            function_name='emit_clinical_evidence',
            description='Extract faithful structured clinical evidence from heterogeneous medical documents.',
        )
        evidence = response.get('evidence')
        if not isinstance(evidence, dict):
            raise ValueError('Evidence extractor output must be a JSON object')
        return Extraction(
            evidence=evidence,
            provenance={
                'artifacts': [a.uri for a in bundle.artifacts],
                'case_id': bundle.case_id,
            },
            model=self.model.fingerprint,
        )
