"""PolicyGuard — OPA/Rego per-tenant action policy (L5 stage 3).

Production deployments run a real OPA sidecar (`OPAPolicyGuard`, HTTP
to `POST /v1/data/saap/actions`); the Rego policy pack lives in
`policies/tenant/*.rego` (see policies/tenant/dental_clinic.rego for a
worked example: read allowed always, write allowed in business hours,
high_risk always routed to HITL).

`InMemoryPolicyGuard` reimplements the same three-tier decision table in
Python for unit tests and any environment without an OPA sidecar
reachable (e.g. a laptop dev profile) — it is intentionally NOT used in
production so the Rego pack stays the single source of truth for policy
review, but it keeps the same Decision contract so callers never know
the difference.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel
from saap.core.types import TenantContext, ToolCall

from .chain import ComplianceViolation, Envelope

Decision = Literal["allow", "deny", "require_human"]


class PolicyInput(BaseModel, frozen=True):
    tenant_id: str
    tool_name: str
    risk_tier: str
    arguments: dict[str, Any]
    now: datetime


class PolicyGuard(Protocol):
    async def evaluate(self, tenant: TenantContext, call: ToolCall) -> Decision: ...


class OPAPolicyGuard:
    """HTTP client for a real OPA sidecar evaluating `saap.actions`
    (see policies/tenant/*.rego). One Rego document per tenant, loaded
    into OPA under `data.tenant.<tenant_id>`."""

    def __init__(self, opa_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._opa_url = opa_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=2.0)

    async def evaluate(self, tenant: TenantContext, call: ToolCall) -> Decision:
        payload = {
            "input": {
                "tool": {"name": call.tool_name, "risk_tier": call.risk_tier},
                "now": datetime.now(UTC).isoformat(),
                "tenant_id": str(tenant.tenant_id),
            }
        }
        response = await self._client.post(f"{self._opa_url}/v1/data/saap/actions", json=payload)
        response.raise_for_status()
        result = response.json().get("result", {})
        if result.get("require_human"):
            return "require_human"
        if result.get("allow"):
            return "allow"
        return "deny"


class InMemoryPolicyGuard:
    """Pure-Python restatement of the default Rego pack's three tiers,
    for tests and the no-OPA dev path:

      * read        -> always allow
      * write       -> allow only within [business_hours_start, business_hours_end)
      * high_risk   -> always require_human
    """

    def __init__(
        self,
        *,
        business_hours_start: int = 8,
        business_hours_end: int = 20,
        allowed_write_tools: frozenset[str] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._start = business_hours_start
        self._end = business_hours_end
        self._allowed_write_tools = allowed_write_tools
        self._clock = clock or _SystemClock()

    async def evaluate(self, tenant: TenantContext, call: ToolCall) -> Decision:
        if call.risk_tier == "high_risk":
            return "require_human"
        if call.risk_tier == "read":
            return "allow"
        # write
        if self._allowed_write_tools is not None and call.tool_name not in self._allowed_write_tools:
            return "deny"
        hour = self._clock.now().hour
        return "allow" if self._start <= hour < self._end else "deny"


class Clock(Protocol):
    def now(self) -> datetime: ...


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class PolicyGuardInterceptor:
    """L5 stage 3. Operates on ToolCalls carried in envelope metadata
    (set by the MCPToolkit canvas component before dispatch) rather than
    on the Message itself — PolicyGuard has nothing to say about plain
    conversational turns, only about proposed actions."""

    name = "policy_guard"

    def __init__(self, guard: PolicyGuard) -> None:
        self._guard = guard

    async def before(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        call: ToolCall | None = envelope.metadata.get("tool_call")
        if call is None:
            return envelope  # no proposed action on this turn; nothing to gate
        decision = await self._guard.evaluate(tenant, call)
        if decision == "deny":
            raise ComplianceViolation("policy_guard", f"denied: {call.tool_name}")
        return envelope.with_message(envelope.message, policy_decision=decision)

    async def after(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        return envelope
