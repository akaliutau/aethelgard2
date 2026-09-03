from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from io import BytesIO
from typing import Sequence

from ...config import VaultConfig
from ...domain import ProcessedCase
from ...pipeline import Pipeline
from ...remote_codec import decode_results


@dataclass(slots=True)
class HTTPRemoteExecutor:
    endpoint: str
    config: VaultConfig
    pipeline: Pipeline
    timeout_seconds: float = 1800.0

    @property
    def fingerprint(self) -> str:
        return f'executor:http:v1:{self.endpoint}'

    def process(self, case_ids: Sequence[str] | None = None) -> Sequence[ProcessedCase]:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError('Remote execution requires `pip install -e .[cloud]`') from exc
        cases = self.pipeline.cases()
        wanted = set(case_ids or cases.keys())
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('job.json', json.dumps({
                'config': self.config.model_dump(),
                'case_ids': sorted(wanted),
            }))
            for case_id, artifacts in cases.items():
                if case_id not in wanted:
                    continue
                for artifact in artifacts:
                    with self.pipeline.source.open(artifact) as fh:
                        zf.writestr(f'source/{artifact.relpath.as_posix()}', fh.read())
        response = httpx.post(
            self.endpoint.rstrip('/') + '/v1/process',
            content=buffer.getvalue(),
            headers={'content-type': 'application/zip'},
            timeout=self.timeout_seconds,
        )
        if response.is_error:
            raise RuntimeError(
                f'Remote worker failed ({response.status_code}): {response.text}'
            )
        decoded = decode_results(response.content)
        by_relpath = {a.relpath.as_posix(): a for artifacts in cases.values() for a in artifacts}
        from dataclasses import replace
        return tuple(replace(item, source_artifacts=tuple(by_relpath.get(a.relpath.as_posix(), a) for a in item.source_artifacts)) for item in decoded)
