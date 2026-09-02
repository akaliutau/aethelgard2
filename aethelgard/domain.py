from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Mapping, TypeAlias

JSONScalar: TypeAlias = None | bool | int | float | str
JSONValue: TypeAlias = JSONScalar | list['JSONValue'] | dict[str, 'JSONValue']
Evidence: TypeAlias = dict[str, JSONValue]


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    uri: str
    relpath: PurePosixPath
    media_type: str
    size: int
    sha256: str

    @property
    def name(self) -> str:
        return self.relpath.name


@dataclass(frozen=True, slots=True)
class ParsedArtifact:
    source: ArtifactRef
    text: str | None = None
    binary: bytes | None = None


@dataclass(frozen=True, slots=True)
class CaseBundle:
    case_id: str
    artifacts: tuple[ArtifactRef, ...]
    parsed: tuple[ParsedArtifact, ...]

    @property
    def text_parts(self) -> tuple[ParsedArtifact, ...]:
        return tuple(p for p in self.parsed if p.text is not None)

    @property
    def image_parts(self) -> tuple[ParsedArtifact, ...]:
        return tuple(p for p in self.parsed if p.binary is not None and p.source.media_type.startswith('image/'))


@dataclass(frozen=True, slots=True)
class ExtractionContext:
    objective: str = 'Build a faithful, clinically useful structured evidence representation.'
    hints: Mapping[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Extraction:
    evidence: Evidence
    provenance: dict[str, JSONValue]
    model: str
    metrics: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PolicyResult:
    evidence: Evidence
    report: dict[str, JSONValue]


@dataclass(frozen=True, slots=True)
class DerivedBlob:
    kind: str
    filename: str
    media_type: str
    data: bytes
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CaseStatus:
    case_id: str
    dirty: bool
    reasons: tuple[str, ...]
    source_fingerprint: str
    semantic_fingerprint: str
    head_semantic_fingerprint: str | None


@dataclass(frozen=True, slots=True)
class ProcessedCase:
    case_id: str
    semantic_fingerprint: str
    raw_extraction: Extraction
    policy: PolicyResult
    derived: tuple[DerivedBlob, ...]
    source_artifacts: tuple[ArtifactRef, ...]
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    revision_id: str
    created_at: str
    message: str
    cases: tuple[str, ...]
