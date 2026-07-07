"""Framework-agnostic logic behind the `MCPToolkit` sealed canvas
component (architecture Section 5.2/§4.4). Wraps `MCPClientPool` +
`PolicyGuard` so the NSA-guidance mitigations are non-optional on the
canvas: only allow-listed, namespaced ToolSpecs are ever offered to the
connected Agent component, and every proposed call passes PolicyGuard
before dispatch — `allow` executes, `deny` returns a safe failure,
`require_human` never touches the MCP pool at all and instead produces
an outcome the `HITLCheckpoint` component turns into an ApprovalRequest.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from saap.compliance.policy import PolicyGuard
from saap.core.llm import ToolSpec
from saap.core.mcp import MCPClientPool
from saap.core.types import TenantContext, ToolCall, ToolResult

OutcomeKind = Literal["dispatched", "denied", "pending_approval"]


@dataclass(frozen=True)
class MCPToolkitOutcome:
    kind: OutcomeKind
    result: ToolResult | None = None
    tool_call: ToolCall | None = None


class MCPToolkitLogic:
    def __init__(self, pool: MCPClientPool, guard: PolicyGuard) -> None:
        self._pool = pool
        self._guard = guard

    async def build_tools(self, tenant: TenantContext) -> list[ToolSpec]:
        return await self._pool.catalog(tenant)

    async def handle_call(self, tenant: TenantContext, call: ToolCall) -> MCPToolkitOutcome:
        decision = await self._guard.evaluate(tenant, call)
        if decision == "deny":
            return MCPToolkitOutcome(
                kind="denied",
                result=ToolResult(call_id=call.call_id, ok=False, error="denied by policy"),
            )
        if decision == "require_human":
            # Deliberately never reaches the MCP pool — the whole point
            # of this branch is that no side effect happens without a
            # human approval round-trip (P5).
            return MCPToolkitOutcome(kind="pending_approval", tool_call=call)
        result = await self._pool.dispatch(tenant, call)
        return MCPToolkitOutcome(kind="dispatched", result=result)
