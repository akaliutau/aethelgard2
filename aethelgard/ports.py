from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO, Iterable, Mapping, Protocol, Sequence, runtime_checkable

from .domain import (
    ArtifactRef,
    CaseBundle,
    DerivedBlob,
    Extraction,
    ExtractionContext,
    JSONValue,
    PolicyResult,
    ProcessedCase,
)


@runtime_checkable
class ArtifactSource(Protocol):
    @property
    def fingerprint(self) -> str: ...
    def scan(self) -> Sequence[ArtifactRef]: ...
    def open(self, ref: ArtifactRef) -> AbstractContextManager[BinaryIO]: ...


@runtime_checkable
class ArtifactReader(Protocol):
    @property
    def fingerprint(self) -> str: ...
    def accepts(self, artifact: ArtifactRef) -> bool: ...
    def read(self, artifact: ArtifactRef, stream: BinaryIO): ...


@runtime_checkable
class CaseResolver(Protocol):
    @property
    def fingerprint(self) -> str: ...
    def resolve(self, artifacts: Sequence[ArtifactRef]) -> Mapping[str, Sequence[ArtifactRef]]: ...


@runtime_checkable
class EvidenceExtractor(Protocol):
    @property
    def fingerprint(self) -> str: ...
    def extract(self, bundle: CaseBundle, context: ExtractionContext) -> Extraction: ...


@runtime_checkable
class StructuredToolModel(Protocol):
    @property
    def fingerprint(self) -> str: ...
    def call(self, *, prompt: str, function_name: str, description: str) -> dict[str, object]: ...


@runtime_checkable
class EvidencePolicy(Protocol):
    @property
    def fingerprint(self) -> str: ...
    def evaluate(self, extraction: Extraction) -> PolicyResult: ...


@runtime_checkable
class TextEncoder(Protocol):
    @property
    def fingerprint(self) -> str: ...
    def encode(self, texts: Sequence[str]) -> Sequence[object]: ...


@runtime_checkable
class ImageEncoder(Protocol):
    @property
    def fingerprint(self) -> str: ...
    def encode_images(self, images: Sequence[bytes]) -> Sequence[object]: ...


@runtime_checkable
class Materializer(Protocol):
    @property
    def fingerprint(self) -> str: ...
    def build(self, bundle: CaseBundle, extraction: Extraction, policy: PolicyResult) -> Sequence[DerivedBlob]: ...


@runtime_checkable
class Executor(Protocol):
    @property
    def fingerprint(self) -> str: ...
    def process(self, *, vault_root: Path, case_ids: Sequence[str] | None = None) -> Sequence[ProcessedCase]: ...
