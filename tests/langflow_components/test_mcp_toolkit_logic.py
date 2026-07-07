from uuid import uuid4

import pytest
from saap.core.fakes import FakeMCPConnection
from saap.core.llm import ToolSpec
from saap.core.mcp import MCPClientPool, MCPServerConfig
from saap.core.types import TenantContext, ToolCall
from saap.langflow_components.logic.mcp_toolkit import MCPToolkitLogic


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


class ScriptedGuard:
    def __init__(self, decision: str) -> None:
        self._decision = decision

    async def evaluate(self, tenant, call):  # noqa: ANN001
        return self._decision


def _pool(tenant: TenantContext, conn: FakeMCPConnection) -> MCPClientPool:
    config = MCPServerConfig(
        server_id="calendar", transport="stdio", endpoint="x", allowed_tools=frozenset({"book_slot"})
    )

    class ConfigStore:
        async def configs_for(self, t):  # noqa: ANN001
            return [config]

    class Auth:
        async def token_for(self, t, audience):  # noqa: ANN001
            return "token"

    class Vault:
        async def resolve(self, t, server_id, key):  # noqa: ANN001
            return "secret"

    async def factory(t, c):  # noqa: ANN001
        return conn

    return MCPClientPool(ConfigStore(), Auth(), Vault(), connection_factory=factory)


async def test_build_tools_delegates_to_pool_catalog(tenant: TenantContext) -> None:
    conn = FakeMCPConnection(tools=[ToolSpec(name="book_slot", description="book", input_schema={})])
    logic = MCPToolkitLogic(_pool(tenant, conn), ScriptedGuard("allow"))
    tools = await logic.build_tools(tenant)
    assert [t.name for t in tools] == ["mcp.calendar.book_slot"]


async def test_allow_decision_dispatches_and_returns_result(tenant: TenantContext) -> None:
    conn = FakeMCPConnection()
    logic = MCPToolkitLogic(_pool(tenant, conn), ScriptedGuard("allow"))
    call = ToolCall(call_id="1", tool_name="mcp.calendar.book_slot", arguments={"when": "tomorrow"})
    outcome = await logic.handle_call(tenant, call)
    assert outcome.kind == "dispatched"
    assert outcome.result is not None and outcome.result.ok is True
    assert conn.calls == [("book_slot", {"when": "tomorrow"})]


async def test_deny_decision_never_touches_pool(tenant: TenantContext) -> None:
    conn = FakeMCPConnection()
    logic = MCPToolkitLogic(_pool(tenant, conn), ScriptedGuard("deny"))
    call = ToolCall(call_id="1", tool_name="mcp.calendar.book_slot", arguments={})
    outcome = await logic.handle_call(tenant, call)
    assert outcome.kind == "denied"
    assert outcome.result is not None and outcome.result.ok is False
    assert conn.calls == []


async def test_require_human_never_touches_pool(tenant: TenantContext) -> None:
    conn = FakeMCPConnection()
    logic = MCPToolkitLogic(_pool(tenant, conn), ScriptedGuard("require_human"))
    call = ToolCall(call_id="1", tool_name="mcp.calendar.book_slot", arguments={"amount": 5000}, risk_tier="high_risk")
    outcome = await logic.handle_call(tenant, call)
    assert outcome.kind == "pending_approval"
    assert outcome.tool_call == call
    assert conn.calls == []
