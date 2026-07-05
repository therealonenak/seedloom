"""Generate realistic seed rows for a table using a pluggable LLM provider.

Key design choice: referential integrity is enforced *structurally*, not by
hoping the model behaves. Foreign-key columns are generated as a JSON Schema
`enum` of the actual parent-row key values already inserted - the model picks
from real values, it can't invent a dangling reference.
"""
from __future__ import annotations

import random
import uuid
from typing import Any

from .models import Column, Table
from .providers import Provider

_MEDIA_KEYWORDS = (
    "avatar",
    "photo",
    "image",
    "picture",
    "logo",
    "banner",
    "thumbnail",
    "cover",
    "icon",
)


def _is_media_url_column(col: Column) -> bool:
    if col.data_type not in ("text", "character varying", "character"):
        return False
    name = col.name.lower()
    return any(k in name for k in _MEDIA_KEYWORDS)


def _random_media_url(col: Column) -> str:
    name = col.name.lower()
    seed = uuid.uuid4().hex[:12]
    if "avatar" in name or "headshot" in name or "profile" in name:
        return f"https://i.pravatar.cc/300?u={seed}"
    if "logo" in name or "icon" in name:
        return f"https://picsum.photos/seed/{seed}/200/200"
    if "banner" in name or "cover" in name:
        return f"https://picsum.photos/seed/{seed}/1200/400"
    return f"https://picsum.photos/seed/{seed}/600/400"


_VIDEO_KEYWORDS = (
    "video",
    "mp4",
    "clip",
    "trailer",
    "movie",
    "recording",
    "footage",
)

_SAMPLE_VIDEO_URLS = (
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerFun.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyrides.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerMeltdowns.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/Sintel.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/SubaruOutbackOnStreetAndDirt.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/TearsOfSteel.mp4",
)


def _is_video_url_column(col: Column) -> bool:
    if col.data_type not in ("text", "character varying", "character"):
        return False
    name = col.name.lower()
    return any(k in name for k in _VIDEO_KEYWORDS)


def _random_video_url() -> str:
    return random.choice(_SAMPLE_VIDEO_URLS)


_DEFAULT_VECTOR_DIM = 256


def _is_vector_column(col: Column) -> bool:
    return col.data_type in ("vector", "halfvec", "sparsevec")


def _random_vector_literal(dim: int | None) -> str:
    """A random unit-length vector in pgvector's text input format, e.g. '[0.12,-0.4,...]'.

    Real embeddings aren't uniformly random, but a normalized random vector is a
    reasonable stand-in for exercising vector columns/indexes/similarity queries
    in seed data - asking an LLM to hand-write hundreds of floats would be slow,
    expensive, and no more meaningful. Columns declared without a fixed dimension
    (plain `vector` rather than `vector(384)`) fall back to a default width.
    """
    dim = dim or _DEFAULT_VECTOR_DIM
    raw = [random.gauss(0, 1) for _ in range(dim)]
    norm = sum(v * v for v in raw) ** 0.5 or 1.0
    values = [v / norm for v in raw]
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"

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
    table not seeded yet / no rows) are skipped - caller should seed in
    dependency order so this shouldn't happen for non-nullable FKs.
    """
    properties: dict[str, Any] = {}
    generatable: list[str] = []
    fk_columns = {fk.column for fk in table.foreign_keys}

    for col in table.columns:
        if col.is_auto_generated:
            continue
        if _is_vector_column(col):
            continue
        if col.name in fk_columns:
            pool = [v for v in (fk_value_pool.get(col.name) or []) if v not in (None, "")]
            if not pool:
                continue
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


_NULL_LITERALS = {"null", "none", "n/a", "na", ""}


def _sanitize_row(
    table: Table, row: dict[str, Any], fk_value_pool: dict[str, list[Any]]
) -> dict[str, Any]:
    fk_columns = {fk.column for fk in table.foreign_keys}
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        col = table.column(key)
        if (
            isinstance(value, str)
            and value.strip().lower() in _NULL_LITERALS
            and col
            and col.is_nullable
        ):
            cleaned[key] = None
            continue
        if key in fk_columns:
            pool = fk_value_pool.get(key) or []
            if pool and value not in pool:
                match = next((item for item in pool if str(item) == str(value)), None)
                if match is not None:
                    value = match
                elif isinstance(value, int) and 1 <= value <= len(pool):
                    value = pool[value - 1]
                elif isinstance(value, int) and 0 <= value < len(pool):
                    value = pool[value]
                else:
                    value = random.choice(pool)
        elif (
            isinstance(value, str)
            and col
            and col.char_max_length
            and len(value) > col.char_max_length
        ):
            value = value[: col.char_max_length]
        cleaned[key] = value
    return cleaned


def generate_rows(
    provider: Provider,
    table: Table,
    count: int,
    fk_value_pool: dict[str, list[Any]],
    context_hint: str = "",
) -> list[dict[str, Any]]:
    row_schema, columns = build_row_schema(table, fk_value_pool)
    if not columns:
        return [{}]

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

    rows = provider.generate(system, user_prompt, tool_schema, tool_name="generate_rows")
    if not rows:
        raise RuntimeError(f"Provider did not return any rows for table {table.name}")
    vector_columns = [c for c in table.columns if _is_vector_column(c)]
    for row in rows:
        for c in columns:
            col = table.column(c)
            if col and _is_media_url_column(col):
                row[c] = _random_media_url(col)
            elif col and _is_video_url_column(col):
                row[c] = _random_video_url()
        for vcol in vector_columns:
            row[vcol.name] = _random_vector_literal(vcol.vector_dim)
    return [_sanitize_row(table, row, fk_value_pool) for row in rows]