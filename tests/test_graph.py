from seedloom.graph import CyclicDependencyError, resolve_seed_order
from seedloom.models import Column, ForeignKey, Schema, Table


def make_schema():
    """users <- orders <- order_items, plus a standalone 'categories' table."""
    schema = Schema()

    users = Table(name="users", columns=[Column("id", "integer", False, is_primary_key=True)])
    categories = Table(name="categories", columns=[Column("id", "integer", False, is_primary_key=True)])

    orders = Table(
        name="orders",
        columns=[
            Column("id", "integer", False, is_primary_key=True),
            Column("user_id", "integer", False),
        ],
        foreign_keys=[ForeignKey(column="user_id", ref_table="users", ref_column="id")],
    )

    order_items = Table(
        name="order_items",
        columns=[
            Column("id", "integer", False, is_primary_key=True),
            Column("order_id", "integer", False),
        ],
        foreign_keys=[ForeignKey(column="order_id", ref_table="orders", ref_column="id")],
    )

    for t in (users, categories, orders, order_items):
        schema.add_table(t)
    return schema


def test_resolve_seed_order_respects_dependencies():
    schema = make_schema()
    order = resolve_seed_order(schema)

    assert order.index("users") < order.index("orders")
    assert order.index("orders") < order.index("order_items")
    assert "categories" in order  # independent table still included
    assert set(order) == {"users", "categories", "orders", "order_items"}


def test_self_reference_does_not_break_ordering():
    schema = Schema()
    employees = Table(
        name="employees",
        columns=[
            Column("id", "integer", False, is_primary_key=True),
            Column("manager_id", "integer", True),
        ],
        foreign_keys=[ForeignKey(column="manager_id", ref_table="employees", ref_column="id")],
    )
    schema.add_table(employees)

    order = resolve_seed_order(schema)
    assert order == ["employees"]


def test_cyclic_dependency_raises():
    schema = Schema()
    a = Table(
        name="a",
        columns=[Column("id", "integer", False, is_primary_key=True), Column("b_id", "integer", True)],
        foreign_keys=[ForeignKey(column="b_id", ref_table="b", ref_column="id")],
    )
    b = Table(
        name="b",
        columns=[Column("id", "integer", False, is_primary_key=True), Column("a_id", "integer", True)],
        foreign_keys=[ForeignKey(column="a_id", ref_table="a", ref_column="id")],
    )
    schema.add_table(a)
    schema.add_table(b)

    try:
        resolve_seed_order(schema)
        assert False, "expected CyclicDependencyError"
    except CyclicDependencyError:
        pass


def test_schema_roundtrip_serialization():
    schema = make_schema()
    restored = Schema.from_dict(schema.to_dict())
    assert set(restored.tables.keys()) == set(schema.tables.keys())
    assert restored.tables["orders"].foreign_keys[0].ref_table == "users"
