from __future__ import annotations

import json
import sys

import click
import psycopg2
from rich.console import Console
from rich.table import Table as RichTable

from .config import Config
from .graph import CyclicDependencyError
from .introspect import introspect
from .pipeline import SCHEMA_CACHE, seed_database
from .providers import ProviderError, SUPPORTED_PROVIDERS

console = Console()


@click.group()
def main() -> None:
    """seedloom — AI-powered database seeding.

    Introspects your Postgres schema and uses Claude to generate realistic,
    referentially-valid seed data.
    """


@main.command()
def init() -> None:
    """Connect to the database, introspect the schema, and cache it locally."""
    try:
        config = Config.load(require_provider=False)
    except EnvironmentError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    console.print("[cyan]Connecting and introspecting schema...[/cyan]")
    try:
        schema = introspect(config.database_url)
    except psycopg2.OperationalError as e:
        console.print(f"[red]Could not connect to database: {e}[/red]")
        sys.exit(1)

    if not schema.tables:
        console.print("[yellow]No tables found in the 'public' schema.[/yellow]")
        sys.exit(0)

    SCHEMA_CACHE.write_text(json.dumps(schema.to_dict(), indent=2))

    t = RichTable(title="Discovered schema")
    t.add_column("Table")
    t.add_column("Columns")
    t.add_column("Foreign Keys")
    for table in schema.tables.values():
        fks = ", ".join(f"{fk.column}->{fk.ref_table}.{fk.ref_column}" for fk in table.foreign_keys)
        t.add_row(table.name, str(len(table.columns)), fks or "-")
    console.print(t)
    console.print(f"[green]Schema cached to {SCHEMA_CACHE}[/green]. Run 'seedloom run' next.")


@main.command()
@click.option("--rows", default=10, show_default=True, help="Rows to generate per table.")
@click.option("--tables", default=None, help="Comma-separated subset of tables to seed (default: all).")
@click.option("--dry-run", is_flag=True, help="Generate data and print it without inserting.")
@click.option(
    "--provider",
    default=None,
    help=f"Override provider from config. Supported: {', '.join(SUPPORTED_PROVIDERS)}.",
)
@click.option("--model", default=None, help="Override model from config.")
@click.option("--base-url", default=None, help="Override base URL (openai_compatible or self-hosted endpoints).")
@click.option("--host", default=None, help="Override Ollama host (default: http://localhost:11434).")
def run(
    rows: int,
    tables: str | None,
    dry_run: bool,
    provider: str | None,
    model: str | None,
    base_url: str | None,
    host: str | None,
) -> None:
    """Generate and insert seed data, respecting foreign key order."""
    if not SCHEMA_CACHE.exists():
        console.print("[red]No cached schema found. Run 'seedloom init' first.[/red]")
        sys.exit(1)

    def report(message: str) -> None:
        console.print(f"[cyan]{message}[/cyan]")

    try:
        result = seed_database(
            rows=rows,
            tables=tables,
            provider=provider,
            model=model,
            base_url=base_url,
            host=host,
            dry_run=dry_run,
            on_progress=report,
        )
    except EnvironmentError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    except ProviderError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    except CyclicDependencyError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    except psycopg2.OperationalError as e:
        console.print(f"[red]Could not connect to database: {e}[/red]")
        sys.exit(1)

    console.print(f"[cyan]Using provider: {result.provider}[/cyan]")
    for t in result.tables:
        if t.status == "dry_run":
            console.print(t.rows)
        elif t.status == "inserted":
            console.print(f"[green]Inserted {t.rows_inserted} rows into '{t.table}'.[/green]")
        # "skipped" is already reported live via on_progress

    console.print("[bold green]Done.[/bold green]")


if __name__ == "__main__":
    main()