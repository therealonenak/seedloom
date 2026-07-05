from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import psycopg2
from rich.console import Console
from rich.table import Table as RichTable

from .config import Config
from .generator import generate_rows
from .graph import CyclicDependencyError, resolve_seed_order
from .inserter import existing_column_values, insert_rows, table_row_count
from .introspect import introspect
from .models import Schema
from .providers import ProviderError, SUPPORTED_PROVIDERS, get_provider

console = Console()
SCHEMA_CACHE = Path(".seedloom_schema.json")


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
    try:
        config = Config.load(provider_override=provider or "")
    except EnvironmentError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    if not SCHEMA_CACHE.exists():
        console.print("[red]No cached schema found. Run 'seedloom init' first.[/red]")
        sys.exit(1)

    schema = Schema.from_dict(json.loads(SCHEMA_CACHE.read_text()))

    try:
        order = resolve_seed_order(schema)
    except CyclicDependencyError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    if tables:
        wanted = set(t.strip() for t in tables.split(","))
        order = [t for t in order if t in wanted]

    try:
        active_provider = get_provider(
            config.provider,
            api_key=config.api_key,
            model=model or config.model,
            base_url=base_url or config.base_url,
            host=host or config.host,
        )
    except ProviderError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    console.print(f"[cyan]Using provider: {config.provider}[/cyan]")
    conn = None if dry_run else psycopg2.connect(config.database_url)

    fk_pools: dict[str, dict[str, list]] = {}  # table -> column -> values

    referenced_columns: dict[str, set[str]] = {}
    for t in schema.tables.values():
        for fk in t.foreign_keys:
            referenced_columns.setdefault(fk.ref_table, set()).add(fk.ref_column)

    try:
        for table_name in order:
            table = schema.tables[table_name]
            needed_columns = sorted(referenced_columns.get(table_name, set()))

            to_generate = rows
            if conn is not None:
                existing_count = table_row_count(conn, table_name)
                if existing_count > 0 and needed_columns:
                    existing_values = existing_column_values(conn, table_name, needed_columns)
                    for col, vals in existing_values.items():
                        if vals:
                            fk_pools.setdefault(table_name, {})[col] = vals

                if existing_count >= rows:
                    console.print(
                        f"[yellow]Skipping '{table_name}' — already has {existing_count} row(s) "
                        f"(>= {rows} requested).[/yellow]"
                    )
                    continue

                to_generate = rows - existing_count
                if existing_count > 0:
                    console.print(
                        f"[cyan]'{table_name}' has {existing_count} row(s); generating "
                        f"{to_generate} more to reach {rows}...[/cyan]"
                    )
                else:
                    console.print(f"[cyan]Generating {to_generate} rows for '{table_name}'...[/cyan]")
            else:
                console.print(f"[cyan]Generating {to_generate} rows for '{table_name}'...[/cyan]")

            fk_value_pool: dict[str, list] = {}
            for fk in table.foreign_keys:
                parent_pool = fk_pools.get(fk.ref_table, {}).get(fk.ref_column, [])
                if parent_pool:
                    fk_value_pool[fk.column] = parent_pool

            try:
                generated = generate_rows(active_provider, table, to_generate, fk_value_pool)
            except ProviderError as e:
                console.print(f"[red]{e}[/red]")
                sys.exit(1)

            if dry_run:
                console.print(generated)
                continue

            inserted_values = insert_rows(conn, table, generated, needed_columns)
            for col, vals in inserted_values.items():
                if vals:
                    fk_pools.setdefault(table_name, {}).setdefault(col, [])
                    fk_pools[table_name][col].extend(vals)

            console.print(f"[green]Inserted {len(generated)} rows into '{table_name}'.[/green]")
    finally:
        if conn:
            conn.close()

    console.print("[bold green]Done.[/bold green]")


if __name__ == "__main__":
    main()