"""Tests for seedloom.pipeline - the shared logic behind both the CLI and
the MCP server. Uses monkeypatching to avoid needing a real Postgres
connection or LLM provider; dry_run=True also means psycopg2.connect is
never called."""
from __future__ import annotations

import seedloom.pipeline as pipeline
from seedloom.config import Config
from seedloom.models import Column, ForeignKey, Schema, Table
from seedloom.providers.base import Provider


class FakeProvider(Provider):
    def __init__(self, responses):
        self.responses = list(responses)

    def generate(self, system, user_prompt, schema, tool_name="generate_rows"):
        return self.responses.pop(0)


def _fake_schema() -> Schema:
    schema = Schema()
    schema.add_table(
        Table(
            name="users",
            columns=[
                Column("id", "integer", False, is_primary_key=True, default="nextval('users_id_seq')"),
                Column("name", "text", False),
            ],
        )
    )
    schema.add_table(
        Table(
            name="orders",
            columns=[
                Column("id", "integer", False, is_primary_key=True, default="nextval('orders_id_seq')"),
                Column("user_id", "integer", False),
            ],
            foreign_keys=[ForeignKey(column="user_id", ref_table="users", ref_column="id")],
        )
    )
    return schema


def _patch_common(monkeypatch, provider, schema=None):
    monkeypatch.setattr(
        Config,
        "load",
        lambda provider_override="", require_provider=True: Config(
            database_url="postgresql://fake/fake", provider="anthropic", api_key="fake-key"
        ),
    )
    monkeypatch.setattr(pipeline, "get_provider", lambda *a, **k: provider)
    monkeypatch.setattr(pipeline, "load_or_build_schema", lambda *a, **k: schema or _fake_schema())


def test_dry_run_returns_structured_results_without_touching_db(monkeypatch):
    provider = FakeProvider(
        [
            [{"name": "Alice"}, {"name": "Bob"}],
            [{"user_id": 1}, {"user_id": 2}],
        ]
    )
    _patch_common(monkeypatch, provider)

    result = pipeline.seed_database(database_url="postgresql://fake/fake", rows=2, dry_run=True)

    assert result.provider == "anthropic"
    assert [t.table for t in result.tables] == ["users", "orders"]
    assert result.tables[0].status == "dry_run"
    assert result.tables[0].rows == [{"name": "Alice"}, {"name": "Bob"}]
    assert result.total_inserted == 0  # nothing is ever inserted in dry_run


def test_tables_filter_only_seeds_requested_tables(monkeypatch):
    provider = FakeProvider([[{"name": "Alice"}]])
    _patch_common(monkeypatch, provider)

    result = pipeline.seed_database(
        database_url="postgresql://fake/fake", rows=1, tables="users", dry_run=True
    )

    assert [t.table for t in result.tables] == ["users"]


def test_missing_database_url_raises_environment_error(monkeypatch):
    provider = FakeProvider([])
    monkeypatch.setattr(
        Config,
        "load",
        lambda provider_override="", require_provider=True: Config(
            database_url="", provider="anthropic", api_key="fake-key"
        ),
    )
    monkeypatch.setattr(pipeline, "get_provider", lambda *a, **k: provider)

    try:
        pipeline.seed_database(database_url=None, dry_run=True)
        assert False, "expected EnvironmentError"
    except EnvironmentError as e:
        assert "DATABASE_URL" in str(e)