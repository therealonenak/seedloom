"""Plain data models describing a database schema.

Kept independent of any DB driver so they can be unit-tested with fixtures
and reused if/when other engines (MySQL, SQLite) are added.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ForeignKey:
    column: str
    ref_table: str
    ref_column: str


@dataclass
class Column:
    name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool = False
    is_unique: bool = False
    default: Optional[str] = None
    char_max_length: Optional[int] = None
    numeric_precision: Optional[int] = None
    enum_values: Optional[list[str]] = None
    vector_dim: Optional[int] = None

    @property
    def is_auto_generated(self) -> bool:
        """True for serial/identity/default-driven columns the agent shouldn't invent."""
        if self.default is None:
            return False
        d = self.default.lower()
        return "nextval(" in d or "gen_random_uuid" in d or "uuid_generate" in d or "now()" in d


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)

    @property
    def primary_key_columns(self) -> list[str]:
        return [c.name for c in self.columns if c.is_primary_key]

    def column(self, name: str) -> Optional[Column]:
        return next((c for c in self.columns if c.name == name), None)


@dataclass
class Schema:
    tables: dict[str, Table] = field(default_factory=dict)

    def add_table(self, table: Table) -> None:
        self.tables[table.name] = table

    def to_dict(self) -> dict:
        return {
            t.name: {
                "columns": [
                    {
                        "name": c.name,
                        "data_type": c.data_type,
                        "is_nullable": c.is_nullable,
                        "is_primary_key": c.is_primary_key,
                        "is_unique": c.is_unique,
                        "default": c.default,
                        "char_max_length": c.char_max_length,
                        "numeric_precision": c.numeric_precision,
                        "enum_values": c.enum_values,
                        "vector_dim": c.vector_dim,
                    }
                    for c in t.columns
                ],
                "foreign_keys": [
                    {"column": fk.column, "ref_table": fk.ref_table, "ref_column": fk.ref_column}
                    for fk in t.foreign_keys
                ],
            }
            for t in self.tables.values()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Schema":
        schema = cls()
        for table_name, t in data.items():
            table = Table(name=table_name)
            for c in t["columns"]:
                table.columns.append(Column(**c))
            for fk in t["foreign_keys"]:
                table.foreign_keys.append(ForeignKey(**fk))
            schema.add_table(table)
        return schema