from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from .domain import QueryVectors, SearchCandidate


def _normalize(vector):
    import numpy as np
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else vector


@dataclass(slots=True)
class _Record:
    case_id: str
    revision_id: str
    vectors: dict[str, Any]
    facts: tuple[str, ...]
    fact_vectors: Any


@dataclass(slots=True)
class NumpyVaultSearchIndex:
    """Exact cosine search over vectors already committed to the vault."""

    vault: object
    _records: tuple[_Record, ...] | None = field(default=None, init=False, repr=False)

    @property
    def fingerprint(self) -> str:
        return 'search-index:numpy-exact:v1'

    def _load(self) -> tuple[_Record, ...]:
        if self._records is not None:
            return self._records

        import numpy as np

        records: list[_Record] = []
        for case_id in self.vault.case_ids():
            output = self.vault.current_output(case_id)
            embeddings_path = output / 'embeddings.npz'
            facts_path = output / 'evidence_facts.json'
            fact_vectors_path = output / 'evidence_facts.npz'
            if not embeddings_path.exists() or not facts_path.exists() or not fact_vectors_path.exists():
                raise RuntimeError(
                    f'{case_id}: search artifacts are missing. '
                    'Run `aethelgard run` once after upgrading to rebuild the case.'
                )

            with np.load(embeddings_path) as data:
                vectors = {
                    name: _normalize(data[name])
                    for name in ('clinical_text', 'medical_image')
                    if name in data.files
                }

            facts_doc = json.loads(facts_path.read_text())
            facts = tuple(item['text'] for item in facts_doc.get('facts', []))
            with np.load(fact_vectors_path) as data:
                fact_vectors = np.asarray(data['vectors'], dtype=np.float32)

            manifest = json.loads((output / 'manifest.json').read_text())
            records.append(_Record(
                case_id=case_id,
                revision_id=str(manifest['revision_id']),
                vectors=vectors,
                facts=facts,
                fact_vectors=fact_vectors,
            ))

        self._records = tuple(records)
        return self._records

    def search(self, vectors: QueryVectors, *, top_k: int) -> Sequence[SearchCandidate]:
        import numpy as np

        candidates: list[SearchCandidate] = []
        for record in self._load():
            component_scores: dict[str, float] = {}
            weighted = 0.0
            total_weight = 0.0

            for name, query_vector in vectors.components.items():
                case_vector = record.vectors.get(name)
                if case_vector is None:
                    continue
                score = float(np.dot(_normalize(query_vector), case_vector))
                component_scores[name] = score
                weight = float(vectors.weights.get(name, 1.0))
                weighted += weight * score
                total_weight += weight

            if component_scores:
                candidates.append(SearchCandidate(
                    case_id=record.case_id,
                    revision_id=record.revision_id,
                    score=weighted / (total_weight or 1.0),
                    component_scores=component_scores,
                ))

        return tuple(
            sorted(candidates, key=lambda item: item.score, reverse=True)[:max(1, top_k)]
        )

    def evidence_vectors(self, case_id: str) -> tuple[tuple[str, ...], Any]:
        for record in self._load():
            if record.case_id == case_id:
                return record.facts, record.fact_vectors
        raise KeyError(case_id)


@dataclass(frozen=True, slots=True)
class RankedEvidenceSelector:
    index: NumpyVaultSearchIndex

    @property
    def fingerprint(self) -> str:
        return 'evidence-selector:embedding-rank:v1'

    def select(
        self,
        case_id: str,
        vectors: QueryVectors,
        *,
        limit: int,
    ) -> Sequence[str]:
        import numpy as np

        query = vectors.components.get('clinical_text')
        if query is None:
            return ()

        facts, matrix = self.index.evidence_vectors(case_id)
        matrix = np.asarray(matrix, dtype=np.float32)
        if not facts or matrix.size == 0:
            return ()

        scores = matrix @ _normalize(query)
        order = np.argsort(scores)[::-1][:max(1, limit)]
        return tuple(facts[int(i)] for i in order)
