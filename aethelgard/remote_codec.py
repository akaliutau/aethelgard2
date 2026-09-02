from __future__ import annotations

import json
import zipfile
from dataclasses import asdict
from io import BytesIO
from pathlib import PurePosixPath
from typing import Sequence

from .domain import ArtifactRef, DerivedBlob, Extraction, PolicyResult, ProcessedCase


def encode_results(items: Sequence[ProcessedCase]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        index = []
        for i, item in enumerate(items):
            prefix = f'cases/{i}'
            blobs = []
            for j, blob in enumerate(item.derived):
                blob_path = f'{prefix}/blobs/{j}-{blob.filename}'
                zf.writestr(blob_path, blob.data)
                blobs.append({
                    'kind': blob.kind,
                    'filename': blob.filename,
                    'media_type': blob.media_type,
                    'metadata': blob.metadata,
                    'path': blob_path,
                })
            index.append({
                'case_id': item.case_id,
                'semantic_fingerprint': item.semantic_fingerprint,
                'raw_extraction': {
                    'evidence': item.raw_extraction.evidence,
                    'provenance': item.raw_extraction.provenance,
                    'model': item.raw_extraction.model,
                    'metrics': item.raw_extraction.metrics,
                },
                'policy': {'evidence': item.policy.evidence, 'report': item.policy.report},
                'source_artifacts': [
                    {
                        'uri': a.uri, 'relpath': a.relpath.as_posix(), 'media_type': a.media_type,
                        'size': a.size, 'sha256': a.sha256,
                    }
                    for a in item.source_artifacts
                ],
                'elapsed_ms': item.elapsed_ms,
                'blobs': blobs,
            })
        zf.writestr('results.json', json.dumps(index, ensure_ascii=False))
    return buffer.getvalue()


def decode_results(payload: bytes) -> tuple[ProcessedCase, ...]:
    with zipfile.ZipFile(BytesIO(payload), 'r') as zf:
        index = json.loads(zf.read('results.json'))
        out = []
        for item in index:
            blobs = tuple(DerivedBlob(
                kind=b['kind'], filename=b['filename'], media_type=b['media_type'],
                metadata=b.get('metadata') or {}, data=zf.read(b['path'])
            ) for b in item['blobs'])
            source = tuple(ArtifactRef(
                uri=a['uri'], relpath=PurePosixPath(a['relpath']), media_type=a['media_type'],
                size=a['size'], sha256=a['sha256']
            ) for a in item['source_artifacts'])
            raw = item['raw_extraction']
            out.append(ProcessedCase(
                case_id=item['case_id'],
                semantic_fingerprint=item['semantic_fingerprint'],
                raw_extraction=Extraction(raw['evidence'], raw['provenance'], raw['model'], raw.get('metrics') or {}),
                policy=PolicyResult(item['policy']['evidence'], item['policy']['report']),
                derived=blobs,
                source_artifacts=source,
                elapsed_ms=item['elapsed_ms'],
            ))
        return tuple(out)
