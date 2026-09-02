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
    model: str = 'Qwen/Qwen3-4B-Instruct-2507'
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


class ProtectionConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str = 'gaussian'
    text_sigma: float = 0.01
    image_sigma: float = 0.02


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    top_k: int = 5
    summary_facts: int = 4
    protection: ProtectionConfig = Field(default_factory=ProtectionConfig)


class VaultConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: SourceConfig = Field(default_factory=SourceConfig)
    extractor: ExtractorConfig = Field(default_factory=ExtractorConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)

    @classmethod
    def load(cls, path: Path) -> 'VaultConfig':
        return cls.model_validate(tomllib.loads(path.read_text()))

    def to_toml(self) -> str:
        s, e, m, q = self.source, self.extractor, self.embeddings, self.search
        p = q.protection
        return f"""# Aethelgard Vault configuration

[source]
kind = "{s.kind}"
uri = "{s.uri}"
anonymous = {str(s.anonymous).lower()}

[extractor]
kind = "{e.kind}"
model = "{e.model}"
device = "{e.device}"
max_new_tokens = {e.max_new_tokens}

[embeddings]
enabled = {str(m.enabled).lower()}
text_model = "{m.text_model}"
text_dimensions = {m.text_dimensions}
image_model = "{m.image_model}"
device = "{m.device}"
text_weight = {m.text_weight}
image_weight = {m.image_weight}

[search]
top_k = {q.top_k}
summary_facts = {q.summary_facts}

[search.protection]
kind = "{p.kind}"
text_sigma = {p.text_sigma}
image_sigma = {p.image_sigma}
"""
