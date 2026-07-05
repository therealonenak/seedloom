"""Core seeding pipeline: introspect -> order -> generate -> insert.

Kept free of any console/print concerns (no Rich, no click) so the exact
same code path can run headless from an MCP tool call as easily as from the
terminal - callers get back structured results and decide how to present
them. `cli.py` and `mcp_server.py` both call `seed_database()`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import psycopg2

from .config import Config
from .generator import generate_rows
from .graph import CyclicDependencyError, resolve_seed_order
from .inserter import existing_column_values, insert_rows, table_row_count
from .introspect import introspect
from .models import Schema
from .providers import ProviderError, get_provider

SCHEMA_CACHE = Path(".seedloom_schema.json")

ProgressFn = Callable[[str], None]


@dataclass
class TableResult:
    table: str
    status: str  # "inserted", "skipped", "dry_run"
    rows_generated: int = 0
    rows_inserted: int = 0
    existing_rows: int = 0
    detail: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SeedRunResult:
    provider: str
    tables: list[TableResult] = field(default_factory=list)

    @property
    def total_inserted(self) -> int:
        return sum(t.rows_inserted for t in self.tables)


def load_or_build_schema(database_url: str, use_cache: bool = True) -> Schema:
    """Load the cached schema if present, otherwise introspect and cache it."""
    if use_cache and SCHEMA_CACHE.exists():
        return Schema.from_dict(json.loads(SCHEMA_CACHE.read_text()))
    schema = introspect(database_url)
    SCHEMA_CACHE.write_text(json.dumps(schema.to_dict(), indent=2))
    return schema


def seed_database(
    *,
    database_url: str | None = None,
    rows: int = 10,
    tables: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    host: str | None = None,
    dry_run: bool = False,
    use_cached_schema: bool = True,
    on_progress: ProgressFn | None = None,
) -> SeedRunResult:
    """Run the full pipeline once and return structured, per-table results.

    `database_url`/`provider`/`model`/`base_url`/`host` are optional
    overrides - anything left as None falls back to Config.load()'s usual
    env-var resolution (DATABASE_URL, SEEDLOOM_PROVIDER, SEEDLOOM_MODEL,
    SEEDLOOM_BASE_URL, SEEDLOOM_HOST). Provider API keys are always read
    from the environment by Config.load() - never accepted as a parameter
    here - so a secret never has to pass through a caller like an MCP tool
    argument.

    Raises EnvironmentError (missing config), ProviderError, or
    CyclicDependencyError on failure - callers decide how to present those.
    """
    config = Config.load(provider_override=provider or "")
    db_url = database_url or config.database_url
    if not db_url:
        raise EnvironmentError(
            "No DATABASE_URL provided (pass database_url or set the DATABASE_URL env var)."
        )

    active_provider = get_provider(
        config.provider,
        api_key=config.api_key,
        model=model or config.model,
        base_url=base_url or config.base_url,
        host=host or config.host,
    )

    schema = load_or_build_schema(db_url, use_cache=use_cached_schema)
    if not schema.tables:
        return SeedRunResult(provider=config.provider, tables=[])

    order = resolve_seed_order(schema)  # may raise CyclicDependencyError

    if tables:
        wanted = {t.strip() for t in tables.split(",")}
        order = [t for t in order if t in wanted]

    conn = None if dry_run else psycopg2.connect(db_url)
    result = SeedRunResult(provider=config.provider)

    fk_pools: dict[str, dict[str, list]] = {}
    referenced_columns: dict[str, set[str]] = {}
    for t in schema.tables.values():
        for fk in t.foreign_keys:
            referenced_columns.setdefault(fk.ref_table, set()).add(fk.ref_column)

    try:
        for table_name in order:
            table = schema.tables[table_name]
            needed_columns = sorted(referenced_columns.get(table_name, set()))

            to_generate = rows
            existing_count = 0
            if conn is not None:
                existing_count = table_row_count(conn, table_name)
                if existing_count > 0 and needed_columns:
                    existing_values = existing_column_values(conn, table_name, needed_columns)
                    for col, vals in existing_values.items():
                        if vals:
                            fk_pools.setdefault(table_name, {})[col] = vals

                if existing_count >= rows:
                    if on_progress:
                        on_progress(
                            f"Skipping '{table_name}' — already has {existing_count} "
                            f"row(s) (>= {rows} requested)."
                        )
                    result.tables.append(
                        TableResult(
                            table=table_name,
                            status="skipped",
                            existing_rows=existing_count,
                            detail=f"already has {existing_count} row(s) (>= {rows} requested)",
                        )
                    )
                    continue

                to_generate = rows - existing_count

            if on_progress:
                on_progress(f"Generating {to_generate} rows for '{table_name}'...")

            fk_value_pool: dict[str, list] = {}
            for fk in table.foreign_keys:
                parent_pool = fk_pools.get(fk.ref_table, {}).get(fk.ref_column, [])
                if parent_pool:
                    fk_value_pool[fk.column] = parent_pool

            generated = generate_rows(active_provider, table, to_generate, fk_value_pool)

            if dry_run:
                result.tables.append(
                    TableResult(
                        table=table_name,
                        status="dry_run",
                        rows_generated=len(generated),
                        existing_rows=existing_count,
                        rows=generated,
                    )
                )
                continue

            inserted_values = insert_rows(conn, table, generated, needed_columns)
            for col, vals in inserted_values.items():
                if vals:
                    fk_pools.setdefault(table_name, {}).setdefault(col, [])
                    fk_pools[table_name][col].extend(vals)

            if on_progress:
                on_progress(f"Inserted {len(generated)} rows into '{table_name}'.")

            result.tables.append(
                TableResult(
                    table=table_name,
                    status="inserted",
                    rows_generated=len(generated),
                    rows_inserted=len(generated),
                    existing_rows=existing_count,
                )
            )
    finally:
        if conn:
            conn.close()

    return result