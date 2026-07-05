<p align="center">
  <img src="https://raw.githubusercontent.com/therealonenak/seedloom/main/assets/logo.svg" width="320" alt="seedloom logo">
</p>

<p align="center">Seed your database, automated.</p>

# seedloom

AI-powered database seeding. `seedloom` connects to your PostgreSQL database,
introspects the real schema (tables, columns, types, foreign keys, enums,
constraints), and uses an LLM to generate realistic, **referentially-valid**
seed data - then inserts it in the correct dependency order.

Works with Claude, OpenAI, Gemini, local Ollama models, and any
OpenAI-compatible endpoint (Groq, Together, Fireworks, OpenRouter, DeepSeek,
Mistral, LM Studio, vLLM, text-generation-webui) - see [Providers](#providers).

No more hand-writing 50 fake users and hoping your `orders` table's `user_id`
values actually exist.

## Why not just use Faker?

Faker generates *plausible-looking* values per column, with no awareness of
your schema's relationships. seedloom:

- Reads your **actual** schema (works with Prisma, Django, raw SQL migrations - anything)
- Resolves foreign key dependency order automatically (seeds `users` before `orders` before `order_items`)
- Constrains foreign-key columns to an `enum` of **real, already-inserted** parent IDs - the model
  structurally cannot invent a dangling reference
- Respects `NOT NULL`, `UNIQUE`, enum types, and column types when generating values
- Skips columns the DB fills in itself (`SERIAL`, `gen_random_uuid()`, `now()` defaults)
- Auto-fills image/avatar/logo/banner/video columns with real, working CDN URLs
  (picsum.photos, i.pravatar.cc, sample .mp4s) instead of letting the model
  invent broken links
- **pgvector-aware**: `vector`/`halfvec`/`sparsevec` columns are detected at
  introspection time (including their declared dimension) and filled with
  real, correctly-sized, unit-length random vectors - generated locally, not
  by asking an LLM to hand-write hundreds of floats
- Automatically excludes ORM/migration bookkeeping tables (`SequelizeMeta`,
  `knex_migrations`, `alembic_version`, `django_migrations`,
  `__EFMigrationsHistory`, etc.) from introspection - they're never seeded
- Swap the LLM provider with one flag or env var - cloud or fully local/free

## Install

```bash
pip install seedloom[anthropic]   # or [openai], [gemini], [ollama], [all]
```

Or from source:

```bash
git clone https://github.com/therealonenak/seedloom
cd seedloom
pip install -e ".[all]"
```

Each provider is an optional extra so you only install the SDK you need.
`ollama` has no cloud SDK - it just needs `requests`, already covered by that extra.

## Setup

Set `DATABASE_URL` plus whichever provider you're using (or put them in a `.env`
file in your working directory):

```bash
export DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
export SEEDLOOM_PROVIDER="anthropic"       # default; see Providers below
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Usage

```bash
# 1. Introspect your schema and cache it locally
seedloom init

# 2. Generate + insert seed data, in FK-safe order
seedloom run --rows 20

# Preview generated data without inserting anything
seedloom run --rows 5 --dry-run

# Only seed specific tables
seedloom run --rows 50 --tables users,products

# Override the provider/model for a single run
seedloom run --provider gemini --model gemini-2.5-flash --rows 20
seedloom run --provider ollama --model llama3.1 --rows 20
```

Try it against the example schema in `examples/schema.sql` on a scratch database.

## pgvector

If the [`pgvector`](https://github.com/pgvector/pgvector) extension is
installed and a table has a `vector`, `halfvec`, or `sparsevec` column,
seedloom detects it during `seedloom init` (along with its declared
dimension, e.g. `vector(384)`) and fills it with a random, unit-length
vector at seed time - generated locally, not by the LLM. This is enough to
exercise vector indexes and similarity queries (`ORDER BY embedding <-> ...`)
against seed data, but the vectors carry no real semantic meaning - they
aren't embeddings of the row's actual content.

Columns declared as a plain `vector` with no fixed dimension fall back to a
default width (currently 256).

No separate install extra is needed - this works with `pip install seedloom`
plus whichever provider extra you're already using.

## Providers

Set `SEEDLOOM_PROVIDER` (or pass `--provider`) plus the matching API key env var.
`SEEDLOOM_MODEL` overrides the default model for any provider.

| Provider | `SEEDLOOM_PROVIDER` | API key env var | Notes |
|---|---|---|---|
| Anthropic (Claude) | `anthropic` | `ANTHROPIC_API_KEY` | default |
| OpenAI | `openai` | `OPENAI_API_KEY` | |
| Google Gemini | `gemini` | `GEMINI_API_KEY` | official Gemini API; free tier is capped at 20 requests/day per model - schemas with many tables will likely exhaust it in one run |
| Ollama (local) | `ollama` | - | run any open-source model locally; needs `ollama serve` |
| Groq | `groq` | `GROQ_API_KEY` | free tier, serves open-source models fast |
| Together AI | `together` | `TOGETHER_API_KEY` | open-source models, free tier |
| Fireworks AI | `fireworks` | `FIREWORKS_API_KEY` | open-source models |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` | many free `:free`-suffixed open-source models |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` | |
| Mistral | `mistral` | `MISTRAL_API_KEY` | |
| LM Studio (local) | `lmstudio` | - | local server, OpenAI-compatible |
| vLLM (local) | `vllm` | - | local server, OpenAI-compatible |
| text-generation-webui (local) | `text_generation_webui` | - | local server, OpenAI-compatible |
| Any OpenAI-compatible endpoint | `openai_compatible` | `OPENAI_COMPATIBLE_API_KEY` | set `SEEDLOOM_BASE_URL` |

Ollama host defaults to `http://localhost:11434`; override with `SEEDLOOM_HOST` or `--host`.
Custom/self-hosted OpenAI-compatible endpoints use `SEEDLOOM_BASE_URL` or `--base-url`.

A note on **Google Antigravity**: it's a desktop agentic IDE, not something with
a public API for scripts like this to call. If you want Google's models
programmatically, `gemini` (the official Gemini API) is the supported path -
same models, real API key, free tier included.

## How it works

1. **Introspect** - queries `information_schema` / `pg_catalog` to build a full
   picture of your schema: columns, types, nullability, uniqueness, enums, and
   foreign keys. ORM/migration bookkeeping tables are filtered out automatically.
2. **Order** - topologically sorts tables so parents are always seeded before
   their dependents (`users` → `orders` → `order_items`).
3. **Generate** - for each table, builds a JSON Schema describing exactly what
   a valid row looks like (including an `enum` of real parent-key values for
   any FK column) and asks the configured provider to fill it in via
   tool-use / structured output. Image/video columns are then populated with
   real, working CDN URLs rather than model-invented links.
4. **Insert** - batch-inserts the generated rows and tracks the primary keys
   the database assigns, so the *next* table's foreign keys always point at
   something real.

## Rate limits

Cloud providers get automatic retry with exponential backoff on transient
429/rate-limit errors, honoring the provider's own suggested retry delay
when it's present in the error. If a provider reports a **daily** quota is
exhausted (e.g. Gemini's free-tier 20-requests/day cap), seedloom fails
fast with a clear message instead of retrying for several minutes against
a quota that won't reset - switch `--provider`/`--model` or re-run once it
resets. Already-seeded tables are skipped automatically on the next run.

## Limitations (v1)

- PostgreSQL only (MySQL/SQLite support welcome as a PR)
- Single-column primary keys only for FK-pool tracking (composite PKs insert fine, just aren't reused as FK sources yet)
- No deferred-constraint support for genuinely cyclic FK relationships between two tables
- No per-provider quota/cost estimation before a run - a large schema can burn through a free-tier daily quota in a single `seedloom run`

## Contributing

PRs welcome - this was built as a learning project and is deliberately kept
readable over clever. Good first contributions: MySQL/SQLite introspection,
composite PK support, a `--seed-from-existing` mode that samples real rows
for context instead of generating from scratch.

## License

MIT