from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ...domain import ProcessedCase
from ...pipeline import Pipeline
from ...vault import Vault


@dataclass(slots=True)
class LocalExecutor:
    vault: Vault
    pipeline: Pipeline

    @property
    def fingerprint(self) -> str:
        return 'executor:local:v1'

    def process(self, case_ids: Sequence[str] | None = None) -> Sequence[ProcessedCase]:
        cases = self.pipeline.cases()
        wanted = set(case_ids or cases.keys())
        return tuple(
            self.pipeline.process_case(case_id, artifacts)
            for case_id, artifacts in cases.items()
            if case_id in wanted
        )
