from aethelgard.domain import Extraction
from aethelgard.privacy import DefaultEvidencePolicy


def test_privacy_removes_keys_and_patterns():
    result = DefaultEvidencePolicy().evaluate(Extraction(
        evidence={
            'name': 'Maria Jensen',
            'diagnosis': 'pneumothorax',
            'note': 'Contact maria@example.com on 2026-05-04; MRN: ABC-1234',
        },
        provenance={},
        model='test',
    ))
    assert 'name' not in result.evidence
    assert 'maria@example.com' not in result.evidence['note']
    assert '2026-05-04' not in result.evidence['note']
    assert result.report['redaction_count'] >= 3
