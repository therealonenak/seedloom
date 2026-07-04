"""Generate realistic seed rows for a table using Claude.

Key design choice: referential integrity is enforced *structurally*, not by
hoping the model behaves. Foreign-key columns are generated as a JSON Schema
`enum` of the actual parent-row key values already inserted — Claude picks
from real values, it can't invent a dangling reference.
"""
from __future__ import annotations

import json
from typing import Any

import anthropic

from .models import Column, Table

_PG_TYPE_TO_JSON_SCHEMA: dict[str, dict[str, Any]] = {
    "integer": {"type": "integer"},
    "bigint": {"type": "integer"},
    "smallint": {"type": "integer"},
    "numeric": {"type": "number"},
    "real": {"type": "number"},
    "double precision": {"type": "number"},
    "boolean": {"type": "boolean"},
    "text": {"type": "string"},
    "character varying": {"type": "string"},
    "character": {"type": "string"},
    "uuid": {"type": "string"},
    "date": {"type": "string", "description": "ISO 8601 date, e.g. 2024-03-15"},
    "timestamp without time zone": {"type": "string", "description": "ISO 8601 datetime"},
    "timestamp with time zone": {"type": "string", "description": "ISO 8601 datetime with offset"},
    "json": {"type": "object"},
    "jsonb": {"type": "object"},
}


def _column_schema(col: Column) -> dict[str, Any]:
    if col.enum_values:
        return {"type": "string", "enum": col.enum_values}
    base = _PG_TYPE_TO_JSON_SCHEMA.get(col.data_type, {"type": "string"})
    schema = dict(base)
    if col.char_max_length and schema.get("type") == "string":
        schema["maxLength"] = col.char_max_length
    return schema


def build_row_schema(
    table: Table, fk_value_pool: dict[str, list[Any]]
) -> tuple[dict[str, Any], list[str]]:
    """Returns (json_schema_for_one_row, list_of_generatable_column_names).

    fk_value_pool maps column_name -> already-inserted parent key values,
    for columns that are foreign keys. Columns with an empty pool (parent
    table not seeded yet / no rows) are skipped — caller should seed in
    dependency order so this shouldn't happen for non-nullable FKs.
    """
    properties: dict[str, Any] = {}
    generatable: list[str] = []
    fk_columns = {fk.column for fk in table.foreign_keys}

    for col in table.columns:
        if col.is_auto_generated:
            continue  # serial/identity/default(now())/etc — DB fills this in
        if col.name in fk_columns:
            pool = fk_value_pool.get(col.name) or []
            if not pool:
                continue  # can't reference rows that don't exist; leave to DB default/NULL
            properties[col.name] = {"enum": pool}
        else:
            properties[col.name] = _column_schema(col)
        generatable.append(col.name)

    required = [
        c for c in generatable
        if not (table.column(c) and table.column(c).is_nullable)
    ]
    schema = {"type": "object", "properties": properties, "required": required}
    return schema, generatable


def generate_rows(
    client: anthropic.Anthropic,
    model: str,
    table: Table,
    count: int,
    fk_value_pool: dict[str, list[Any]],
    context_hint: str = "",
) -> list[dict[str, Any]]:
    row_schema, columns = build_row_schema(table, fk_value_pool)
    if not columns:
        return [{}]  # table has nothing generatable (e.g. pure auto-increment join row)

    tool_schema = {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": row_schema,
            }
        },
        "required": ["rows"],
    }

    system = (
        "You generate realistic, internally-consistent fake data for database seeding. "
        "Values should look like real-world data (plausible names, emails matching names, "
        "believable dates/amounts), not placeholder text like 'test1'. "
        "Never reuse the exact same value twice within the batch unless the column is clearly "
        "meant to repeat (e.g. a status field)."
    )
    user_prompt = (
        f"Generate {count} realistic rows for the table `{table.name}`.\n"
        f"{context_hint}\n"
        "Call the generate_rows tool with the data."
    )

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[
            {
                "name": "generate_rows",
                "description": "Submit the generated seed rows for this table.",
                "input_schema": tool_schema,
            }
        ],
        tool_choice={"type": "tool", "name": "generate_rows"},
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "generate_rows":
            return block.input.get("rows", [])

    raise RuntimeError(f"Model did not return a tool_use block for table {table.name}")
