"""Framework-agnostic logic behind the `ComplianceIngress` sealed
canvas component (architecture Section 5.2). The Langflow adapter in
`saap.langflow_components.compliance_ingress` is a thin wrapper over
this class; this module has no Langflow dependency so it is directly
unit-testable.
"""
from __future__ import annotations

from saap.compliance.chain import ComplianceChain, Envelope
from saap.core.types import Message, TenantContext


class ComplianceIngressLogic:
    """Mandatory first node. Runs ConsentGate -> PIIMasking ->
    PolicyGuard(no-op for plain messages) -> RateLimiter -> AuditRecorder's
    `before` phase and returns the masked envelope. Downstream canvas
    components receive only the masked `Message` — the raw payload
    never enters the graph, so no wiring mistake can leak PII to a
    model component."""

    def __init__(self, chain: ComplianceChain) -> None:
        self._chain = chain

    async def process(self, tenant: TenantContext, raw_message: Message) -> Envelope:
        envelope = Envelope(tenant, raw_message)
        return await self._chain.run_before(tenant, envelope)

    @staticmethod
    def is_refused(envelope: Envelope) -> bool:
        """Downstream components (GroundedResponder, MCPToolkit) must
        treat this as a hard stop and just pass the envelope's message
        straight to Chat Output rather than invoking a model or tool.

        Checks `envelope.metadata["violation"]` — the canonical
        envelope-level flag set by `ComplianceChain.run_before` — not
        `envelope.message.metadata["compliance_violation"]`, which is a
        separate dict scoped to the inner Message."""
        return envelope.metadata.get("violation") is not None
