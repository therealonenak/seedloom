"""Insert generated rows into Postgres, returning the primary key values
that got assigned so downstream tables can reference them as valid FKs."""
from __future__ import annotations

from typing import Any

import psycopg2
import psycopg2.extras

from .models import Table


def insert_rows(conn, table: Table, rows: list[dict[str, Any]]) -> list[Any]:
    """Insert rows for one table. Returns list of primary key values inserted.

    Assumes a single-column primary key (v1 limitation — composite PKs on
    join tables are inserted fine, just not returned as an FK pool source).
    """
    if not rows or not rows[0]:
        return []

    columns = list(rows[0].keys())
    pk_cols = table.primary_key_columns
    returning_clause = ""
    if len(pk_cols) == 1 and pk_cols[0] not in columns:
        returning_clause = f' RETURNING "{pk_cols[0]}"'

    col_list = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(f"%({c})s" for c in columns)
    query = f'INSERT INTO "{table.name}" ({col_list}) VALUES ({placeholders}){returning_clause}'

    returned_pks: list[Any] = []
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(query, row)
            if returning_clause:
                returned_pks.append(cur.fetchone()[0])
    conn.commit()

    if not returning_clause and len(pk_cols) == 1 and pk_cols[0] in columns:
        returned_pks = [row[pk_cols[0]] for row in rows]

    return returned_pks
