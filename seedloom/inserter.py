"""Insert generated rows into Postgres, returning values for whichever
columns other tables' foreign keys point at, so downstream tables always
have a real, valid pool to pick from - not just the primary key."""
from __future__ import annotations

from typing import Any

import psycopg2
import psycopg2.extras
from rich.console import Console

from .models import Table

console = Console()


def _adapt_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return psycopg2.extras.Json(value)
    return value


def table_row_count(conn, table_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        return cur.fetchone()[0]


def existing_column_values(conn, table_name: str, columns: list[str]) -> dict[str, list[Any]]:
    """Fetch current values for the given columns (e.g. columns other tables'
    foreign keys reference - which may or may not be the primary key)."""
    if not columns:
        return {}
    col_list = ", ".join(f'"{c}"' for c in columns)
    result: dict[str, list[Any]] = {c: [] for c in columns}
    with conn.cursor() as cur:
        cur.execute(f'SELECT {col_list} FROM "{table_name}"')
        for record in cur.fetchall():
            for i, c in enumerate(columns):
                result[c].append(record[i])
    return result


def insert_rows(
    conn, table: Table, rows: list[dict[str, Any]], needed_columns: list[str] | None = None
) -> dict[str, list[Any]]:
    """Insert rows for one table. Returns {column_name: [values]} for each
    column in `needed_columns` (typically every column some other table's
    foreign key references), covering both auto-generated and model-supplied
    values.

    Rows that collide with an existing unique/primary key are skipped (logged,
    not treated as an error) rather than aborting the run.
    """
    if not rows or not rows[0]:
        return {}

    needed_columns = needed_columns or []
    columns = sorted({c for row in rows for c in row.keys()})
    returning_clause = ""
    if needed_columns:
        returning_clause = " RETURNING " + ", ".join(f'"{c}"' for c in needed_columns)

    col_list = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(f"%({c})s" for c in columns)
    query = (
        f'INSERT INTO "{table.name}" ({col_list}) VALUES ({placeholders}) '
        f'ON CONFLICT DO NOTHING{returning_clause}'
    )

    collected: dict[str, list[Any]] = {c: [] for c in needed_columns}
    skipped = 0
    with conn.cursor() as cur:
        for row in rows:
            adapted_row = {c: _adapt_value(row.get(c)) for c in columns}
            cur.execute(query, adapted_row)
            if returning_clause:
                result = cur.fetchone()
                if result is not None:
                    for i, c in enumerate(needed_columns):
                        collected[c].append(result[i])
                else:
                    skipped += 1
            elif cur.rowcount == 0:
                skipped += 1
    conn.commit()

    if skipped:
        console.print(
            f"[yellow]  {skipped} row(s) already existed in '{table.name}', skipped.[/yellow]"
        )

    return collected