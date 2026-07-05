"""Introspect a live PostgreSQL database into our Schema model.

Uses information_schema + pg_catalog rather than ORM-specific metadata so it
works against any Postgres DB regardless of what created it (Prisma, Django,
raw SQL migrations, etc).
"""
from __future__ import annotations

import psycopg2
import psycopg2.extras

from .models import Column, ForeignKey, Schema, Table

_EXCLUDED_SCHEMAS = ("pg_catalog", "information_schema")

_EXCLUDED_TABLE_NAMES = {
    "sequelizemeta",
    "sequelize_meta",
    "knex_migrations",
    "knex_migrations_lock",
    "typeorm_metadata",
    "migrations",
    "schema_migrations",
    "django_migrations",
    "alembic_version",
    "flyway_schema_history",
    "prisma_migrations",
    "ar_internal_metadata",
    "schema_info",
    "__efmigrationshistory",
    "__efmigrationshistory2",
    "__diesel_schema_migrations",
}


def introspect(database_url: str, schema_name: str = "public") -> Schema:
    conn = psycopg2.connect(database_url)
    try:
        conn.autocommit = True
        schema = Schema()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            table_names = _fetch_table_names(cur, schema_name)
            for table_name in table_names:
                table = Table(name=table_name)
                pk_cols = _fetch_primary_key_columns(cur, schema_name, table_name)
                unique_cols = _fetch_unique_columns(cur, schema_name, table_name)
                table.columns = _fetch_columns(cur, schema_name, table_name, pk_cols, unique_cols)
                table.foreign_keys = _fetch_foreign_keys(cur, schema_name, table_name)
                schema.add_table(table)
        return schema
    finally:
        conn.close()


def _fetch_table_names(cur, schema_name: str) -> list[str]:
    cur.execute(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = %s AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
        (schema_name,),
    )
    return [
        row["table_name"]
        for row in cur.fetchall()
        if row["table_name"].lower() not in _EXCLUDED_TABLE_NAMES
    ]


def _fetch_primary_key_columns(cur, schema_name: str, table_name: str) -> set[str]:
    cur.execute(
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = %s AND tc.table_name = %s
        """,
        (schema_name, table_name),
    )
    return {row["column_name"] for row in cur.fetchall()}


def _fetch_unique_columns(cur, schema_name: str, table_name: str) -> set[str]:
    cur.execute(
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'UNIQUE'
          AND tc.table_schema = %s AND tc.table_name = %s
        """,
        (schema_name, table_name),
    )
    return {row["column_name"] for row in cur.fetchall()}


def _fetch_columns(
    cur, schema_name: str, table_name: str, pk_cols: set[str], unique_cols: set[str]
) -> list[Column]:
    cur.execute(
        """
        SELECT column_name, data_type, udt_name, is_nullable, column_default,
               character_maximum_length, numeric_precision
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema_name, table_name),
    )
    columns = []
    for row in cur.fetchall():
        enum_values = None
        if row["data_type"] == "USER-DEFINED":
            enum_values = _fetch_enum_values(cur, row["udt_name"])
        columns.append(
            Column(
                name=row["column_name"],
                data_type=row["udt_name"] if enum_values else row["data_type"],
                is_nullable=row["is_nullable"] == "YES",
                is_primary_key=row["column_name"] in pk_cols,
                is_unique=row["column_name"] in unique_cols,
                default=row["column_default"],
                char_max_length=row["character_maximum_length"],
                numeric_precision=row["numeric_precision"],
                enum_values=enum_values,
            )
        )
    return columns


def _fetch_enum_values(cur, type_name: str) -> list[str] | None:
    cur.execute(
        """
        SELECT e.enumlabel
        FROM pg_type t
        JOIN pg_enum e ON t.oid = e.enumtypid
        WHERE t.typname = %s
        ORDER BY e.enumsortorder
        """,
        (type_name,),
    )
    values = [row["enumlabel"] for row in cur.fetchall()]
    return values or None


def _fetch_foreign_keys(cur, schema_name: str, table_name: str) -> list[ForeignKey]:
    cur.execute(
        """
        SELECT kcu.column_name, ccu.table_name AS ref_table, ccu.column_name AS ref_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = %s AND tc.table_name = %s
        """,
        (schema_name, table_name),
    )
    return [
        ForeignKey(column=row["column_name"], ref_table=row["ref_table"], ref_column=row["ref_column"])
        for row in cur.fetchall()
    ]