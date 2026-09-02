from __future__ import annotations

import difflib
import hashlib
import json
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from .config import VaultConfig
from .domain import CaseStatus, ProcessedCase, RevisionRecord
from .errors import VaultNotInitialized
from .pipeline import Pipeline


_SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS cases (
  case_id TEXT PRIMARY KEY,
  source_fingerprint TEXT NOT NULL,
  pipeline_fingerprint TEXT NOT NULL,
  semantic_fingerprint TEXT NOT NULL,
  revision_id TEXT NOT NULL,
  output_dir TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
  revision_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revision_cases (
  revision_id TEXT NOT NULL,
  case_id TEXT NOT NULL,
  semantic_fingerprint TEXT NOT NULL,
  output_dir TEXT NOT NULL,
  PRIMARY KEY (revision_id, case_id)
);
CREATE INDEX IF NOT EXISTS idx_revision_cases_case ON revision_cases(case_id);
'''


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Vault:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.meta = self.root / '.aethelgard'
        self.config_path = self.meta / 'config.toml'
        self.db_path = self.meta / 'state.db'
        self.derived = self.meta / 'derived'
        if not self.config_path.exists() or not self.db_path.exists():
            raise VaultNotInitialized(f'{self.root} is not an Aethelgard vault; run `aethelgard init`')

    @classmethod
    def init(cls, root: Path, config: VaultConfig | None = None, *, force: bool = False) -> 'Vault':
        root = root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        meta = root / '.aethelgard'
        meta.mkdir(mode=0o700, exist_ok=True)
        try:
            os.chmod(meta, 0o700)
        except OSError:
            pass
        config_path = meta / 'config.toml'
        if config_path.exists() and not force:
            raise FileExistsError(f'{config_path} already exists')
        config = config or VaultConfig()
        config_path.write_text(config.to_toml())
        (meta / 'derived').mkdir(exist_ok=True)
        db = sqlite3.connect(meta / 'state.db')
        db.executescript(_SCHEMA)
        db.close()
        return cls(root)

    @property
    def config(self) -> VaultConfig:
        return VaultConfig.load(self.config_path)

    def _db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        return conn

    def status(self, pipeline: Pipeline) -> list[CaseStatus]:
        current = pipeline.cases()
        with self._db() as db:
            head = {row['case_id']: row for row in db.execute('SELECT * FROM cases')}
        statuses: list[CaseStatus] = []
        for case_id, artifacts in current.items():
            source_fp = pipeline.source_fingerprint(artifacts)
            semantic_fp = pipeline.semantic_fingerprint(artifacts)
            row = head.get(case_id)
            reasons: list[str] = []
            if row is None:
                reasons.append('new case')
            else:
                if row['source_fingerprint'] != source_fp:
                    reasons.append('source changed')
                if row['pipeline_fingerprint'] != pipeline.fingerprint:
                    reasons.append('semantic processor changed')
            statuses.append(CaseStatus(
                case_id=case_id,
                dirty=bool(reasons),
                reasons=tuple(reasons),
                source_fingerprint=source_fp,
                semantic_fingerprint=semantic_fp,
                head_semantic_fingerprint=row['semantic_fingerprint'] if row else None,
            ))
        for case_id, row in head.items():
            if case_id not in current:
                statuses.append(CaseStatus(
                    case_id=case_id,
                    dirty=True,
                    reasons=('source deleted',),
                    source_fingerprint='',
                    semantic_fingerprint='',
                    head_semantic_fingerprint=row['semantic_fingerprint'],
                ))
        return sorted(statuses, key=lambda s: s.case_id)

    def commit(self, processed: Sequence[ProcessedCase], pipeline: Pipeline, *, message: str | None = None) -> str | None:
        if not processed:
            return None
        created = _utcnow()
        revision_seed = created + ''.join(sorted(p.semantic_fingerprint for p in processed))
        revision_id = hashlib.sha256(revision_seed.encode()).hexdigest()[:12]
        message = message or f'processed {len(processed)} case(s)'
        with self._db() as db:
            db.execute('INSERT INTO revisions(revision_id, created_at, message) VALUES (?, ?, ?)', (revision_id, created, message))
            for item in processed:
                out_dir = self.derived / item.case_id / item.semantic_fingerprint[:16]
                out_dir.mkdir(parents=True, exist_ok=True)
                try:
                    os.chmod(out_dir, 0o700)
                except OSError:
                    pass
                files = []
                for blob in item.derived:
                    target = out_dir / blob.filename
                    target.write_bytes(blob.data)
                    try:
                        os.chmod(target, 0o600)
                    except OSError:
                        pass
                    files.append({
                        'kind': blob.kind,
                        'filename': blob.filename,
                        'media_type': blob.media_type,
                        'sha256': _sha256_bytes(blob.data),
                        'size': len(blob.data),
                        'metadata': blob.metadata,
                    })
                manifest = {
                    'format': 'aethelgard-vault/1',
                    'case_id': item.case_id,
                    'revision_id': revision_id,
                    'semantic_fingerprint': item.semantic_fingerprint,
                    'source_fingerprint': pipeline.source_fingerprint(item.source_artifacts),
                    'pipeline_fingerprint': pipeline.fingerprint,
                    'extractor': item.raw_extraction.model,
                    'elapsed_ms': item.elapsed_ms,
                    'source_artifacts': [
                        {
                            'uri': a.uri, 'relpath': a.relpath.as_posix(), 'sha256': a.sha256,
                            'size': a.size, 'media_type': a.media_type,
                        }
                        for a in item.source_artifacts
                    ],
                    'files': files,
                }
                manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True).encode()
                (out_dir / 'manifest.json').write_bytes(manifest_bytes)
                db.execute(
                    '''INSERT OR REPLACE INTO cases(case_id, source_fingerprint, pipeline_fingerprint, semantic_fingerprint, revision_id, output_dir, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (
                        item.case_id,
                        pipeline.source_fingerprint(item.source_artifacts),
                        pipeline.fingerprint,
                        item.semantic_fingerprint,
                        revision_id,
                        str(out_dir.relative_to(self.meta)),
                        created,
                    ),
                )
                db.execute(
                    'INSERT INTO revision_cases(revision_id, case_id, semantic_fingerprint, output_dir) VALUES (?, ?, ?, ?)',
                    (revision_id, item.case_id, item.semantic_fingerprint, str(out_dir.relative_to(self.meta))),
                )
            db.commit()
        return revision_id

    def remove_deleted(self, case_ids: Iterable[str]) -> None:
        ids = tuple(case_ids)
        if not ids:
            return
        with self._db() as db:
            db.executemany('DELETE FROM cases WHERE case_id = ?', [(x,) for x in ids])
            db.commit()

    def current_output(self, case_id: str) -> Path:
        with self._db() as db:
            row = db.execute('SELECT output_dir FROM cases WHERE case_id = ?', (case_id,)).fetchone()
        if row is None:
            raise KeyError(case_id)
        return self.meta / row['output_dir']

    def show_json(self, case_id: str, filename: str = 'evidence.json') -> object:
        path = self.current_output(case_id) / filename
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text())

    def derived_files(self, case_id: str) -> list[dict]:
        manifest = self.show_json(case_id, 'manifest.json')
        return manifest['files']

    def log(self, *, limit: int = 20) -> list[RevisionRecord]:
        with self._db() as db:
            rows = db.execute('SELECT * FROM revisions ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
            out = []
            for row in rows:
                cases = tuple(r['case_id'] for r in db.execute(
                    'SELECT case_id FROM revision_cases WHERE revision_id = ? ORDER BY case_id', (row['revision_id'],)
                ))
                out.append(RevisionRecord(row['revision_id'], row['created_at'], row['message'], cases))
            return out

    def case_history(self, case_id: str, *, limit: int = 20) -> list[tuple[str, Path]]:
        with self._db() as db:
            rows = db.execute(
                '''SELECT rc.revision_id, rc.output_dir FROM revision_cases rc
                   JOIN revisions r ON r.revision_id = rc.revision_id
                   WHERE rc.case_id = ? ORDER BY r.created_at DESC LIMIT ?''',
                (case_id, limit),
            ).fetchall()
        return [(r['revision_id'], self.meta / r['output_dir']) for r in rows]

    def diff(self, case_id: str, *, raw: bool = False) -> str:
        history = self.case_history(case_id, limit=2)
        if len(history) < 2:
            return 'No previous semantic revision to diff.'
        filename = 'evidence.raw.json' if raw else 'evidence.json'
        newer_id, newer_dir = history[0]
        older_id, older_dir = history[1]
        old = (older_dir / filename).read_text().splitlines(keepends=True)
        new = (newer_dir / filename).read_text().splitlines(keepends=True)
        return ''.join(difflib.unified_diff(old, new, fromfile=older_id, tofile=newer_id)) or 'No evidence changes.'

    def verify(self) -> list[str]:
        problems: list[str] = []
        with self._db() as db:
            rows = db.execute('SELECT case_id, output_dir FROM cases ORDER BY case_id').fetchall()
        for row in rows:
            out_dir = self.meta / row['output_dir']
            manifest_path = out_dir / 'manifest.json'
            if not manifest_path.exists():
                problems.append(f'{row["case_id"]}: missing manifest')
                continue
            manifest = json.loads(manifest_path.read_text())
            for entry in manifest.get('files', []):
                path = out_dir / entry['filename']
                if not path.exists():
                    problems.append(f'{row["case_id"]}: missing {entry["filename"]}')
                    continue
                actual = _sha256_bytes(path.read_bytes())
                if actual != entry['sha256']:
                    problems.append(f'{row["case_id"]}: checksum mismatch {entry["filename"]}')
        return problems
