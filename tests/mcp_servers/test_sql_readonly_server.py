from typing import Any

from tests.mcp_servers._loader import load_server_module

guard_module = load_server_module("sql-readonly", "guard.py")
executor_module = load_server_module("sql-readonly", "executor.py")
server_module = load_server_module("sql-readonly", "server.py")

build_server = server_module.build_server


class FakeQueryExecutor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, dict | None, int]] = []

    async def execute(self, sql: str, params: dict | None, row_limit: int) -> list[dict[str, Any]]:
        self.calls.append((sql, params, row_limit))
        return self._rows[:row_limit]


async def test_query_tool_returns_rows_for_valid_select() -> None:
    executor = FakeQueryExecutor([{"id": 1, "name": "Ramesh"}, {"id": 2, "name": "Priya"}])
    server = build_server(executor)
    _content, payload = await server.call_tool("query", {"sql": "SELECT * FROM patients"})
    assert payload["ok"] is True
    assert payload["row_count"] == 2
    assert payload["rows"] == [{"id": 1, "name": "Ramesh"}, {"id": 2, "name": "Priya"}]


async def test_query_tool_rejects_unsafe_sql_before_reaching_executor() -> None:
    executor = FakeQueryExecutor([])
    server = build_server(executor)
    _content, payload = await server.call_tool("query", {"sql": "DROP TABLE patients"})
    assert payload["ok"] is False
    assert executor.calls == []  # never reached the database


async def test_query_tool_caps_row_limit_at_max() -> None:
    rows = [{"id": i} for i in range(1000)]
    executor = FakeQueryExecutor(rows)
    server = build_server(executor, max_row_limit=10)
    _content, payload = await server.call_tool("query", {"sql": "SELECT * FROM patients", "row_limit": 999})
    assert executor.calls[0][2] == 10  # capped, not 999
    assert payload["row_count"] == 10


async def test_query_tool_passes_params_through_to_executor() -> None:
    executor = FakeQueryExecutor([])
    server = build_server(executor)
    await server.call_tool(
        "query", {"sql": "SELECT * FROM patients WHERE clinic_id = :cid", "params": {"cid": "clinic-1"}}
    )
    assert executor.calls[0][1] == {"cid": "clinic-1"}


async def test_server_exposes_single_query_tool() -> None:
    server = build_server(FakeQueryExecutor([]))
    tools = await server.list_tools()
    assert [t.name for t in tools] == ["query"]
