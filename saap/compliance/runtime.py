"""InterceptedRuntime — the only handle channel adapters (L6) ever see.

Wraps an Orchestrator so that every inbound message traverses the L5
chain before reaching L4, and exposes no attribute that would let a
caller reach the raw Orchestrator or MCPClientPool directly. This is
the P6 enforcement point: `saap.gateway` imports `InterceptedRuntime`,
never `saap.core.flow.Orchestrator` — checked by an import-linter
contract in CI (tools/license_gate's sibling contract, see
tools/flow_linter for the flow-side half of this guarantee).
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from saap.core.flow import ApprovalDecision, FlowRef, FlowRunEvent, Orchestrator
from saap.core.types import Message, TenantContext

from .chain import ComplianceChain, Envelope


class RuntimeRefused(Exception):
    """Raised by `InterceptedRuntime.start` when the compliance chain
    short-circuited before reaching the orchestrator (a ConsentGate
    denial, a rate-limit trip, etc.). Carries the safe, generic refusal
    text the channel adapter should render directly — there is no
    run_id and nothing to stream because the flow never ran."""

    def __init__(self, refusal_text: str) -> None:
        self.refusal_text = refusal_text
        super().__init__(refusal_text)


class InterceptedRuntime:
    def __init__(self, chain: ComplianceChain, orchestrator: Orchestrator) -> None:
        self._chain = chain
        self._orchestrator = orchestrator

    async def start(
        self,
        tenant: TenantContext,
        flow: FlowRef,
        message: Message,
        session_id: str,
        *,
        purpose: str = "service",
    ) -> str:
        envelope = Envelope(tenant, message, {"purpose": purpose})

        async def inner(t: TenantContext, env: Envelope) -> Envelope:
            run_id = await self._orchestrator.start(t, flow, env.message, session_id)
            return env.with_message(env.message, run_id=run_id)

        result = await self._chain.wrap(tenant, envelope, inner)
        run_id = result.metadata.get("run_id")
        if run_id is None:
            raise RuntimeRefused(result.message.content)
        return str(run_id)

    def events(self, run_id: str) -> AsyncIterator[FlowRunEvent]:
        return self._orchestrator.events(run_id)

    async def resume(self, request_id: str, decision: ApprovalDecision) -> None:
        await self._orchestrator.resume(request_id, decision)

    async def cancel(self, run_id: str) -> None:
        await self._orchestrator.cancel(run_id)
