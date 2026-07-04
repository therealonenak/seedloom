"""End-to-end flow test: introspection-shaped schema -> ordering -> generation
(mocked LLM) -> insertion (fake in-memory DB), verifying FK values seeded for
'users' actually get used when generating 'orders'."""
from unittest.mock import MagicMock

from seedloom.generator import generate_rows
from seedloom.graph import resolve_seed_order
from seedloom.inserter import insert_rows
from seedloom.models import Column, ForeignKey, Schema, Table


class FakeCursor:
    def __init__(self, store, pk_seq):
        self.store = store
        self.pk_seq = pk_seq
        self._last_pk = None

    def execute(self, query, params):
        table_name = query.split('"')[1]
        self._last_pk = self.pk_seq[table_name]
        self.pk_seq[table_name] += 1
        self.store.setdefault(table_name, []).append(dict(params))

    def fetchone(self):
        return (self._last_pk,)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class FakeConn:
    def __init__(self):
        self.store: dict[str, list] = {}
        self.pk_seq: dict[str, int] = {"users": 1, "orders": 1}

    def cursor(self):
        return FakeCursor(self.store, self.pk_seq)

    def commit(self):
        pass


def make_tool_response(rows):
    block = MagicMock()
    block.type = "tool_use"
    block.name = "generate_rows"
    block.input = {"rows": rows}
    resp = MagicMock()
    resp.content = [block]
    return resp


def test_end_to_end_seed_flow_links_foreign_keys():
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
                Column("total", "numeric", False),
            ],
            foreign_keys=[ForeignKey(column="user_id", ref_table="users", ref_column="id")],
        )
    )

    order = resolve_seed_order(schema)
    assert order == ["users", "orders"]

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        make_tool_response([{"name": "Alice"}, {"name": "Bob"}]),
        make_tool_response([{"user_id": 1, "total": 42.5}, {"user_id": 2, "total": 10.0}]),
    ]

    conn = FakeConn()
    fk_pools: dict[str, dict[str, list]] = {}

    for table_name in order:
        table = schema.tables[table_name]
        fk_value_pool = {}
        for fk in table.foreign_keys:
            pool = fk_pools.get(fk.ref_table, {}).get(fk.ref_column, [])
            if pool:
                fk_value_pool[fk.column] = pool

        generated = generate_rows(fake_client, "claude-sonnet-4-6", table, 2, fk_value_pool)
        pk_values = insert_rows(conn, table, generated)
        pk_cols = table.primary_key_columns
        if len(pk_cols) == 1 and pk_values:
            fk_pools.setdefault(table_name, {})[pk_cols[0]] = pk_values

    # users got PKs 1, 2 assigned
    assert fk_pools["users"]["id"] == [1, 2]
    # orders were inserted referencing those real user ids
    assert conn.store["orders"][0]["user_id"] == 1
    assert conn.store["orders"][1]["user_id"] == 2

    # verify the second LLM call's schema actually constrained user_id to the real pool
    second_call_kwargs = fake_client.messages.create.call_args_list[1].kwargs
    order_row_schema = second_call_kwargs["tools"][0]["input_schema"]["properties"]["rows"]["items"]
    assert order_row_schema["properties"]["user_id"] == {"enum": [1, 2]}
