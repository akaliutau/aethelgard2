from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str = 'local'
    uri: str = '.'
    anonymous: bool = False


class ExtractorConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str = 'qwen'
    model: str = 'Qwen/Qwen3-4B'
    device: str = 'cpu'
    max_new_tokens: int = 1024


class EmbeddingsConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = True
    text_model: str = 'google/embeddinggemma-300m'
    text_dimensions: int = 256
    image_model: str = 'google/medsiglip-448'
    device: str = 'cpu'
    text_weight: float = 0.45
    image_weight: float = 0.55


class VaultConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: SourceConfig = Field(default_factory=SourceConfig)
    extractor: ExtractorConfig = Field(default_factory=ExtractorConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)

    @classmethod
    def load(cls, path: Path) -> 'VaultConfig':
        return cls.model_validate(tomllib.loads(path.read_text()))

    def to_toml(self) -> str:
        s, e, m = self.source, self.extractor, self.embeddings
        return f'''# Aethelgard Vault configuration\n\n[source]\nkind = "{s.kind}"\nuri = "{s.uri}"\nanonymous = {str(s.anonymous).lower()}\n\n[extractor]\nkind = "{e.kind}"\nmodel = "{e.model}"\ndevice = "{e.device}"\nmax_new_tokens = {e.max_new_tokens}\n\n[embeddings]\nenabled = {str(m.enabled).lower()}\ntext_model = "{m.text_model}"\ntext_dimensions = {m.text_dimensions}\nimage_model = "{m.image_model}"\ndevice = "{m.device}"\ntext_weight = {m.text_weight}\nimage_weight = {m.image_weight}\n'''
