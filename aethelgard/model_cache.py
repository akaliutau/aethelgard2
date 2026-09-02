from __future__ import annotations

import json
import os
from pathlib import Path

from .auth import hf_token


def main() -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError('Model caching requires `pip install -e .[models]`') from exc

    raw = os.environ.get('AETHELGARD_CACHE_MODELS', '').strip()
    models = tuple(x.strip() for x in raw.split(';') if x.strip())
    if not models:
        raise RuntimeError('AETHELGARD_CACHE_MODELS is empty')

    cache_dir = Path(os.environ.get('HF_HUB_CACHE', Path.home() / '.cache' / 'huggingface' / 'hub'))
    cache_dir.mkdir(parents=True, exist_ok=True)
    token = hf_token()

    print(f'Caching {len(models)} model(s) in {cache_dir}')
    snapshots: dict[str, str] = {}
    for model in models:
        print(f'→ {model}')
        snapshots[model] = snapshot_download(
            repo_id=model,
            cache_dir=cache_dir,
            token=token,
        )

    hf_home = Path(os.environ.get('HF_HOME', cache_dir.parent))
    marker = hf_home / 'aethelgard-models.json'
    marker.write_text(json.dumps({'models': models, 'snapshots': snapshots}, indent=2, sort_keys=True))
    print(f'Model cache complete: {marker}')


if __name__ == '__main__':
    main()
