from __future__ import annotations

import json
import sys
from pathlib import Path

import anthropic
import click
import psycopg2
from rich.console import Console
from rich.table import Table as RichTable

from .config import Config
from .generator import generate_rows
from .graph import CyclicDependencyError, resolve_seed_order
from .inserter import insert_rows
from .introspect import introspect
from .models import Schema

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
        config = Config.load()
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
def run(rows: int, tables: str | None, dry_run: bool) -> None:
    """Generate and insert seed data, respecting foreign key order."""
    try:
        config = Config.load()
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

    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    conn = None if dry_run else psycopg2.connect(config.database_url)

    fk_pools: dict[str, dict[str, list]] = {}  # table -> column -> values

    try:
        for table_name in order:
            table = schema.tables[table_name]
            console.print(f"[cyan]Generating {rows} rows for '{table_name}'...[/cyan]")

            fk_value_pool: dict[str, list] = {}
            for fk in table.foreign_keys:
                parent_pool = fk_pools.get(fk.ref_table, {}).get(fk.ref_column, [])
                if parent_pool:
                    fk_value_pool[fk.column] = parent_pool

            generated = generate_rows(client, config.model, table, rows, fk_value_pool)

            if dry_run:
                console.print(generated)
                continue

            pk_values = insert_rows(conn, table, generated)
            pk_cols = table.primary_key_columns
            if len(pk_cols) == 1 and pk_values:
                fk_pools.setdefault(table_name, {})[pk_cols[0]] = pk_values

            console.print(f"[green]Inserted {len(generated)} rows into '{table_name}'.[/green]")
    finally:
        if conn:
            conn.close()

    console.print("[bold green]Done.[/bold green]")


if __name__ == "__main__":
    main()
