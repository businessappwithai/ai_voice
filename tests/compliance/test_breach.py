from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from saap.compliance.audit import InMemoryAuditStore
from saap.compliance.breach import (
    BREACH_NOTIFICATION_WINDOW,
    AuditChainBreachDetector,
    BreachAlert,
    InMemoryBreachAlertSink,
    VaultAccessMonitor,
)
from saap.compliance.pii import TokenVault
from saap.core.types import TenantContext


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


# --- BreachAlert clock -------------------------------------------------------


def test_notification_deadline_is_72_hours_after_detection() -> None:
    detected_at = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
    alert = BreachAlert(tenant_id="t1", kind="tamper_detected", detail="x", detected_at=detected_at)
    assert alert.notification_deadline == detected_at + BREACH_NOTIFICATION_WINDOW


def test_time_remaining_counts_down() -> None:
    detected_at = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
    alert = BreachAlert(tenant_id="t1", kind="tamper_detected", detail="x", detected_at=detected_at)
    remaining = alert.time_remaining(now=detected_at + timedelta(hours=70))
    assert remaining == timedelta(hours=2)


def test_is_overdue_false_within_window() -> None:
    detected_at = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
    alert = BreachAlert(tenant_id="t1", kind="tamper_detected", detail="x", detected_at=detected_at)
    assert not alert.is_overdue(now=detected_at + timedelta(hours=71))


def test_is_overdue_true_past_window() -> None:
    detected_at = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
    alert = BreachAlert(tenant_id="t1", kind="tamper_detected", detail="x", detected_at=detected_at)
    assert alert.is_overdue(now=detected_at + timedelta(hours=73))


# --- AuditChainBreachDetector -------------------------------------------------


async def test_detector_raises_no_alert_on_untampered_chain(tenant: TenantContext) -> None:
    store = InMemoryAuditStore()
    await store.append(tenant, "message", {"a": 1})
    sink = InMemoryBreachAlertSink()
    detector = AuditChainBreachDetector(sink)

    result = await detector.check(store, tenant)

    assert result is None
    assert sink.alerts == []


async def test_detector_raises_alert_on_tampered_chain(tenant: TenantContext) -> None:
    store = InMemoryAuditStore()
    await store.append(tenant, "message", {"a": 1})
    await store.append(tenant, "response", {"b": 2})
    rows = store._rows[str(tenant.tenant_id)]  # noqa: SLF001 - white-box tamper injection
    rows[0] = rows[0].model_copy(update={"payload": {"a": 999}})

    sink = InMemoryBreachAlertSink()
    detector = AuditChainBreachDetector(sink)

    alert = await detector.check(store, tenant)

    assert alert is not None
    assert alert.kind == "tamper_detected"
    assert sink.alerts == [alert]


# --- VaultAccessMonitor -------------------------------------------------------


async def test_monitor_does_not_alert_below_threshold(tenant: TenantContext) -> None:
    vault = TokenVault()
    token = vault.tokenize("IN_AADHAAR", "123456789012")
    sink = InMemoryBreachAlertSink()
    clock = _FakeClock()
    monitor = VaultAccessMonitor(
        vault, sink, tenant_id=str(tenant.tenant_id), threshold=3, window_seconds=60.0, clock=clock
    )

    for _ in range(3):
        await monitor.resolve(token)

    assert sink.alerts == []


async def test_monitor_alerts_once_threshold_exceeded(tenant: TenantContext) -> None:
    vault = TokenVault()
    token = vault.tokenize("IN_AADHAAR", "123456789012")
    sink = InMemoryBreachAlertSink()
    clock = _FakeClock()
    monitor = VaultAccessMonitor(
        vault, sink, tenant_id=str(tenant.tenant_id), threshold=3, window_seconds=60.0, clock=clock
    )

    for _ in range(4):
        await monitor.resolve(token)

    assert len(sink.alerts) == 1
    assert sink.alerts[0].kind == "anomalous_vault_access"


async def test_monitor_resets_window_after_calls_age_out(tenant: TenantContext) -> None:
    vault = TokenVault()
    token = vault.tokenize("IN_AADHAAR", "123456789012")
    sink = InMemoryBreachAlertSink()
    clock = _FakeClock()
    monitor = VaultAccessMonitor(
        vault, sink, tenant_id=str(tenant.tenant_id), threshold=3, window_seconds=60.0, clock=clock
    )

    for _ in range(3):
        await monitor.resolve(token)
    clock.advance(120.0)  # well past the 60s window
    await monitor.resolve(token)

    assert sink.alerts == []


async def test_monitor_still_resolves_the_real_value(tenant: TenantContext) -> None:
    vault = TokenVault()
    token = vault.tokenize("IN_AADHAAR", "123456789012")
    monitor = VaultAccessMonitor(
        vault, InMemoryBreachAlertSink(), tenant_id=str(tenant.tenant_id), threshold=100, clock=_FakeClock()
    )

    assert await monitor.resolve(token) == "123456789012"


class _FakeClock:
    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds
