from __future__ import annotations

import hashlib
import mimetypes
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO, Iterator, Sequence

from ...domain import ArtifactRef


@dataclass(slots=True)
class FsspecArtifactSource:
    """Artifact source for local/cloud URLs through fsspec.

    Examples: file:///data, gs://bucket/prefix, s3://bucket/prefix.
    GCS requires the optional gcsfs package. For a public GCS bucket use
    storage_options={"token": "anon"}.
    """

    uri: str
    storage_options: dict | None = None

    def __post_init__(self) -> None:
        import fsspec
        self._fs, self._root = fsspec.core.url_to_fs(self.uri, **(self.storage_options or {}))
        self._root = self._root.rstrip('/')

    @property
    def fingerprint(self) -> str:
        return f'source:fsspec:v1:{self.uri}'

    def scan(self) -> Sequence[ArtifactRef]:
        refs: list[ArtifactRef] = []
        for path in sorted(self._fs.find(self._root)):
            info = self._fs.info(path)
            if info.get('type') == 'directory':
                continue
            rel = path[len(self._root):].lstrip('/')
            if rel.startswith('.aethelgard/'):
                continue
            with self._fs.open(path, 'rb') as fh:
                h = hashlib.sha256()
                size = 0
                for chunk in iter(lambda: fh.read(1024 * 1024), b''):
                    h.update(chunk)
                    size += len(chunk)
            media_type = mimetypes.guess_type(rel)[0] or 'application/octet-stream'
            refs.append(ArtifactRef(
                uri=f'{self.uri.rstrip("/")}/{rel}',
                relpath=PurePosixPath(rel),
                media_type=media_type,
                size=size,
                sha256=h.hexdigest(),
            ))
        return tuple(refs)

    @contextmanager
    def open(self, ref: ArtifactRef) -> Iterator[BinaryIO]:
        path = f'{self._root}/{ref.relpath.as_posix()}'
        with self._fs.open(path, 'rb') as fh:
            yield fh
