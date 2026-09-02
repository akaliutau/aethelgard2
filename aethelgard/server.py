import json
import tempfile
import threading
import zipfile
from io import BytesIO
from pathlib import Path

from .adapters.executors.local import LocalExecutor
from .config import SourceConfig, VaultConfig
from .factory import build_components, build_pipeline
from .remote_codec import encode_results
from .vault import Vault


class WorkerRuntime:
    """Caches heavyweight model components across Cloud Run requests."""

    def __init__(self) -> None:
        self._cache: dict[str, object] = {}
        self._lock = threading.Lock()

    def components(self, config: VaultConfig):
        key = config.model_copy(update={'source': SourceConfig(kind='local', uri='.')}).model_dump_json()
        with self._lock:
            if key not in self._cache:
                self._cache[key] = build_components(config)
            return self._cache[key]


_runtime = WorkerRuntime()


def create_app():
    try:
        from fastapi import FastAPI, HTTPException, Request, Response
    except ImportError as exc:
        raise RuntimeError('Worker service requires `pip install -e .[cloud]`') from exc

    app = FastAPI(title='Aethelgard Vault Worker', version='0.4.0')

    @app.get('/healthz')
    def healthz():
        return {'status': 'ok'}

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
                config = VaultConfig.model_validate(job['config'])
                config = config.model_copy(update={'source': SourceConfig(kind='local', uri='source')})
                vault = Vault.init(root, config)
                pipeline = build_pipeline(root, config, _runtime.components(config))
                executor = LocalExecutor(vault, pipeline)
                results = executor.process(job.get('case_ids'))
                return Response(content=encode_results(results), media_type='application/zip')
            except Exception as exc:
                raise HTTPException(500, str(exc)) from exc

    return app


app = create_app()
