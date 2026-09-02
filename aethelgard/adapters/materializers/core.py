from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence

from ...domain import CaseBundle, DerivedBlob, Extraction, PolicyResult


@dataclass(frozen=True, slots=True)
class EvidenceFilesMaterializer:
    @property
    def fingerprint(self) -> str:
        return 'materializer:evidence-files:v1'

    def build(self, bundle: CaseBundle, extraction: Extraction, policy: PolicyResult) -> Sequence[DerivedBlob]:
        return (
            DerivedBlob(
                kind='raw_extraction', filename='evidence.raw.json', media_type='application/json',
                data=json.dumps(extraction.evidence, indent=2, ensure_ascii=False, sort_keys=True).encode(),
            ),
            DerivedBlob(
                kind='evidence', filename='evidence.json', media_type='application/json',
                data=json.dumps(policy.evidence, indent=2, ensure_ascii=False, sort_keys=True).encode(),
            ),
            DerivedBlob(
                kind='provenance', filename='provenance.json', media_type='application/json',
                data=json.dumps(extraction.provenance, indent=2, ensure_ascii=False, sort_keys=True).encode(),
            ),
            DerivedBlob(
                kind='privacy', filename='privacy.json', media_type='application/json',
                data=json.dumps(policy.report, indent=2, ensure_ascii=False, sort_keys=True).encode(),
            ),
        )
