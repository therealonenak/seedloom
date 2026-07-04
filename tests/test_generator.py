from seedloom.generator import build_row_schema
from seedloom.models import Column, ForeignKey, Table


def test_skips_auto_generated_columns():
    table = Table(
        name="users",
        columns=[
            Column("id", "integer", False, is_primary_key=True, default="nextval('users_id_seq')"),
            Column("name", "text", False),
            Column("created_at", "timestamp without time zone", False, default="now()"),
        ],
    )
    schema, generatable = build_row_schema(table, fk_value_pool={})
    assert "id" not in generatable
    assert "created_at" not in generatable
    assert "name" in generatable
    assert schema["properties"]["name"] == {"type": "string"}


def test_fk_column_becomes_enum_of_pool_values():
    table = Table(
        name="orders",
        columns=[
            Column("id", "integer", False, is_primary_key=True, default="nextval('orders_id_seq')"),
            Column("user_id", "integer", False),
        ],
        foreign_keys=[ForeignKey(column="user_id", ref_table="users", ref_column="id")],
    )
    schema, generatable = build_row_schema(table, fk_value_pool={"user_id": [1, 2, 3]})
    assert schema["properties"]["user_id"] == {"enum": [1, 2, 3]}
    assert "user_id" in generatable


def test_fk_column_skipped_when_pool_empty():
    table = Table(
        name="orders",
        columns=[
            Column("id", "integer", False, is_primary_key=True, default="nextval('orders_id_seq')"),
            Column("user_id", "integer", True),
        ],
        foreign_keys=[ForeignKey(column="user_id", ref_table="users", ref_column="id")],
    )
    schema, generatable = build_row_schema(table, fk_value_pool={})
    assert "user_id" not in generatable


def test_enum_column_uses_enum_values():
    table = Table(
        name="orders",
        columns=[
            Column("id", "integer", False, is_primary_key=True, default="nextval('orders_id_seq')"),
            Column("status", "order_status", False, enum_values=["pending", "shipped", "delivered"]),
        ],
    )
    schema, _ = build_row_schema(table, fk_value_pool={})
    assert schema["properties"]["status"] == {
        "type": "string",
        "enum": ["pending", "shipped", "delivered"],
    }


def test_required_excludes_nullable_columns():
    table = Table(
        name="users",
        columns=[
            Column("id", "integer", False, is_primary_key=True, default="nextval('x')"),
            Column("name", "text", False),
            Column("middle_name", "text", True),
        ],
    )
    schema, _ = build_row_schema(table, fk_value_pool={})
    assert "name" in schema["required"]
    assert "middle_name" not in schema["required"]
