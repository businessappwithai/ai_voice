"""Framework-agnostic logic behind the `AuditClose` sealed canvas
component — terminal node of every flow, pairing with `ComplianceIngress`
via `ComplianceChain.run_after` (see saap.compliance.chain for why the
chain is split into two phases for the canvas)."""
from __future__ import annotations

from saap.compliance.chain import ComplianceChain, Envelope
from saap.core.types import TenantContext


class AuditCloseLogic:
    def __init__(self, chain: ComplianceChain) -> None:
        self._chain = chain

    async def close(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        return await self._chain.run_after(tenant, envelope)
