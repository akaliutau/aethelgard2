from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from .domain import ProtectionReport, QueryVectors


def _normalize(vector):
    import numpy as np
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else vector


@dataclass(frozen=True, slots=True)
class GaussianVectorProtector:
    text_sigma: float = 0.01
    image_sigma: float = 0.02

    @property
    def fingerprint(self) -> str:
        return f'protector:gaussian:v1:text={self.text_sigma:.6f}:image={self.image_sigma:.6f}'

    def protect(
        self,
        vectors: QueryVectors,
        *,
        seed: int | None = None,
    ) -> tuple[QueryVectors, ProtectionReport]:
        import numpy as np

        rng = np.random.default_rng(seed)
        protected: dict[str, object] = {}
        similarities: dict[str, float] = {}
        parameters: dict[str, float] = {}

        for name, value in vectors.components.items():
            clean = _normalize(value)
            sigma = self.image_sigma if name == 'medical_image' else self.text_sigma
            noisy = _normalize(clean + rng.normal(0.0, sigma, size=clean.shape).astype(np.float32))
            protected[name] = noisy
            similarities[name] = float(np.dot(clean, noisy))
            parameters[f'{name}_sigma'] = float(sigma)

        return (
            QueryVectors(
                profile=vectors.profile,
                components=protected,
                weights=dict(vectors.weights),
            ),
            ProtectionReport(
                algorithm='gaussian-v1',
                parameters=parameters,
                component_cosine=similarities,
            ),
        )


def encode_protected_query(
    vectors: QueryVectors,
    report: ProtectionReport,
) -> tuple[dict, bytes]:
    """Serialize protected vectors as future transport input.

    Raw query text and raw image bytes are intentionally not represented.
    """

    import numpy as np

    components = {}
    for name, value in vectors.components.items():
        vector = np.asarray(value, dtype=np.float32).reshape(-1)
        raw = vector.astype('<f2').tobytes()
        components[name] = {
            'dimensions': int(vector.size),
            'dtype': 'float16',
            'data': base64.b64encode(raw).decode('ascii'),
        }

    envelope = {
        'format': 'aethelgard-protected-query/1',
        'profile': vectors.profile,
        'components': components,
        'weights': dict(vectors.weights),
        'protection': {
            'algorithm': report.algorithm,
            'parameters': dict(report.parameters),
        },
    }
    payload = json.dumps(envelope, separators=(',', ':'), sort_keys=True).encode()
    return envelope, payload
