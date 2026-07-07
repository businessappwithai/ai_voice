"""Ordered, non-bypassable interceptor chain (P6).

Order matters and is fixed by ComplianceChain, not by caller convention:

  1. ConsentGate        — fail closed if purpose not in consent_scope
  2. PIIMasking         — Presidio detect -> reversible tokenization
  3. PolicyGuard        — OPA/Rego per-tenant action policy
  4. RateLimiter        — per-tenant, per-tool budgets (Valkey)
  5. AuditRecorder      — append-only, hash-chained event log

`before()` interceptors run in list order on the way in; `after()`
interceptors run in *reverse* order on the way out, mirroring a
middleware stack. Any interceptor may raise ComplianceViolation, which
short-circuits to a safe, audited refusal — never a stack trace to the
caller.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from saap.core.types import Message, TenantContext


class ComplianceViolation(Exception):
    """Raised by any interceptor to short-circuit the chain. Carries a
    caller-safe `reason` (never includes raw PII) and the interceptor
    that raised it, for audit logging."""

    def __init__(self, interceptor: str, reason: str) -> None:
        self.interceptor = interceptor
        self.reason = reason
        super().__init__(f"{interceptor}: {reason}")


class Envelope:
    """Mutable-by-replacement carrier passed through the chain.

    Each interceptor receives the current envelope and returns a new
    one (frozen `Message` inside means the interceptor cannot mutate
    the original in place — it must construct a new Message, which is
    what keeps every transformation auditable as a distinct object).
    """

    __slots__ = ("tenant", "message", "metadata")

    def __init__(
        self,
        tenant: TenantContext,
        message: Message,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.tenant = tenant
        self.message = message
        self.metadata: dict[str, Any] = dict(metadata or {})

    def with_message(self, message: Message, **extra_metadata: Any) -> Envelope:
        merged = {**self.metadata, **extra_metadata}
        return Envelope(self.tenant, message, merged)


class Interceptor(Protocol):
    name: str

    async def before(self, tenant: TenantContext, envelope: Envelope) -> Envelope: ...

    async def after(self, tenant: TenantContext, envelope: Envelope) -> Envelope: ...


InnerCall = Callable[[TenantContext, Envelope], Awaitable[Envelope]]


class ComplianceChain:
    """Composes interceptors in the fixed order required by P6.

    `wrap(tenant, envelope, inner)`:
        before[0] -> before[1] -> ... -> inner() -> ...after[1] -> after[0]

    A ComplianceViolation raised by any `before` stage skips `inner()`
    entirely and unwinds only through the `after` stages of interceptors
    that already ran — each interceptor's `after` MUST tolerate being
    called after a violation (e.g. AuditRecorder still writes the
    refusal row).
    """

    def __init__(self, interceptors: Sequence[Interceptor]) -> None:
        if not interceptors:
            raise ValueError("ComplianceChain requires at least one interceptor")
        self._interceptors = list(interceptors)

    @property
    def interceptor_names(self) -> tuple[str, ...]:
        return tuple(i.name for i in self._interceptors)

    async def wrap(
        self, tenant: TenantContext, envelope: Envelope, inner: InnerCall
    ) -> Envelope:
        ran: list[Interceptor] = []
        try:
            for interceptor in self._interceptors:
                envelope = await interceptor.before(tenant, envelope)
                ran.append(interceptor)
            envelope = await inner(tenant, envelope)
        except ComplianceViolation as violation:
            envelope = envelope.with_message(
                Message(
                    role="assistant",
                    content=self._safe_refusal_text(violation),
                    metadata={"compliance_violation": violation.interceptor},
                ),
                violation=violation.interceptor,
            )
            for interceptor in reversed(ran):
                envelope = await interceptor.after(tenant, envelope)
            return envelope

        for interceptor in reversed(ran):
            envelope = await interceptor.after(tenant, envelope)
        return envelope

    async def run_before(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        """Two-phase variant of `wrap` for callers that can't hold a
        Python call stack across the "inner" step — namely the Langflow
        canvas, where `ComplianceIngress` (this phase) and `AuditClose`
        (`run_after`, below) are two separate graph nodes, not nested
        function calls. Which interceptors actually ran is threaded
        through envelope metadata (`_ran_interceptors`) so `run_after`
        can mirror `wrap`'s exact short-circuit semantics: only
        interceptors whose `before` executed get their `after` called.

        On a ComplianceViolation, returns immediately with the same safe
        refusal message `wrap` would produce, rather than raising — a
        canvas node has no exception channel to the rest of the graph,
        only an output message. Downstream components (GroundedResponder,
        MCPToolkit) must treat `metadata["compliance_violation"]` as a
        hard stop, same as `RuntimeRefused` is for the gateway path.
        """
        ran: list[str] = []
        try:
            for interceptor in self._interceptors:
                envelope = await interceptor.before(tenant, envelope)
                ran.append(interceptor.name)
        except ComplianceViolation as violation:
            return envelope.with_message(
                Message(
                    role="assistant",
                    content=self._safe_refusal_text(violation),
                    metadata={"compliance_violation": violation.interceptor},
                ),
                violation=violation.interceptor,
                _ran_interceptors=ran,
            )
        return envelope.with_message(envelope.message, _ran_interceptors=ran)

    async def run_after(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        """Companion to `run_before`; called by `AuditClose`. Runs
        `after()` in reverse order for exactly the interceptors recorded
        by `run_before` in `_ran_interceptors` — interceptors whose
        `before` never executed (because an earlier one short-circuited)
        never see this envelope's `after` either, matching `wrap`."""
        ran_names: list[str] = envelope.metadata.get("_ran_interceptors", [])
        by_name = {i.name: i for i in self._interceptors}
        for name in reversed(ran_names):
            interceptor = by_name.get(name)
            if interceptor is not None:
                envelope = await interceptor.after(tenant, envelope)
        return envelope

    @staticmethod
    def _safe_refusal_text(violation: ComplianceViolation) -> str:
        # Deliberately generic — the real reason lives in the audit row,
        # never echoed back to an end user (avoids leaking policy internals
        # or confirming/denying sensitive data existence).
        return "I'm not able to help with that request."
