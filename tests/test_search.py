from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from aethelgard.adapters.materializers.embeddings import (
    EvidenceFactsMaterializer,
    flatten_evidence,
)
from aethelgard.cases import ParentDirectoryCaseResolver
from aethelgard.domain import ArtifactRef, CaseBundle, Extraction, PolicyResult
from aethelgard.search import (
    GaussianVectorProtector,
    NumpyVaultSearchIndex,
    QueryVectors,
    RankedEvidenceSelector,
    VaultSearch,
    encode_protected_query,
)


class FakeTextEncoder:
    fingerprint = 'fake-text:v1'
    dimensions = 3

    def encode(self, texts):
        mapping = {
            'diagnosis: pneumothorax': np.array([1.0, 0.0, 0.0], dtype=np.float32),
            'treatment: tube thoracostomy': np.array([0.9, 0.1, 0.0], dtype=np.float32),
        }
        return [mapping.get(text, np.array([0.0, 1.0, 0.0], dtype=np.float32)) for text in texts]


class FakeVault:
    def __init__(self, root: Path):
        self.root = root

    def case_ids(self):
        return ('CASE-A', 'CASE-B')

    def current_output(self, case_id: str):
        return self.root / case_id


def _write_case(root: Path, case_id: str, text_vector, image_vector, facts, fact_vectors):
    out = root / case_id
    out.mkdir(parents=True)
    np.savez_compressed(
        out / 'embeddings.npz',
        clinical_text=np.asarray(text_vector, dtype=np.float32),
        medical_image=np.asarray(image_vector, dtype=np.float32),
    )
    (out / 'evidence_facts.json').write_text(json.dumps({
        'facts': [{'text': fact} for fact in facts],
    }))
    np.savez_compressed(
        out / 'evidence_facts.npz',
        vectors=np.asarray(fact_vectors, dtype=np.float32),
    )
    (out / 'manifest.json').write_text(json.dumps({
        'case_id': case_id,
        'revision_id': f'rev-{case_id}',
    }))


def test_parent_directory_resolver_handles_wrapper_directory():
    refs = (
        ArtifactRef('file:///x', Path('demo/CASE-001/note.txt'), 'text/plain', 1, 'a'),
        ArtifactRef('file:///y', Path('demo/CASE-002/note.txt'), 'text/plain', 1, 'b'),
    )
    grouped = ParentDirectoryCaseResolver().resolve(refs)
    assert tuple(grouped) == ('CASE-001', 'CASE-002')


def test_evidence_facts_are_searchable_derived_artifacts():
    evidence = {'diagnosis': 'pneumothorax', 'treatment': 'tube thoracostomy'}
    facts = flatten_evidence(evidence)
    assert [item['text'] for item in facts] == [
        'diagnosis: pneumothorax',
        'treatment: tube thoracostomy',
    ]

    materializer = EvidenceFactsMaterializer(FakeTextEncoder())
    blobs = materializer.build(
        CaseBundle('CASE-X', (), ()),
        Extraction(evidence, {}, 'test'),
        PolicyResult(evidence, {'passed': True}),
    )
    assert {blob.filename for blob in blobs} == {'evidence_facts.json', 'evidence_facts.npz'}


def test_numpy_search_and_evidence_ranking(tmp_path: Path):
    _write_case(
        tmp_path, 'CASE-A',
        [1.0, 0.0], [1.0, 0.0],
        ['diagnosis: pneumothorax', 'treatment: tube thoracostomy'],
        [[1.0, 0.0], [0.9, 0.1]],
    )
    _write_case(
        tmp_path, 'CASE-B',
        [0.0, 1.0], [0.0, 1.0],
        ['diagnosis: heart failure'],
        [[0.0, 1.0]],
    )

    index = NumpyVaultSearchIndex(FakeVault(tmp_path))
    selector = RankedEvidenceSelector(index)
    vectors = QueryVectors(
        profile='test',
        components={'clinical_text': np.array([1.0, 0.0], dtype=np.float32)},
        weights={'clinical_text': 1.0},
    )
    candidates = index.search(vectors, top_k=2)
    assert candidates[0].case_id == 'CASE-A'
    summary = selector.select('CASE-A', vectors, limit=1)
    assert summary == ('diagnosis: pneumothorax',)


def test_protected_query_contains_vectors_but_no_raw_query():
    clean = QueryVectors(
        profile='test',
        components={
            'clinical_text': np.array([1.0, 0.0], dtype=np.float32),
            'medical_image': np.array([0.0, 1.0], dtype=np.float32),
        },
        weights={'clinical_text': 0.45, 'medical_image': 0.55},
    )
    protector = GaussianVectorProtector(text_sigma=0.01, image_sigma=0.02)
    protected, report = protector.protect(clean, seed=42)
    envelope, payload = encode_protected_query(protected, report)

    assert envelope['components']['clinical_text']['dimensions'] == 2
    assert envelope['components']['medical_image']['dimensions'] == 2
    assert b'pneumothorax' not in payload
    assert report.component_cosine['clinical_text'] < 1.000001
    assert report.component_cosine['clinical_text'] > 0.9
