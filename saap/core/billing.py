"""Usage metering contracts (Phase 4 Epic 4.4): per-tenant minutes,
tokens, and tool calls flow from Langfuse/Prometheus exporters into a
`UsageEventSink` for metered billing with agency markup.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field


class UsageEvent(BaseModel, frozen=True):
    tenant_id: UUID
    metric_code: str  # "voice_minutes" | "llm_tokens" | "tool_calls" | ...
    quantity: float
    transaction_id: str  # idempotency key — re-sending the same id must not double-bill
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UsageEventSink(Protocol):
    """Implementations: ``LagoUsageEventSink`` (saap.plugins.billing.lago).
    `emit` must be safe to call more than once with the same
    `transaction_id` (exporters retry on timeout) without double-billing —
    the sink, not the caller, is responsible for that idempotency."""

    async def emit(self, event: UsageEvent) -> None: ...
