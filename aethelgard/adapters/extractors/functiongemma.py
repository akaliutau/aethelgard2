from __future__ import annotations

import json
from dataclasses import dataclass

from ...domain import CaseBundle, Extraction, ExtractionContext
from ...ports import StructuredToolModel


@dataclass(frozen=True, slots=True)
class FunctionGemmaEvidenceExtractor:
    model: StructuredToolModel
    max_chars: int = 48_000

    @property
    def fingerprint(self) -> str:
        return f'extractor:functiongemma-evidence:v2:{self.model.fingerprint}'

    def extract(self, bundle: CaseBundle, context: ExtractionContext) -> Extraction:
        text = '\n\n'.join(
            f'--- SOURCE {part.source.name} ---\n{part.text}'
            for part in bundle.text_parts
            if part.text
        )[: self.max_chars]
        prompt = (
            'You are the semantic ingestion engine of a protected clinical document vault. '
            'Read heterogeneous EHR text faithfully and emit clinically useful structured evidence. '
            'The source can be old, abbreviated, inconsistent or locally formatted. '
            'Call emit_clinical_evidence exactly once with the extracted facts in its evidence object. '
            'Use whatever nested keys best preserve the clinical facts. '
            'Do not invent or infer undocumented facts. Do not include direct identifiers such as patient names, '
            'MRNs, addresses, emails, phone numbers or exact dates. Preserve clinically meaningful measurements, '
            'findings, interventions, outcomes, temporal relationships and uncertainty when present.\n\n'
            f'OBJECTIVE: {context.objective}\n'
            f'HINTS: {json.dumps(dict(context.hints), ensure_ascii=False)}\n\n'
            f'SOURCE MATERIAL:\n{text}'
        )
        response = self.model.call(
            prompt=prompt,
            function_name='emit_clinical_evidence',
            description='Emit a flexible JSON dictionary containing only faithful clinical evidence from the provided record.',
        )
        evidence = response['evidence']
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
