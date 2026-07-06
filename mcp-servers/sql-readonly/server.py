"""SAAP read-only SQL MCP server (Phase 1 Epic 1.3) — the first
first-party server named in the Phase-1 milestone gate, enough for
simple reporting/lookup tools without hand-writing an N-th bespoke
connector.

Every call is validated by `guard.validate_select_only` BEFORE it
reaches the executor — no statement is ever passed through unchecked,
regardless of what the executor's own DB role permissions are.
"""
from __future__ import annotations

from typing import Any

from executor import QueryExecutor
from guard import UnsafeQuery, validate_select_only
from mcp.server.fastmcp import FastMCP

DEFAULT_ROW_LIMIT = 100


def build_server(executor: QueryExecutor, *, max_row_limit: int = 500) -> FastMCP:
    server: FastMCP = FastMCP(name="sql-readonly")

    @server.tool(description=f"Run a read-only SELECT query and return rows (max {max_row_limit} rows)")
    async def query(
        sql: str, params: dict[str, Any] | None = None, row_limit: int = DEFAULT_ROW_LIMIT
    ) -> dict[str, Any]:
        try:
            validate_select_only(sql)
        except UnsafeQuery as exc:
            return {"ok": False, "error": str(exc)}
        capped_limit = min(row_limit, max_row_limit)
        rows = await executor.execute(sql, params, capped_limit)
        return {"ok": True, "rows": rows, "row_count": len(rows)}

    return server
