from uuid import uuid4

import pytest
from saap.core.fakes import FakeMCPConnection
from saap.core.llm import ToolSpec
from saap.core.mcp import MCPClientPool, MCPServerConfig
from saap.core.types import TenantContext, ToolCall


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


def _make_pool(tenant: TenantContext, config: MCPServerConfig, conn: FakeMCPConnection) -> MCPClientPool:
    class ConfigStore:
        async def configs_for(self, t: TenantContext) -> list[MCPServerConfig]:
            return [config]

    class Auth:
        async def token_for(self, t: TenantContext, audience: str) -> str:
            return "token"

    class Vault:
        async def resolve(self, t: TenantContext, server_id: str, key: str) -> str:
            return "secret"

    async def factory(t: TenantContext, c: MCPServerConfig) -> FakeMCPConnection:
        return conn

    return MCPClientPool(ConfigStore(), Auth(), Vault(), connection_factory=factory)


async def test_catalog_namespaces_tools_and_respects_allowlist(tenant: TenantContext) -> None:
    config = MCPServerConfig(
        server_id="calendar",
        transport="stdio",
        endpoint="calendar-mcp",
        allowed_tools=frozenset({"book_slot"}),
    )
    conn = FakeMCPConnection(
        tools=[
            ToolSpec(name="book_slot", description="book", input_schema={}),
            ToolSpec(name="delete_all", description="danger", input_schema={}),
        ]
    )
    pool = _make_pool(tenant, config, conn)

    catalog = await pool.catalog(tenant)
    names = {t.name for t in catalog}
    assert names == {"mcp.calendar.book_slot"}  # delete_all silently dropped, never "*"


async def test_catalog_quarantines_unapproved_tool_expansion_without_failing(
    tenant: TenantContext,
) -> None:
    config = MCPServerConfig(
        server_id="calendar",
        transport="stdio",
        endpoint="calendar-mcp",
        allowed_tools=frozenset({"book_slot", "cancel_slot"}),
    )
    conn = FakeMCPConnection(
        tools=[
            ToolSpec(name="book_slot", description="book", input_schema={}),
            ToolSpec(name="cancel_slot", description="cancel", input_schema={}),
            ToolSpec(name="wipe_calendar", description="new + dangerous", input_schema={}),
        ]
    )
    pool = _make_pool(tenant, config, conn)

    # The already-approved tools must keep working...
    catalog = await pool.catalog(tenant)
    names = {t.name for t in catalog}
    assert names == {"mcp.calendar.book_slot", "mcp.calendar.cancel_slot"}

    # ...while the new, unapproved one is quarantined for operator review,
    # not silently merged into the allow-list and not blocking the call.
    assert pool.quarantined(tenant, "calendar") == frozenset({"wipe_calendar"})


async def test_dispatch_rejects_non_allowlisted_tool(tenant: TenantContext) -> None:
    config = MCPServerConfig(
        server_id="calendar",
        transport="stdio",
        endpoint="calendar-mcp",
        allowed_tools=frozenset({"book_slot"}),
    )
    conn = FakeMCPConnection()
    pool = _make_pool(tenant, config, conn)

    result = await pool.dispatch(
        tenant, ToolCall(call_id="1", tool_name="mcp.calendar.delete_everything", arguments={})
    )
    assert result.ok is False
    assert conn.calls == []  # never reached the connection


async def test_dispatch_calls_allowlisted_tool(tenant: TenantContext) -> None:
    config = MCPServerConfig(
        server_id="calendar",
        transport="stdio",
        endpoint="calendar-mcp",
        allowed_tools=frozenset({"book_slot"}),
    )
    conn = FakeMCPConnection()
    pool = _make_pool(tenant, config, conn)

    result = await pool.dispatch(
        tenant, ToolCall(call_id="1", tool_name="mcp.calendar.book_slot", arguments={"when": "tomorrow"})
    )
    assert result.ok is True
    assert conn.calls == [("book_slot", {"when": "tomorrow"})]


def test_dispatch_requires_namespaced_tool_name() -> None:
    from saap.core.mcp import MCPClientPool as Pool

    pool = Pool.__new__(Pool)  # bypass __init__, only testing the pure helper
    with pytest.raises(ValueError):
        pool._split_namespaced("book_slot")
