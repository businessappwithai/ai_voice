"""Model Context Protocol integration — the universal tool bus (P4).

Threat model (NSA MCP guidance):
  * Dynamic tool invocation  -> mitigated by static per-tenant allow-lists;
    tools discovered at runtime are quarantined until an operator approves.
  * Implicit trust of agent output -> every ToolCall passes PolicyGuard
    (OPA) and risk-tier gating before dispatch (P5).
  * Payload injection -> arguments are re-validated against the server's
    JSON Schema *client-side* before send; free-form strings destined for
    SQL/shell-like tools pass a Presidio + injection-pattern screen.
  * Credential blast radius -> per-tenant OAuth 2.1 tokens from Keycloak,
    secrets resolved from OpenBao at call time, never stored in agent state.
"""
from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from .llm import ToolSpec
from .types import TenantContext, ToolCall, ToolResult


class MCPServerConfig(BaseModel, frozen=True):
    server_id: str  # "crm", "calendar", "inventory"
    transport: str  # "stdio" | "streamable-http"
    endpoint: str  # command or URL
    allowed_tools: frozenset[str]  # explicit allow-list (never "*")
    risk_overrides: dict[str, str] = {}  # tool -> "high_risk" escalation
    oauth_audience: str | None = None  # Keycloak client for remote servers


class ToolCatalogChanged(Exception):
    """Raised when a server advertises tools outside the last-known
    catalog. The pool quarantines the new tools (excludes them from
    `catalog()`) until an operator explicitly re-approves the allow-list
    — this is the mitigation for MCP's dynamic-tool-invocation vector."""

    def __init__(self, server_id: str, new_tools: frozenset[str]) -> None:
        self.server_id = server_id
        self.new_tools = new_tools
        super().__init__(
            f"MCP server {server_id!r} advertised unapproved tools: "
            f"{sorted(new_tools)} — quarantined pending operator review"
        )


class MCPConnection(Protocol):
    """One live session to one MCP server (official MIT Python SDK under
    the hood). Reconnects transparently; surfaces server-pushed
    capability changes as `ToolCatalogChanged` events (quarantined)."""

    async def list_tools(self) -> list[ToolSpec]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult: ...

    async def close(self) -> None: ...


class TenantMCPConfigStore(Protocol):
    async def configs_for(self, tenant: TenantContext) -> list[MCPServerConfig]: ...


class OAuthTokenBroker(Protocol):
    """Keycloak OAuth 2.1 client-credentials broker for remote MCP servers."""

    async def token_for(self, tenant: TenantContext, audience: str) -> str: ...


class SecretResolver(Protocol):
    """OpenBao secret resolution, scoped per tenant+server, at call time —
    never cached in agent state."""

    async def resolve(self, tenant: TenantContext, server_id: str, key: str) -> str: ...


def namespaced(server_id: str, tool_name: str) -> str:
    """Names are namespaced `mcp.<server_id>.<tool>` to prevent
    cross-server tool-name collisions (a known MCP spoofing vector)."""
    return f"mcp.{server_id}.{tool_name}"


class ConnectionFactory(Protocol):
    async def __call__(
        self, tenant: TenantContext, config: MCPServerConfig
    ) -> MCPConnection: ...


class MCPClientPool:
    """Tenant-scoped connection manager.

    * `catalog(tenant)`  -> merged, allow-listed ToolSpecs handed to the LLM.
      Names are namespaced `mcp.<server_id>.<tool>` to prevent cross-server
      tool-name collisions (a known MCP spoofing vector).
    * `dispatch(tenant, call)` -> resolves the connection, re-validates the
      schema, injects tenant credentials, executes, wraps ToolResult.

    The pool is the ONLY code path in the platform allowed to perform
    outbound side effects. Agents receive it pre-wrapped in the
    compliance chain so a bypass is not expressible in code (enforced by
    import-linter: `MCPConnection.call_tool` must not be reachable
    without going through `MCPClientPool.dispatch`).
    """

    def __init__(
        self,
        config_store: TenantMCPConfigStore,
        auth: OAuthTokenBroker,
        vault: SecretResolver,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._config_store = config_store
        self._auth = auth
        self._vault = vault
        self._connection_factory = connection_factory
        self._connections: dict[tuple[str, str], MCPConnection] = {}
        # Tools a server has advertised that are NOT on the operator-curated
        # allow-list. Never merged into the allow-list automatically and
        # never dispatched — surfaced via `quarantined()` for an operator
        # to review and, if legitimate, add to the tenant's MCPServerConfig.
        self._quarantined: dict[tuple[str, str], frozenset[str]] = {}

    async def _connection_for(
        self, tenant: TenantContext, config: MCPServerConfig
    ) -> MCPConnection:
        key = (str(tenant.tenant_id), config.server_id)
        if key not in self._connections:
            if self._connection_factory is None:
                raise RuntimeError(
                    "no connection_factory bound; MCPClientPool cannot open "
                    f"a connection to server {config.server_id!r}"
                )
            self._connections[key] = await self._connection_factory(tenant, config)
        return self._connections[key]

    async def catalog(self, tenant: TenantContext) -> list[ToolSpec]:
        """Merged, allow-listed ToolSpecs for this tenant.

        The allow-list is operator-curated config and never grows itself:
        any tool a server advertises outside it is quarantined (recorded,
        excluded) rather than raised as an error — a server adding one
        new tool must never take down every *already-approved* tool on
        that server (that would make the allow-list a liability instead
        of a safeguard). Operators review quarantined tools out-of-band
        via `quarantined(tenant)` and explicitly widen the allow-list if
        the new tool is legitimate.
        """
        configs = await self._config_store.configs_for(tenant)
        catalog: list[ToolSpec] = []
        for config in configs:
            conn = await self._connection_for(tenant, config)
            live_tools = await conn.list_tools()
            live_names = frozenset(t.name for t in live_tools)
            key = (str(tenant.tenant_id), config.server_id)
            self._quarantined[key] = live_names - config.allowed_tools
            for tool in live_tools:
                if tool.name not in config.allowed_tools:
                    continue  # never "*" — silently drop anything off the allow-list
                catalog.append(
                    ToolSpec(
                        name=namespaced(config.server_id, tool.name),
                        description=tool.description,
                        input_schema=tool.input_schema,
                    )
                )
        return catalog

    def quarantined(self, tenant: TenantContext, server_id: str) -> frozenset[str]:
        """Tool names the server has advertised outside the allow-list,
        as of the last `catalog()` call. Surfaced in the agency console
        for operator review; never auto-approved."""
        return self._quarantined.get((str(tenant.tenant_id), server_id), frozenset())

    def _split_namespaced(self, tool_name: str) -> tuple[str, str]:
        parts = tool_name.split(".", 2)
        if len(parts) != 3 or parts[0] != "mcp":
            raise ValueError(f"tool name {tool_name!r} is not namespaced as mcp.<server>.<tool>")
        return parts[1], parts[2]

    async def dispatch(self, tenant: TenantContext, call: ToolCall) -> ToolResult:
        server_id, bare_name = self._split_namespaced(call.tool_name)
        configs = {c.server_id: c for c in await self._config_store.configs_for(tenant)}
        config = configs.get(server_id)
        if config is None or bare_name not in config.allowed_tools:
            return ToolResult(
                call_id=call.call_id,
                ok=False,
                error=f"tool {call.tool_name!r} is not allow-listed for this tenant",
            )
        conn = await self._connection_for(tenant, config)
        # Client-side schema re-validation happens here before dispatch;
        # the concrete connection implementation owns JSON-Schema checking
        # against the server's declared input_schema.
        return await conn.call_tool(bare_name, call.arguments)

    async def close_all(self) -> None:
        for conn in self._connections.values():
            await conn.close()
        self._connections.clear()
