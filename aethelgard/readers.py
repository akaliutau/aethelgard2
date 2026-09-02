from __future__ import annotations

import json
from dataclasses import dataclass
from typing import BinaryIO

from .domain import ArtifactRef, ParsedArtifact


_TEXT_TYPES = {
    'text/plain', 'text/markdown', 'text/csv', 'application/json',
    'application/hl7-v2', 'text/x-hl7',
}


@dataclass(frozen=True, slots=True)
class TextReader:
    @property
    def fingerprint(self) -> str:
        return 'reader:text:v1'

    def accepts(self, artifact: ArtifactRef) -> bool:
        return artifact.media_type in _TEXT_TYPES or artifact.relpath.suffix.lower() in {'.txt', '.md', '.csv', '.hl7', '.json'}

    def read(self, artifact: ArtifactRef, stream: BinaryIO) -> ParsedArtifact:
        raw = stream.read()
        text = raw.decode('utf-8', errors='replace')
        if artifact.relpath.suffix.lower() == '.json':
            try:
                text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                pass
        return ParsedArtifact(source=artifact, text=text)


@dataclass(frozen=True, slots=True)
class ImageReader:
    @property
    def fingerprint(self) -> str:
        return 'reader:image:v1'

    def accepts(self, artifact: ArtifactRef) -> bool:
        return artifact.media_type.startswith('image/') or artifact.relpath.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'}

    def read(self, artifact: ArtifactRef, stream: BinaryIO) -> ParsedArtifact:
        return ParsedArtifact(source=artifact, binary=stream.read())


@dataclass(frozen=True, slots=True)
class PdfTextReader:
    @property
    def fingerprint(self) -> str:
        return 'reader:pdf:pypdf:v1'

    def accepts(self, artifact: ArtifactRef) -> bool:
        return artifact.media_type == 'application/pdf' or artifact.relpath.suffix.lower() == '.pdf'

    def read(self, artifact: ArtifactRef, stream: BinaryIO) -> ParsedArtifact:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError('PDF support requires `pip install aethelgard-vault[pdf]`') from exc
        reader = PdfReader(stream)
        text = '\n\n'.join((page.extract_text() or '') for page in reader.pages)
        return ParsedArtifact(source=artifact, text=text)


class ReaderRegistry:
    def __init__(self, *readers) -> None:
        self._readers = readers or (TextReader(), ImageReader(), PdfTextReader())

    @property
    def fingerprint(self) -> str:
        return '|'.join(r.fingerprint for r in self._readers)

    def read(self, artifact: ArtifactRef, stream: BinaryIO) -> ParsedArtifact:
        for reader in self._readers:
            if reader.accepts(artifact):
                return reader.read(artifact, stream)
        raise ValueError(f'No reader for {artifact.relpath} ({artifact.media_type})')
