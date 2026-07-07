"""Query execution backend for the sql-readonly MCP server.

`SQLAlchemyQueryExecutor` is the production binding: connects through
a Postgres role that itself only has SELECT grants, so even a bug in
`guard.validate_select_only` can't produce a write — defense in depth,
not a substitute for the guard.
"""
from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class QueryExecutor(Protocol):
    async def execute(
        self, sql: str, params: dict[str, Any] | None, row_limit: int
    ) -> list[dict[str, Any]]: ...


class SQLAlchemyQueryExecutor:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def execute(
        self, sql: str, params: dict[str, Any] | None, row_limit: int
    ) -> list[dict[str, Any]]:
        async with self._engine.connect() as conn:
            result = await conn.execute(text(sql), params or {})
            rows = result.mappings().fetchmany(row_limit)
            return [dict(row) for row in rows]
