from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .domain import ArtifactRef


@dataclass(frozen=True, slots=True)
class ParentDirectoryCaseResolver:
    @property
    def fingerprint(self) -> str:
        return 'case-resolver:parent-directory:v1'

    def resolve(self, artifacts: Sequence[ArtifactRef]) -> Mapping[str, Sequence[ArtifactRef]]:
        grouped: dict[str, list[ArtifactRef]] = {}
        for artifact in artifacts:
            parts = artifact.relpath.parts
            case_id = parts[0] if len(parts) > 1 else artifact.relpath.stem
            grouped.setdefault(case_id, []).append(artifact)
        return {k: tuple(sorted(v, key=lambda a: str(a.relpath))) for k, v in sorted(grouped.items())}
