from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Sequence

from .domain import CaseBundle, CaseStatus, ExtractionContext, ProcessedCase
from .ports import ArtifactSource, CaseResolver, EvidenceExtractor, EvidencePolicy, Materializer
from .readers import ReaderRegistry


def _digest(payload) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


@dataclass(slots=True)
class Pipeline:
    source: ArtifactSource
    readers: ReaderRegistry
    resolver: CaseResolver
    extractor: EvidenceExtractor
    policy: EvidencePolicy
    materializers: Sequence[Materializer]

    @property
    def fingerprint(self) -> str:
        return _digest({
            'readers': self.readers.fingerprint,
            'resolver': self.resolver.fingerprint,
            'extractor': self.extractor.fingerprint,
            'policy': self.policy.fingerprint,
            'materializers': [m.fingerprint for m in self.materializers],
        })

    def cases(self) -> dict[str, tuple]:
        return {k: tuple(v) for k, v in self.resolver.resolve(self.source.scan()).items()}

    def source_fingerprint(self, artifacts) -> str:
        return _digest([(a.relpath.as_posix(), a.sha256, a.size) for a in artifacts])

    def semantic_fingerprint(self, artifacts) -> str:
        return _digest({'source': self.source_fingerprint(artifacts), 'pipeline': self.fingerprint})

    def build_bundle(self, case_id: str, artifacts) -> CaseBundle:
        parsed = []
        for artifact in artifacts:
            with self.source.open(artifact) as stream:
                parsed.append(self.readers.read(artifact, stream))
        return CaseBundle(case_id=case_id, artifacts=tuple(artifacts), parsed=tuple(parsed))

    def process_case(self, case_id: str, artifacts) -> ProcessedCase:
        started = time.perf_counter()
        bundle = self.build_bundle(case_id, artifacts)
        extraction = self.extractor.extract(bundle, ExtractionContext())
        policy = self.policy.evaluate(extraction)
        derived = []
        for materializer in self.materializers:
            derived.extend(materializer.build(bundle, extraction, policy))
        return ProcessedCase(
            case_id=case_id,
            semantic_fingerprint=self.semantic_fingerprint(artifacts),
            raw_extraction=extraction,
            policy=policy,
            derived=tuple(derived),
            source_artifacts=tuple(artifacts),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
