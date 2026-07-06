"""RateLimiter — per-tenant, per-tool budgets (L5 stage 4).

Production backing store is Valkey (`RedisRateLimiter`, a fixed-window
counter via INCR+EXPIRE); `InMemoryRateLimiter` is the same algorithm
against a Python dict, for tests and any environment without Valkey
reachable.
"""
from __future__ import annotations

import time
from typing import Protocol

from saap.core.types import TenantContext

from .chain import ComplianceViolation, Envelope


class RateLimitBackend(Protocol):
    async def incr_and_get(self, key: str, window_seconds: int) -> int:
        """Increments the counter for `key`, creating it with a TTL of
        `window_seconds` if absent, and returns the new count."""
        ...


class InMemoryRateLimitBackend:
    def __init__(self) -> None:
        self._counts: dict[str, tuple[int, float]] = {}  # key -> (count, expires_at)

    async def incr_and_get(self, key: str, window_seconds: int) -> int:
        now = time.monotonic()
        count, expires_at = self._counts.get(key, (0, 0.0))
        if now >= expires_at:
            count, expires_at = 0, now + window_seconds
        count += 1
        self._counts[key] = (count, expires_at)
        return count


class RateLimiter:
    """L5 stage 4. Keys are `{tenant_id}:{tool_name or 'message'}`;
    budget is per-tenant unless a tool-specific override is given —
    e.g. a booking tool might get a tighter budget than plain chat."""

    name = "rate_limiter"

    def __init__(
        self,
        backend: RateLimitBackend,
        *,
        default_limit: int = 60,
        window_seconds: int = 60,
        tool_limits: dict[str, int] | None = None,
    ) -> None:
        self._backend = backend
        self._default_limit = default_limit
        self._window_seconds = window_seconds
        self._tool_limits = tool_limits or {}

    async def before(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        tool_name = envelope.metadata.get("tool_call_name", "message")
        limit = self._tool_limits.get(tool_name, self._default_limit)
        key = f"{tenant.tenant_id}:{tool_name}"
        count = await self._backend.incr_and_get(key, self._window_seconds)
        if count > limit:
            raise ComplianceViolation(
                "rate_limiter", f"budget exceeded for {tool_name}: {count} > {limit}"
            )
        return envelope

    async def after(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        return envelope
