"""Breach detection and the 72-hour DPDP notification clock (Phase 3
Epic 3.3).

A real deployment wires Grafana/Prometheus alert rules on anomalous
vault access and audit-chain anomalies, which POST to a webhook that
dispatches an incident-response Langflow flow via FlowScheduler
(Epic 4.3) to assemble the notification dossier — that flow-JSON+PDF
piece isn't built here (see the README's note on vertical-pack
authoring). This module is the receiving end and the two concrete,
mechanically-detectable signals this codebase can raise without an
external anomaly-detection model:

  * audit-chain tamper — `InMemoryAuditStore.verify_chain` already
    raises `TamperDetected` on any hash-chain mismatch; that mismatch
    IS the anomaly, no heuristic needed.
  * anomalous vault access — a fixed-window rate threshold over
    `TokenVault.resolve` calls, the same signal a real Prometheus
    alert rule would fire on, exported as a counter instead.

`BreachAlert.notification_deadline` is `detected_at + 72h` (DPDP
Section 8(6)) — the clock a real incident dashboard counts down.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from saap.core.types import TenantContext

from .audit import InMemoryAuditStore, TamperDetected
from .pii import TokenVault

BREACH_NOTIFICATION_WINDOW = timedelta(hours=72)


class BreachAlert(BaseModel, frozen=True):
    alert_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    kind: str  # "tamper_detected" | "anomalous_vault_access"
    detail: str
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def notification_deadline(self) -> datetime:
        return self.detected_at + BREACH_NOTIFICATION_WINDOW

    def time_remaining(self, *, now: datetime | None = None) -> timedelta:
        return self.notification_deadline - (now or datetime.now(UTC))

    def is_overdue(self, *, now: datetime | None = None) -> bool:
        return self.time_remaining(now=now) <= timedelta(0)


class BreachAlertSink(Protocol):
    """Where a raised `BreachAlert` goes. A real binding dispatches to
    FlowScheduler to fire the incident-response flow;
    `InMemoryBreachAlertSink` just records it, for tests and any
    environment without that wired up yet."""

    async def raise_alert(self, alert: BreachAlert) -> None: ...


class InMemoryBreachAlertSink:
    def __init__(self) -> None:
        self.alerts: list[BreachAlert] = []

    async def raise_alert(self, alert: BreachAlert) -> None:
        self.alerts.append(alert)


class AuditChainBreachDetector:
    """Runs `AuditStore.verify_chain` and turns a `TamperDetected` into
    a `BreachAlert` — the clock-starting event for a real tamper
    incident, not just a caught exception."""

    def __init__(self, sink: BreachAlertSink) -> None:
        self._sink = sink

    async def check(self, store: InMemoryAuditStore, tenant: TenantContext) -> BreachAlert | None:
        try:
            store.verify_chain(tenant)
        except TamperDetected as exc:
            alert = BreachAlert(
                tenant_id=str(tenant.tenant_id), kind="tamper_detected", detail=str(exc)
            )
            await self._sink.raise_alert(alert)
            return alert
        return None


class VaultAccessMonitor:
    """Wraps `TokenVault.resolve` with a fixed-window rate threshold —
    the "anomalous vault access" alert source. A real deployment's
    Prometheus alert rule fires on the same underlying signal
    (resolve-call rate) exported as a metric; this is the same
    threshold logic in-process, for environments without that stack
    wired up yet."""

    def __init__(
        self,
        vault: TokenVault,
        sink: BreachAlertSink,
        *,
        tenant_id: str,
        threshold: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._vault = vault
        self._sink = sink
        self._tenant_id = tenant_id
        self._threshold = threshold
        self._window_seconds = window_seconds
        self._clock = clock or _monotonic
        self._recent_calls: list[float] = []

    async def resolve(self, token: str) -> str | None:
        now = self._clock()
        self._recent_calls = [t for t in self._recent_calls if now - t < self._window_seconds]
        self._recent_calls.append(now)
        value = self._vault.resolve(token)
        if len(self._recent_calls) > self._threshold:
            alert = BreachAlert(
                tenant_id=self._tenant_id,
                kind="anomalous_vault_access",
                detail=(
                    f"{len(self._recent_calls)} vault resolves within "
                    f"{self._window_seconds}s (threshold {self._threshold})"
                ),
            )
            await self._sink.raise_alert(alert)
        return value


def _monotonic() -> float:
    import time

    return time.monotonic()
