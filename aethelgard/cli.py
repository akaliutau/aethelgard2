from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from .adapters.executors import HTTPRemoteExecutor, LocalExecutor
from .config import EmbeddingsConfig, ExtractorConfig, SourceConfig, VaultConfig
from .factory import build_pipeline, build_search_service
from .search import encode_protected_query
from .vault import Vault

app = typer.Typer(no_args_is_help=True, help='Aethelgard: semantic Git for medical documents.')
console = Console()


def _root(path: Path) -> Path:
    return path.expanduser().resolve()


def _open(path: Path) -> tuple[Vault, object]:
    vault = Vault(_root(path))
    pipeline = build_pipeline(vault.root, vault.config)
    return vault, pipeline


def _image_bytes(image: Path | None) -> bytes | None:
    return image.expanduser().read_bytes() if image else None


def _hits_json(hits) -> list[dict]:
    return [
        {
            'case_id': hit.case_id,
            'revision_id': hit.revision_id,
            'score': hit.score,
            'component_scores': dict(hit.component_scores),
            'evidence': list(hit.evidence),
        }
        for hit in hits
    ]


def _print_hits(title: str, hits) -> None:
    table = Table(title=title)
    table.add_column('Rank', justify='right')
    table.add_column('Case')
    table.add_column('Score', justify='right')
    table.add_column('Clinical', justify='right')
    table.add_column('Image', justify='right')
    for rank, hit in enumerate(hits, 1):
        table.add_row(
            str(rank),
            hit.case_id,
            f'{hit.score:.4f}',
            f'{hit.component_scores.get("clinical_text", 0.0):.4f}'
            if 'clinical_text' in hit.component_scores else '—',
            f'{hit.component_scores.get("medical_image", 0.0):.4f}'
            if 'medical_image' in hit.component_scores else '—',
        )
    console.print(table)
    for hit in hits:
        if hit.evidence:
            console.print(f'[bold]{hit.case_id} relevant evidence[/bold]')
            for fact in hit.evidence:
                console.print(f'  • {fact}')


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



@app.command(name='search')
def search_cmd(
    query: Annotated[str, typer.Argument(help='Clinical evidence query')],
    path: Annotated[Path, typer.Option('--path', '-p')] = Path('.'),
    image: Annotated[Optional[Path], typer.Option('--image', help='Optional query JPG/PNG')] = None,
    top_k: Annotated[Optional[int], typer.Option('--top-k')] = None,
    summary_facts: Annotated[Optional[int], typer.Option('--summary-facts')] = None,
    protected: Annotated[bool, typer.Option('--protected', help='Search using a perturbed vector, simulating an external peer')] = False,
    compare_protection: Annotated[bool, typer.Option('--compare-protection', help='Compare clean and protected ranking')] = False,
    seed: Annotated[Optional[int], typer.Option('--seed', help='Reproducible protection experiment seed')] = None,
    as_json: Annotated[bool, typer.Option('--json', help='Emit machine-readable JSON')] = False,
):
    vault = Vault(_root(path))
    service = build_search_service(vault)
    image_data = _image_bytes(image)

    if compare_protection:
        comparison = service.compare_protection(
            query,
            image_data,
            top_k=top_k,
            summary_facts=summary_facts,
            seed=seed,
        )
        if as_json:
            console.print_json(data={
                'clean': _hits_json(comparison.clean),
                'protected': _hits_json(comparison.protected),
                'protection': {
                    'algorithm': comparison.protection.algorithm,
                    'parameters': dict(comparison.protection.parameters),
                    'component_cosine': dict(comparison.protection.component_cosine),
                },
                'protected_vector_bytes': comparison.protected_vector_bytes,
                'protected_wire_bytes': comparison.protected_wire_bytes,
                'raw_query_text_bytes': len(query.encode()),
                'raw_query_image_bytes': len(image_data or b''),
                'raw_query_text_in_envelope': False,
                'raw_query_image_in_envelope': False,
                'top1_preserved': comparison.top1_preserved,
                'top_k_overlap': comparison.top_k_overlap,
            })
            return
        _print_hits('Clean query', comparison.clean)
        _print_hits('Protected query', comparison.protected)
        console.print(
            f'Top-1 preserved: [bold]{comparison.top1_preserved}[/bold]  '
            f'Top-k overlap: [bold]{comparison.top_k_overlap:.1%}[/bold]'
        )
        console.print(
            f'Protected vectors: [bold]{comparison.protected_vector_bytes} B[/bold]  '
            f'wire envelope: [bold]{comparison.protected_wire_bytes} B[/bold]  '
            f'raw text/image included: [bold]no/no[/bold]'
        )
        for component, cosine in comparison.protection.component_cosine.items():
            console.print(f'{component} clean/protected cosine: {cosine:.4f}')
        return

    vectors = service.encode(query, image_data)
    protection_report = None
    if protected:
        vectors, protection_report = service.protector.protect(vectors, seed=seed)
    hits = service.search_vectors(vectors, top_k=top_k, summary_facts=summary_facts)

    if as_json:
        payload = {'hits': _hits_json(hits)}
        if protection_report:
            payload['protection'] = {
                'algorithm': protection_report.algorithm,
                'parameters': dict(protection_report.parameters),
                'component_cosine': dict(protection_report.component_cosine),
            }
        console.print_json(data=payload)
        return
    _print_hits('Aethelgard Search' + (' — protected vector' if protected else ''), hits)


@app.command()
def protect(
    query: Annotated[str, typer.Argument(help='Clinical evidence query')],
    path: Annotated[Path, typer.Option('--path', '-p')] = Path('.'),
    image: Annotated[Optional[Path], typer.Option('--image', help='Optional query JPG/PNG')] = None,
    output: Annotated[Optional[Path], typer.Option('--output', '-o', help='Write future transport envelope JSON')] = None,
    seed: Annotated[Optional[int], typer.Option('--seed', help='Reproducible experiment seed')] = None,
):
    vault = Vault(_root(path))
    service = build_search_service(vault)
    image_data = _image_bytes(image)
    clean = service.encode(query, image_data)
    protected_vectors, report = service.protector.protect(clean, seed=seed)
    envelope, wire = encode_protected_query(protected_vectors, report)

    raw_text_bytes = len(query.encode())
    raw_image_bytes = len(image_data or b'')
    binary_vector_bytes = sum(
        int(component['dimensions']) * 2
        for component in envelope['components'].values()
    )

    table = Table(title='Protected Query')
    table.add_column('Property')
    table.add_column('Value')
    table.add_row('Profile', envelope['profile'])
    table.add_row('Components', ', '.join(
        f'{name}={value["dimensions"]}d'
        for name, value in envelope['components'].items()
    ))
    table.add_row('Algorithm', report.algorithm)
    table.add_row('Protected vector bytes', str(binary_vector_bytes))
    table.add_row('Serialized envelope bytes', str(len(wire)))
    table.add_row('Raw query text bytes', str(raw_text_bytes))
    table.add_row('Raw query image bytes', str(raw_image_bytes))
    table.add_row('Raw query text included', 'no')
    table.add_row('Raw query image included', 'no')
    console.print(table)
    for component, cosine in report.component_cosine.items():
        console.print(f'{component} clean/protected cosine: {cosine:.4f}')

    if output:
        target = output.expanduser()
        target.write_text(json.dumps(envelope, indent=2, sort_keys=True))
        console.print(f'[green]Wrote[/green] {target}')


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
