from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class QueryVectors:
    profile: str
    components: Mapping[str, Any]
    weights: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    case_id: str
    revision_id: str
    score: float
    component_scores: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class SearchHit:
    case_id: str
    revision_id: str
    score: float
    component_scores: Mapping[str, float]
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProtectionReport:
    algorithm: str
    parameters: Mapping[str, float]
    component_cosine: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class SearchComparison:
    clean: tuple[SearchHit, ...]
    protected: tuple[SearchHit, ...]
    protection: ProtectionReport
    protected_vector_bytes: int
    protected_wire_bytes: int
    top1_preserved: bool
    top_k_overlap: float
