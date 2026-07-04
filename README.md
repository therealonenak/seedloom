# seedloom

AI-powered database seeding. `seedloom` connects to your PostgreSQL database,
introspects the real schema (tables, columns, types, foreign keys, enums,
constraints), and uses Claude to generate realistic, **referentially-valid**
seed data - then inserts it in the correct dependency order.

No more hand-writing 50 fake users and hoping your `orders` table's `user_id`
values actually exist.

## Why not just use Faker?

Faker generates *plausible-looking* values per column, with no awareness of
your schema's relationships. seedloom:

- Reads your **actual** schema (works with Prisma, Django, raw SQL migrations - anything)
- Resolves foreign key dependency order automatically (seeds `users` before `orders` before `order_items`)
- Constrains foreign-key columns to an `enum` of **real, already-inserted** parent IDs - Claude
  structurally cannot invent a dangling reference
- Respects `NOT NULL`, `UNIQUE`, enum types, and column types when generating values
- Skips columns the DB fills in itself (`SERIAL`, `gen_random_uuid()`, `now()` defaults)

## Install

```bash
pip install seedloom
```

Or from source:

```bash
git clone https://github.com/therealonenak/seedloom
cd seedloom
pip install -e .
```

## Setup

Set two environment variables (or put them in a `.env` file in your working directory):

```bash
export DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
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
```

Try it against the example schema in `examples/schema.sql` on a scratch database.

## How it works

1. **Introspect** - queries `information_schema` / `pg_catalog` to build a full
   picture of your schema: columns, types, nullability, uniqueness, enums, and
   foreign keys.
2. **Order** - topologically sorts tables so parents are always seeded before
   their dependents (`users` → `orders` → `order_items`).
3. **Generate** - for each table, builds a JSON Schema describing exactly what
   a valid row looks like (including an `enum` of real parent-key values for
   any FK column) and asks Claude to fill it in via tool-use / structured output.
4. **Insert** - batch-inserts the generated rows and tracks the primary keys
   the database assigns, so the *next* table's foreign keys always point at
   something real.

## Limitations (v1)

- PostgreSQL only (MySQL/SQLite support welcome as a PR)
- Single-column primary keys only for FK-pool tracking (composite PKs insert fine, just aren't reused as FK sources yet)
- No deferred-constraint support for genuinely cyclic FK relationships between two tables

## Contributing

PRs welcome - this was built as a learning project and is deliberately kept
readable over clever. Good first contributions: MySQL/SQLite introspection,
composite PK support, a `--seed-from-existing` mode that samples real rows
for context instead of generating from scratch.

## License

MIT
