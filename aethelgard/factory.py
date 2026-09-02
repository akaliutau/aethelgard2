from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .adapters.extractors import FunctionGemmaEvidenceExtractor, RegexEvidenceExtractor, StructuredEvidenceExtractor
from .adapters.materializers import (
    EmbeddingGemmaEncoder,
    EvidenceFilesMaterializer,
    MedSigLIPEncoder,
    MultimodalEmbeddingMaterializer,
)
from .adapters.models import FunctionGemmaToolModel, QwenStructuredModel
from .adapters.sources import FsspecArtifactSource, LocalFilesystemSource
from .cases import ParentDirectoryCaseResolver
from .config import VaultConfig
from .pipeline import Pipeline
from .plugins import PluginRegistry
from .privacy import DefaultEvidencePolicy
from .readers import ReaderRegistry


@dataclass(frozen=True, slots=True)
class ProcessingComponents:
    readers: ReaderRegistry
    resolver: object
    extractor: object
    policy: object
    materializers: tuple


def build_source(vault_root: Path, config: VaultConfig):
    if config.source.kind == 'local':
        source_path = Path(config.source.uri)
        if not source_path.is_absolute():
            source_path = vault_root / source_path
        return LocalFilesystemSource(source_path)
    if config.source.kind == 'fsspec':
        options = {'token': 'anon'} if config.source.anonymous and config.source.uri.startswith('gs://') else {}
        return FsspecArtifactSource(config.source.uri, options)
    raise ValueError(f'Unknown source kind: {config.source.kind}')


def build_extractor(config: VaultConfig):
    if config.extractor.kind == 'regex':
        return RegexEvidenceExtractor()
    if config.extractor.kind == 'qwen':
        model = QwenStructuredModel(
            model_name=config.extractor.model,
            device=config.extractor.device,
            max_new_tokens=config.extractor.max_new_tokens,
        )
        return StructuredEvidenceExtractor(model)
    if config.extractor.kind == 'functiongemma':
        model = FunctionGemmaToolModel(
            model_name=config.extractor.model,
            device=config.extractor.device,
            max_new_tokens=config.extractor.max_new_tokens,
        )
        return FunctionGemmaEvidenceExtractor(model)
    factory = PluginRegistry().resolve('extractors', config.extractor.kind)
    return factory(config.extractor)


def build_components(config: VaultConfig) -> ProcessingComponents:
    materializers = [EvidenceFilesMaterializer()]
    if config.embeddings.enabled:
        materializers.append(MultimodalEmbeddingMaterializer(
            text_encoder=EmbeddingGemmaEncoder(
                model_name=config.embeddings.text_model,
                dimensions=config.embeddings.text_dimensions,
                device=config.embeddings.device,
            ),
            image_encoder=MedSigLIPEncoder(
                model_name=config.embeddings.image_model,
                device=config.embeddings.device,
            ),
            text_weight=config.embeddings.text_weight,
            image_weight=config.embeddings.image_weight,
        ))
    return ProcessingComponents(
        readers=ReaderRegistry(),
        resolver=ParentDirectoryCaseResolver(),
        extractor=build_extractor(config),
        policy=DefaultEvidencePolicy(),
        materializers=tuple(materializers),
    )


def build_pipeline(vault_root: Path, config: VaultConfig, components: ProcessingComponents | None = None) -> Pipeline:
    c = components or build_components(config)
    return Pipeline(
        source=build_source(vault_root, config),
        readers=c.readers,
        resolver=c.resolver,
        extractor=c.extractor,
        policy=c.policy,
        materializers=c.materializers,
    )
