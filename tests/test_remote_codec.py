from pathlib import PurePosixPath

from aethelgard.domain import ArtifactRef, DerivedBlob, Extraction, PolicyResult, ProcessedCase
from aethelgard.remote_codec import decode_results, encode_results


def test_remote_result_roundtrip():
    item = ProcessedCase(
        case_id='CASE-X',
        semantic_fingerprint='abc',
        raw_extraction=Extraction({'x': 1}, {'a': ['b']}, 'model'),
        policy=PolicyResult({'x': 1}, {'passed': True}),
        derived=(DerivedBlob('evidence', 'evidence.json', 'application/json', b'{"x":1}'),),
        source_artifacts=(ArtifactRef('file:///x', PurePosixPath('CASE-X/note.txt'), 'text/plain', 3, 'deadbeef'),),
        elapsed_ms=12,
    )
    decoded = decode_results(encode_results([item]))
    assert decoded[0].case_id == 'CASE-X'
    assert decoded[0].derived[0].data == b'{"x":1}'
