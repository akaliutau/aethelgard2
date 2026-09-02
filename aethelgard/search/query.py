from __future__ import annotations

from dataclasses import dataclass

from .domain import QueryVectors


@dataclass(slots=True)
class MultimodalQueryEncoder:
    text_encoder: object
    image_encoder: object
    text_weight: float = 0.45
    image_weight: float = 0.55

    @property
    def fingerprint(self) -> str:
        return (
            f'query-encoder:mm:v1:{self.text_encoder.fingerprint}:'
            f'{self.image_encoder.fingerprint}:{self.text_weight:.4f}:{self.image_weight:.4f}'
        )

    def encode(self, text: str, image: bytes | None = None) -> QueryVectors:
        if not text.strip():
            raise ValueError('Search query must contain text')

        text_vector = self.text_encoder.encode_query([text])[0]
        components: dict[str, object] = {'clinical_text': text_vector}
        weights: dict[str, float] = {'clinical_text': max(0.0, float(self.text_weight))}

        if image is not None:
            image_vectors = self.image_encoder.encode_images([image])
            if not image_vectors:
                raise ValueError('Image encoder returned no vector')
            components['medical_image'] = image_vectors[0]
            weights['medical_image'] = max(0.0, float(self.image_weight))

        total = sum(weights.values()) or 1.0
        weights = {name: value / total for name, value in weights.items()}
        return QueryVectors(
            profile='aethelgard-mm-v1',
            components=components,
            weights=weights,
        )
