from __future__ import annotations

import shutil
from pathlib import Path

from aethelgard.adapters.executors.local import LocalExecutor
from aethelgard.config import EmbeddingsConfig, ExtractorConfig, SourceConfig, VaultConfig
from aethelgard.factory import build_pipeline
from aethelgard.vault import Vault


def make_vault(tmp_path: Path) -> tuple[Vault, object]:
    src = Path(__file__).parents[1] / 'demo'
    root = tmp_path / 'vault'
    shutil.copytree(src, root)
    config = VaultConfig(
        source=SourceConfig(kind='local', uri='.'),
        extractor=ExtractorConfig(kind='regex'),
        embeddings=EmbeddingsConfig(enabled=False),
    )
    vault = Vault.init(root, config)
    return vault, build_pipeline(root, config)


def test_smoke_semantic_workflow(tmp_path: Path):
    vault, pipeline = make_vault(tmp_path)
    before = vault.status(pipeline)
    assert all(s.dirty for s in before)
    dirty = [s.case_id for s in before if s.dirty]
    results = LocalExecutor(vault, pipeline).process(dirty)
    revision = vault.commit(results, pipeline)
    assert revision
    assert all(not s.dirty for s in vault.status(pipeline))
    evidence = vault.show_json('CASE-001')
    assert evidence['diagnosis'].startswith('spontaneous right pneumothorax')
    assert vault.verify() == []


def test_source_change_and_diff(tmp_path: Path):
    vault, pipeline = make_vault(tmp_path)
    first = LocalExecutor(vault, pipeline).process()
    vault.commit(first, pipeline)
    note = vault.root / 'CASE-001' / 'note.txt'
    note.write_text(note.read_text().replace(
        'Outcome: oxygen saturation improved to 96%; respiratory distress rapidly resolved.',
        'Outcome: oxygen saturation improved to 98%; patient discharged after observation.'
    ))
    dirty = [s for s in vault.status(pipeline) if s.case_id == 'CASE-001'][0]
    assert 'source changed' in dirty.reasons
    second = LocalExecutor(vault, pipeline).process(['CASE-001'])
    vault.commit(second, pipeline)
    assert 'oxygen saturation improved to 98%' in vault.diff('CASE-001')


def test_pipeline_change_marks_clean_case_dirty(tmp_path: Path):
    vault, pipeline = make_vault(tmp_path)
    vault.commit(LocalExecutor(vault, pipeline).process(), pipeline)
    new_config = VaultConfig(
        source=SourceConfig(kind='local', uri='.'),
        extractor=ExtractorConfig(kind='regex'),
        embeddings=EmbeddingsConfig(enabled=True),
    )
    changed = build_pipeline(vault.root, new_config)
    status = vault.status(changed)
    assert all('semantic processor changed' in s.reasons for s in status)
