"""Lightweight internal event bus (Valkey streams; NATS adapter optional)
decoupling side-concerns from the hot path: audit fan-out, usage
metering for billing, CRM activity logging, and analytics all
subscribe — the agent loop never blocks on them.

`consent.revoked` deserves note: its subscriber deletes the principal's
`campaign_enrollments` rows (halting all future scheduled flow runs),
cancels any pending ApprovalRequests, and enqueues an erasure job —
revocation propagates through the whole system from one event.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field


class DomainEvent(BaseModel, frozen=True):
    kind: str  # "call.completed" | "tool.executed" | "consent.revoked" ...
    tenant_id: str
    payload: dict[str, Any]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EventBus(Protocol):
    async def publish(self, event: DomainEvent) -> None: ...

    def subscribe(self, kinds: Sequence[str]) -> AsyncIterator[DomainEvent]: ...


# Well-known event kinds referenced elsewhere in the codebase (compliance
# chain, scheduler, tenancy). Kept as plain strings rather than an enum
# so plugins can publish new kinds without a core change (P3) — this
# list is documentation, not an exhaustive registry.
CONSENT_REVOKED = "consent.revoked"
TOOL_EXECUTED = "tool.executed"
CALL_COMPLETED = "call.completed"
APPROVAL_REQUESTED = "approval.requested"
APPROVAL_DECIDED = "approval.decided"
ERASURE_COMPLETED = "erasure.completed"
