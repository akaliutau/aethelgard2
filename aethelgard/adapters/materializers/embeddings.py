from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from typing import Sequence

from ...auth import gated_model_help, hf_token
from ...domain import CaseBundle, DerivedBlob, Extraction, PolicyResult


def _normalize(vector):
    import numpy as np
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else vector


def _fact_text(path: str, value) -> str:
    label = path.replace('.', ' › ').replace('_', ' ').strip()
    return f'{label}: {value}'


def flatten_evidence(value, path: str = '') -> list[dict]:
    """Flatten arbitrary evidence JSON into stable, human-readable atomic facts."""

    facts: list[dict] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f'{path}.{key}' if path else key
            facts.extend(flatten_evidence(child, child_path))
    elif isinstance(value, list):
        for child in value:
            facts.extend(flatten_evidence(child, path))
    else:
        facts.append({
            'path': path or 'evidence',
            'value': value,
            'text': _fact_text(path or 'evidence', value),
        })
    return facts


@dataclass(slots=True)
class EmbeddingGemmaEncoder:
    model_name: str = 'google/embeddinggemma-300m'
    dimensions: int = 256
    device: str = 'cpu'
    _model: object | None = field(default=None, init=False, repr=False)

    @property
    def fingerprint(self) -> str:
        return f'encoder:embeddinggemma:{self.model_name}:{self.dimensions}:v1'

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError('EmbeddingGemma requires `pip install -e .[models]`') from exc
        token = hf_token()
        try:
            self._model = SentenceTransformer(
                self.model_name,
                device=self.device,
                truncate_dim=self.dimensions,
                token=token,
            )
        except Exception as exc:
            if 'gated' in str(exc).lower() or '401' in str(exc) or 'restricted' in str(exc).lower():
                raise gated_model_help(self.model_name, exc) from exc
            raise

    def encode(self, texts: Sequence[str]):
        import numpy as np
        self._ensure_loaded()
        if hasattr(self._model, 'encode_document'):
            matrix = self._model.encode_document(
                list(texts),
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
        else:
            matrix = self._model.encode(
                list(texts),
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
        matrix = np.asarray(matrix, dtype=np.float32)
        if matrix.ndim == 1:
            matrix = matrix[None, :]
        return [_normalize(row) for row in matrix]

    def encode_query(self, texts: Sequence[str]):
        import numpy as np
        self._ensure_loaded()
        if hasattr(self._model, 'encode_query'):
            matrix = self._model.encode_query(
                list(texts),
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
        else:
            matrix = self._model.encode(
                list(texts),
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
        matrix = np.asarray(matrix, dtype=np.float32)
        if matrix.ndim == 1:
            matrix = matrix[None, :]
        return [_normalize(row) for row in matrix]


@dataclass(slots=True)
class MedSigLIPEncoder:
    model_name: str = 'google/medsiglip-448'
    device: str = 'cpu'
    _processor: object | None = field(default=None, init=False, repr=False)
    _model: object | None = field(default=None, init=False, repr=False)

    @property
    def fingerprint(self) -> str:
        return f'encoder:medsiglip:{self.model_name}:v1'

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            from transformers import AutoModel, AutoProcessor
        except ImportError as exc:
            raise RuntimeError('MedSigLIP requires `pip install -e .[models]`') from exc
        token = hf_token()
        try:
            self._processor = AutoProcessor.from_pretrained(self.model_name, token=token)
            self._model = AutoModel.from_pretrained(self.model_name, token=token).to(self.device)
            self._model.eval()
        except Exception as exc:
            if 'gated' in str(exc).lower() or '401' in str(exc) or 'restricted' in str(exc).lower():
                raise gated_model_help(self.model_name, exc) from exc
            raise

    def encode_images(self, images: Sequence[bytes]):
        import numpy as np
        if not images:
            return []
        self._ensure_loaded()
        import torch
        from PIL import Image
        from io import BytesIO

        pil_images = [Image.open(BytesIO(data)).convert('RGB') for data in images]
        inputs = self._processor(images=pil_images, return_tensors='pt').to(self._model.device)
        with torch.inference_mode():
            if hasattr(self._model, 'get_image_features'):
                features = self._model.get_image_features(pixel_values=inputs['pixel_values'])
            else:
                outputs = self._model.vision_model(pixel_values=inputs['pixel_values'])
                features = outputs.pooler_output

        if hasattr(features, 'pooler_output'):
            features = features.pooler_output
        matrix = features.detach().cpu().numpy().astype(np.float32)
        return [_normalize(row) for row in matrix]


@dataclass(slots=True)
class EvidenceFactsMaterializer:
    text_encoder: EmbeddingGemmaEncoder

    @property
    def fingerprint(self) -> str:
        return f'materializer:evidence-facts:v1:{self.text_encoder.fingerprint}'

    def build(self, bundle: CaseBundle, extraction: Extraction, policy: PolicyResult) -> Sequence[DerivedBlob]:
        import numpy as np

        facts = flatten_evidence(policy.evidence)
        texts = [item['text'] for item in facts]
        vectors = (
            np.stack(self.text_encoder.encode(texts)).astype(np.float32)
            if texts
            else np.empty((0, self.text_encoder.dimensions), dtype=np.float32)
        )

        buffer = io.BytesIO()
        np.savez_compressed(buffer, vectors=vectors)
        metadata = {
            'count': len(facts),
            'dimensions': int(vectors.shape[1]) if vectors.ndim == 2 and vectors.shape[0] else self.text_encoder.dimensions,
            'text_encoder': self.text_encoder.fingerprint,
        }
        return (
            DerivedBlob(
                kind='evidence_facts',
                filename='evidence_facts.json',
                media_type='application/json',
                data=json.dumps({'facts': facts}, indent=2, ensure_ascii=False, sort_keys=True).encode(),
                metadata=metadata,
            ),
            DerivedBlob(
                kind='evidence_fact_vectors',
                filename='evidence_facts.npz',
                media_type='application/x-npz',
                data=buffer.getvalue(),
                metadata=metadata,
            ),
        )


@dataclass(slots=True)
class MultimodalEmbeddingMaterializer:
    text_encoder: EmbeddingGemmaEncoder
    image_encoder: MedSigLIPEncoder
    text_weight: float = 0.45
    image_weight: float = 0.55

    @property
    def fingerprint(self) -> str:
        return (
            f'materializer:multimodal:v3:{self.text_encoder.fingerprint}:'
            f'{self.image_encoder.fingerprint}:{self.text_weight:.4f}:{self.image_weight:.4f}'
        )

    def build(self, bundle: CaseBundle, extraction: Extraction, policy: PolicyResult) -> Sequence[DerivedBlob]:
        import numpy as np
        safe_text = json.dumps(policy.evidence, ensure_ascii=False, sort_keys=True)
        text_vec = self.text_encoder.encode([safe_text])[0]
        image_vecs = self.image_encoder.encode_images([part.binary for part in bundle.image_parts if part.binary])
        arrays: dict[str, np.ndarray] = {'clinical_text': text_vec.astype(np.float32)}

        if image_vecs:
            image_vec = _normalize(np.mean(np.stack(image_vecs), axis=0))
            arrays['medical_image'] = image_vec.astype(np.float32)
            tw = max(0.0, float(self.text_weight))
            iw = max(0.0, float(self.image_weight))
            total = tw + iw or 1.0
            tw, iw = tw / total, iw / total
            fused = np.concatenate([np.sqrt(tw) * text_vec, np.sqrt(iw) * image_vec]).astype(np.float32)
            arrays['multimodal'] = _normalize(fused)
        else:
            arrays['multimodal'] = text_vec.astype(np.float32)

        buffer = io.BytesIO()
        np.savez_compressed(buffer, **arrays)
        metadata = {
            'components': {name: int(value.shape[0]) for name, value in arrays.items()},
            'text_encoder': self.text_encoder.fingerprint,
            'image_encoder': self.image_encoder.fingerprint,
            'text_weight': self.text_weight,
            'image_weight': self.image_weight,
        }
        return (
            DerivedBlob(
                kind='multimodal_embeddings',
                filename='embeddings.npz',
                media_type='application/x-npz',
                data=buffer.getvalue(),
                metadata=metadata,
            ),
            DerivedBlob(
                kind='embedding_metadata',
                filename='embeddings.json',
                media_type='application/json',
                data=json.dumps(metadata, indent=2, sort_keys=True).encode(),
                metadata=metadata,
            ),
        )
