from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from .adapters.executors import HTTPRemoteExecutor, LocalExecutor
from .config import EmbeddingsConfig, ExtractorConfig, SourceConfig, VaultConfig
from .factory import build_pipeline
from .vault import Vault

app = typer.Typer(no_args_is_help=True, help='Aethelgard: semantic Git for medical documents.')
console = Console()


def _root(path: Path) -> Path:
    return path.expanduser().resolve()


def _open(path: Path) -> tuple[Vault, object]:
    vault = Vault(_root(path))
    pipeline = build_pipeline(vault.root, vault.config)
    return vault, pipeline


@app.command()
def init(
    path: Annotated[Path, typer.Argument(help='Vault directory')] = Path('.'),
    source: Annotated[str, typer.Option('--source', help='Source URI: . or gs://bucket/prefix')] = '.',
    profile: Annotated[str, typer.Option('--profile', help='full = FunctionGemma+EmbeddingGemma+MedSigLIP; smoke = deterministic/no models')] = 'full',
    anonymous: Annotated[bool, typer.Option('--anonymous', help='Anonymous access for a public fsspec/GCS source')] = False,
):
    root = _root(path)
    source_kind = 'local' if '://' not in source else 'fsspec'
    if profile == 'smoke':
        config = VaultConfig(
            source=SourceConfig(kind=source_kind, uri=source, anonymous=anonymous),
            extractor=ExtractorConfig(kind='regex'),
            embeddings=EmbeddingsConfig(enabled=False),
        )
    elif profile == 'full':
        config = VaultConfig(source=SourceConfig(kind=source_kind, uri=source, anonymous=anonymous))
    else:
        raise typer.BadParameter('profile must be full or smoke')
    Vault.init(root, config)
    console.print(f'[green]Initialized Aethelgard vault[/green] at {root}')
    console.print(f'Config: {root / ".aethelgard" / "config.toml"}')


@app.command()
def status(path: Annotated[Path, typer.Argument()] = Path('.')):
    vault, pipeline = _open(path)
    statuses = vault.status(pipeline)
    table = Table(title='Aethelgard Vault Status')
    table.add_column('State', width=5)
    table.add_column('Case')
    table.add_column('Reason')
    for item in statuses:
        state = '[yellow]M[/yellow]' if item.dirty else '[green]✓[/green]'
        if item.reasons == ('new case',):
            state = '[green]+[/green]'
        if item.reasons == ('source deleted',):
            state = '[red]D[/red]'
        table.add_row(state, item.case_id, ', '.join(item.reasons) or 'clean')
    console.print(table)
    dirty = sum(x.dirty for x in statuses)
    console.print(f'{dirty} case(s) require processing; {len(statuses) - dirty} clean.')


@app.command(name='run')
def run_vault(
    case_ids: Annotated[Optional[list[str]], typer.Argument(help='Optional case IDs')] = None,
    path: Annotated[Path, typer.Option('--path', '-p')] = Path('.'),
    remote: Annotated[Optional[str], typer.Option('--remote', help='Remote worker base URL, e.g. https://worker.run.app')] = None,
):
    vault, pipeline = _open(path)
    statuses = vault.status(pipeline)
    requested = set(case_ids or [])
    dirty_current = [
        s.case_id for s in statuses
        if s.dirty and 'source deleted' not in s.reasons and (not requested or s.case_id in requested)
    ]
    deleted = [s.case_id for s in statuses if 'source deleted' in s.reasons and (not requested or s.case_id in requested)]
    if deleted:
        vault.remove_deleted(deleted)
        for case_id in deleted:
            console.print(f'[red]Removed[/red] {case_id} from vault HEAD')
    if not dirty_current:
        console.print('[green]Nothing to process.[/green]')
        return
    if remote:
        executor = HTTPRemoteExecutor(remote, vault.config, pipeline)
        console.print(f'Processing {len(dirty_current)} case(s) on [cyan]{remote}[/cyan]...')
    else:
        executor = LocalExecutor(vault, pipeline)
        console.print(f'Processing {len(dirty_current)} case(s) locally...')
    results = executor.process(dirty_current)
    revision = vault.commit(results, pipeline)
    for item in results:
        console.print(
            f'[green]✓[/green] {item.case_id}  '
            f'extractor={item.raw_extraction.model}  '
            f'redactions={item.policy.report.get("redaction_count", 0)}  '
            f'{item.elapsed_ms} ms'
        )
    console.print(f'[bold]revision {revision}[/bold]')


@app.command()
def show(
    case_id: Annotated[str, typer.Argument()],
    path: Annotated[Path, typer.Option('--path', '-p')] = Path('.'),
    view: Annotated[str, typer.Option('--view', help='evidence|raw|provenance|privacy|derived|manifest')] = 'evidence',
):
    vault = Vault(_root(path))
    names = {
        'evidence': 'evidence.json',
        'raw': 'evidence.raw.json',
        'provenance': 'provenance.json',
        'privacy': 'privacy.json',
        'manifest': 'manifest.json',
    }
    if view == 'derived':
        console.print_json(data=vault.derived_files(case_id))
        return
    if view not in names:
        raise typer.BadParameter('view must be evidence, raw, provenance, privacy, derived, or manifest')
    console.print_json(data=vault.show_json(case_id, names[view]))


@app.command()
def diff(
    case_id: Annotated[str, typer.Argument()],
    path: Annotated[Path, typer.Option('--path', '-p')] = Path('.'),
    raw: Annotated[bool, typer.Option('--raw')] = False,
):
    vault = Vault(_root(path))
    console.print(vault.diff(case_id, raw=raw), markup=False)


@app.command(name='log')
def log_cmd(
    path: Annotated[Path, typer.Option('--path', '-p')] = Path('.'),
    limit: Annotated[int, typer.Option('--limit')] = 20,
):
    vault = Vault(_root(path))
    table = Table(title='Semantic Revisions')
    table.add_column('Revision')
    table.add_column('Created')
    table.add_column('Cases')
    table.add_column('Message')
    for item in vault.log(limit=limit):
        table.add_row(item.revision_id, item.created_at, ', '.join(item.cases), item.message)
    console.print(table)


@app.command()
def verify(path: Annotated[Path, typer.Argument()] = Path('.')):
    vault = Vault(_root(path))
    problems = vault.verify()
    if problems:
        for problem in problems:
            console.print(f'[red]✗[/red] {problem}')
        raise typer.Exit(1)
    console.print('[green]✓ Vault derived artifacts and manifests verified.[/green]')


@app.command(hidden=True)
def worker(
    host: Annotated[str, typer.Option()] = '0.0.0.0',
    port: Annotated[int, typer.Option()] = 8080,
):
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError('Worker service requires `pip install -e .[cloud]`') from exc
    uvicorn.run('aethelgard.server:app', host=host, port=port)


def main() -> None:
    app()
