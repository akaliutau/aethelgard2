from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .domain import ArtifactRef


@dataclass(frozen=True, slots=True)
class ParentDirectoryCaseResolver:
    """Resolve each artifact to its immediate parent directory.

    This keeps CASE-001 and CASE-002 distinct even when the configured source
    points at a wrapper directory such as ``demo/``.
    """

    @property
    def fingerprint(self) -> str:
        return 'case-resolver:parent-directory:v2'

    def resolve(self, artifacts: Sequence[ArtifactRef]) -> Mapping[str, Sequence[ArtifactRef]]:
        grouped: dict[str, list[ArtifactRef]] = {}
        for artifact in artifacts:
            parent = artifact.relpath.parent
            case_id = parent.name if parent.name else artifact.relpath.stem
            grouped.setdefault(case_id, []).append(artifact)
        return {
            key: tuple(sorted(value, key=lambda a: str(a.relpath)))
            for key, value in sorted(grouped.items())
        }
