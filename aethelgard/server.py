from __future__ import annotations

import json
import os
import tempfile
import threading
import zipfile
from io import BytesIO
from pathlib import Path

try:
    from fastapi import FastAPI, HTTPException, Request, Response
except ImportError as exc:
    raise RuntimeError('Worker service requires `pip install -e .[cloud]`') from exc

from .adapters.executors.local import LocalExecutor
from .config import SourceConfig, VaultConfig
from .factory import build_components, build_pipeline
from .remote_codec import encode_results
from .vault import Vault


def runtime_config(config: VaultConfig) -> VaultConfig:
    """Normalize client config for the worker without changing model identity.

    The client still supplies model names and semantic configuration. The worker
    may only override execution location/device, which is intentionally not part
    of the semantic meaning of the extracted evidence.
    """

    device = os.environ.get('AETHELGARD_WORKER_DEVICE', '').strip()
    update: dict[str, object] = {
        'source': SourceConfig(kind='local', uri='.'),
    }
    if device:
        update['extractor'] = config.extractor.model_copy(update={'device': device})
        update['embeddings'] = config.embeddings.model_copy(update={'device': device})
    return config.model_copy(update=update)


class WorkerRuntime:
    """Caches heavyweight model components across Cloud Run requests."""

    def __init__(self) -> None:
        self._cache: dict[str, object] = {}
        self._lock = threading.Lock()

    def components(self, config: VaultConfig):
        config = runtime_config(config)
        key = json.dumps(
            {
                'extractor': config.extractor.model_dump(),
                'embeddings': config.embeddings.model_dump(),
            },
            sort_keys=True,
            separators=(',', ':'),
        )
        with self._lock:
            if key not in self._cache:
                self._cache[key] = build_components(config)
            return self._cache[key]


_runtime = WorkerRuntime()


def create_app():
    app = FastAPI(title='Aethelgard Vault Worker', version='0.6.0')

    @app.get('/')
    def root():
        return {
            'service': 'aethelgard-vault-worker',
            'status': 'ok',
            'health': '/healthz',
            'process': '/v1/process',
        }

    @app.get('/healthz')
    def healthz():
        return {
            'status': 'ok',
            'device': os.environ.get('AETHELGARD_WORKER_DEVICE', 'client-config'),
            'hf_offline': os.environ.get('HF_HUB_OFFLINE') == '1',
        }

    @app.post('/v1/process')
    async def process(request: Request):
        payload = await request.body()
        max_bytes = 25 * 1024 * 1024
        if len(payload) > max_bytes:
            raise HTTPException(413, f'Job is larger than {max_bytes} bytes')
        with tempfile.TemporaryDirectory(prefix='aethelgard-worker-') as tmp:
            root = Path(tmp)
            try:
                with zipfile.ZipFile(BytesIO(payload), 'r') as zf:
                    names = zf.namelist()
                    if 'job.json' not in names:
                        raise ValueError('job.json missing')
                    for name in names:
                        target = (root / name).resolve()
                        if root.resolve() not in target.parents and target != root.resolve():
                            raise ValueError(f'unsafe zip member: {name}')
                    zf.extractall(root)
                job = json.loads((root / 'job.json').read_text())
                client_config = VaultConfig.model_validate(job['config'])
                config = runtime_config(client_config)
                config = config.model_copy(update={'source': SourceConfig(kind='local', uri='source')})
                vault = Vault.init(root, config)
                pipeline = build_pipeline(root, config, _runtime.components(client_config))
                executor = LocalExecutor(vault, pipeline)
                results = executor.process(job.get('case_ids'))
                return Response(content=encode_results(results), media_type='application/zip')
            except Exception as exc:
                import traceback
                traceback.print_exc()
                raise HTTPException(500, str(exc)) from exc
    return app


app = create_app()
