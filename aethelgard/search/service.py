from __future__ import annotations

from dataclasses import dataclass

from .domain import QueryVectors, SearchComparison, SearchHit
from .protection import encode_protected_query


@dataclass(slots=True)
class VaultSearch:
    encoder: object
    index: object
    selector: object
    protector: object
    default_top_k: int = 5
    default_summary_facts: int = 4

    def encode(self, text: str, image: bytes | None = None) -> QueryVectors:
        return self.encoder.encode(text, image)

    def search_vectors(
        self,
        vectors: QueryVectors,
        *,
        top_k: int | None = None,
        summary_facts: int | None = None,
    ) -> tuple[SearchHit, ...]:
        top_k = top_k or self.default_top_k
        summary_facts = summary_facts or self.default_summary_facts
        candidates = self.index.search(vectors, top_k=top_k)
        return tuple(
            SearchHit(
                case_id=item.case_id,
                revision_id=item.revision_id,
                score=item.score,
                component_scores=dict(item.component_scores),
                evidence=tuple(self.selector.select(
                    item.case_id,
                    vectors,
                    limit=summary_facts,
                )),
            )
            for item in candidates
        )

    def search(
        self,
        text: str,
        image: bytes | None = None,
        *,
        top_k: int | None = None,
        summary_facts: int | None = None,
    ) -> tuple[SearchHit, ...]:
        return self.search_vectors(
            self.encode(text, image),
            top_k=top_k,
            summary_facts=summary_facts,
        )

    def compare_protection(
        self,
        text: str,
        image: bytes | None = None,
        *,
        top_k: int | None = None,
        summary_facts: int | None = None,
        seed: int | None = None,
    ) -> SearchComparison:
        vectors = self.encode(text, image)
        clean = self.search_vectors(vectors, top_k=top_k, summary_facts=summary_facts)
        protected_vectors, report = self.protector.protect(vectors, seed=seed)
        protected = self.search_vectors(
            protected_vectors,
            top_k=top_k,
            summary_facts=summary_facts,
        )
        envelope, wire = encode_protected_query(protected_vectors, report)
        vector_bytes = sum(
            int(component['dimensions']) * 2
            for component in envelope['components'].values()
        )

        clean_ids = [hit.case_id for hit in clean]
        protected_ids = [hit.case_id for hit in protected]
        denom = max(1, min(len(clean_ids), len(protected_ids)))
        overlap = len(set(clean_ids) & set(protected_ids)) / denom

        return SearchComparison(
            clean=clean,
            protected=protected,
            protection=report,
            protected_vector_bytes=vector_bytes,
            protected_wire_bytes=len(wire),
            top1_preserved=bool(
                clean_ids and protected_ids and clean_ids[0] == protected_ids[0]
            ),
            top_k_overlap=overlap,
        )
