"""Resolve the order tables must be seeded in, based on foreign key dependencies.

A table depends on every table its foreign keys point to (excluding self-references,
which are seeded as NULL-first-then-update or just left nullable). Raises on a
genuine cycle between two *different* tables, since that can't be seeded without
deferred constraints (out of scope for v1 - surfaced as a clear error instead of
a silent wrong answer).
"""
from __future__ import annotations

from .models import Schema


class CyclicDependencyError(Exception):
    pass


def resolve_seed_order(schema: Schema) -> list[str]:
    deps: dict[str, set[str]] = {}
    for table in schema.tables.values():
        table_deps = set()
        for fk in table.foreign_keys:
            if fk.ref_table != table.name and fk.ref_table in schema.tables:
                table_deps.add(fk.ref_table)
        deps[table.name] = table_deps

    ordered: list[str] = []
    visited: set[str] = set()
    in_progress: set[str] = set()

    def visit(name: str, path: list[str]) -> None:
        if name in visited:
            return
        if name in in_progress:
            raise CyclicDependencyError(
                f"Cyclic foreign key dependency detected: {' -> '.join(path + [name])}. "
                "seedloom can't resolve insert order for mutually-dependent tables in v1 - "
                "consider making one of the FKs nullable and seeding it in a second pass."
            )
        in_progress.add(name)
        for dep in deps.get(name, set()):
            visit(dep, path + [name])
        in_progress.discard(name)
        visited.add(name)
        ordered.append(name)

    for table_name in schema.tables:
        visit(table_name, [])

    return ordered
