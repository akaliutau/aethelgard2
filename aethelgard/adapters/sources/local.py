from __future__ import annotations

import hashlib
import mimetypes
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterator, Sequence

from ...domain import ArtifactRef


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True, slots=True)
class LocalFilesystemSource:
    root: Path

    @property
    def fingerprint(self) -> str:
        return f'source:local:v1:{self.root.resolve()}'

    def scan(self) -> Sequence[ArtifactRef]:
        root = self.root.resolve()
        refs: list[ArtifactRef] = []
        for path in sorted(root.rglob('*')):
            if not path.is_file() or '.aethelgard' in path.parts:
                continue
            rel = path.relative_to(root)
            media_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            refs.append(ArtifactRef(
                uri=path.as_uri(),
                relpath=PurePosixPath(rel.as_posix()),
                media_type=media_type,
                size=path.stat().st_size,
                sha256=_sha256(path),
            ))
        return tuple(refs)

    @contextmanager
    def open(self, ref: ArtifactRef) -> Iterator[BinaryIO]:
        path = self.root / Path(*ref.relpath.parts)
        with path.open('rb') as fh:
            yield fh
