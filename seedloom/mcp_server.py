"""MCP server exposing seedloom as tools for AI coding agents (Claude Code,
Cursor, Windsurf, and any other MCP-capable client) to call directly, on top
of the existing CLI.

Run directly: `seedloom-mcp` (installed as a console script by `pip install
seedloom[mcp]`). Communicates over stdio, the standard transport for local
MCP servers - most clients launch it as a subprocess.

Provider API keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.) are read from
this process's environment only, via the same Config.load() the CLI uses -
never accepted as a tool argument - so a secret never has to pass through
the calling agent's context or logs.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .graph import CyclicDependencyError
from .introspect import introspect
from .pipeline import seed_database
from .providers import ProviderError, SUPPORTED_PROVIDERS

mcp = FastMCP("seedloom")


@mcp.tool()
def list_providers() -> list[str]:
    """List the LLM providers seedloom can generate seed data with (e.g.
    'anthropic', 'openai', 'gemini', 'ollama', 'groq', 'together',
    'fireworks', 'openrouter', 'deepseek', 'mistral', and local
    OpenAI-compatible servers). Each provider needs its matching API key
    already set as an environment variable on the machine running this MCP
    server - keys are never passed as a tool argument."""
    return SUPPORTED_PROVIDERS


@mcp.tool()
def introspect_schema(database_url: str) -> dict:
    """Connect to a PostgreSQL database and return its full schema: tables,
    columns, data types, nullability, uniqueness, foreign keys, enum
    values, and pgvector dimensions (for vector/halfvec/sparsevec columns).
    Read-only - makes no changes to the database. Useful for an agent to
    inspect a schema before deciding what/how to seed."""
    schema = introspect(database_url)
    return schema.to_dict()


@mcp.tool()
def seed(
    database_url: str,
    rows: int = 10,
    tables: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Generate and insert realistic, referentially-valid seed data into a
    PostgreSQL database. Introspects the schema, resolves foreign-key seed
    order (parents before dependents), generates rows with the configured
    LLM provider, and inserts them - foreign-key columns are structurally
    constrained to real, already-inserted parent-row values, so the model
    can never invent a dangling reference. pgvector columns are filled
    locally with correctly-sized, unit-length random vectors rather than
    asking the LLM to hand-write floats.

    Set dry_run=true to generate and preview rows without writing to the
    database - nothing is inserted, and the connection is never opened.

    `provider`/`model` override this server's default (from the
    SEEDLOOM_PROVIDER/SEEDLOOM_MODEL environment variables) for this call
    only. The matching API key (e.g. ANTHROPIC_API_KEY) must already be set
    in this server's environment - see list_providers - it is never
    accepted as a tool argument here.

    `tables` is an optional comma-separated subset (e.g. "users,orders");
    omit it to seed every table in dependency order. Tables that already
    have >= `rows` rows are skipped automatically.
    """
    try:
        result = seed_database(
            database_url=database_url,
            rows=rows,
            tables=tables,
            provider=provider,
            model=model,
            dry_run=dry_run,
        )
    except (EnvironmentError, ProviderError, CyclicDependencyError) as e:
        return {"error": str(e)}

    return {
        "provider": result.provider,
        "total_inserted": result.total_inserted,
        "tables": [
            {
                "table": t.table,
                "status": t.status,
                "rows_generated": t.rows_generated,
                "rows_inserted": t.rows_inserted,
                "existing_rows": t.existing_rows,
                "rows": t.rows if t.status == "dry_run" else None,
            }
            for t in result.tables
        ],
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()