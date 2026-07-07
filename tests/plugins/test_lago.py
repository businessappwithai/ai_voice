from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from lago_python_client.models.event import Event
from saap.core.billing import UsageEvent
from saap.core.registry import PluginRegistry
from saap.plugins.billing.lago import LagoUsageEventSink, register


class FakeLagoEventClient:
    def __init__(self) -> None:
        self.calls: list[Event] = []

    def create(self, input_object: Event, timeout: object = None) -> None:
        self.calls.append(input_object)


async def test_emit_builds_a_real_lago_event_with_expected_fields() -> None:
    tenant_id = uuid4()
    client = FakeLagoEventClient()
    sink = LagoUsageEventSink(client, subscription_resolver=lambda t: f"sub-{t}")
    occurred_at = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
    event = UsageEvent(
        tenant_id=tenant_id,
        metric_code="voice_minutes",
        quantity=4.5,
        transaction_id="txn-1",
        occurred_at=occurred_at,
    )

    await sink.emit(event)

    assert len(client.calls) == 1
    sent = client.calls[0]
    assert isinstance(sent, Event)
    assert sent.transaction_id == "txn-1"
    assert sent.external_subscription_id == f"sub-{tenant_id}"
    assert sent.code == "voice_minutes"
    # lago_python_client.models.event.Event.timestamp is typed
    # Union[str, int, None] with str listed first, so pydantic v1's
    # union coercion always stores it as a str, even though this
    # adapter passes an int — verified against the real installed
    # model rather than assumed.
    assert sent.timestamp == str(int(occurred_at.timestamp()))
    assert sent.properties == {"quantity": 4.5}


async def test_emit_uses_the_subscription_resolver_per_tenant() -> None:
    resolved: list[UUID] = []

    def resolver(tenant_id: UUID) -> str:
        resolved.append(tenant_id)
        return "external-sub-123"

    tenant_id = uuid4()
    client = FakeLagoEventClient()
    sink = LagoUsageEventSink(client, subscription_resolver=resolver)
    event = UsageEvent(tenant_id=tenant_id, metric_code="llm_tokens", quantity=100, transaction_id="txn-2")

    await sink.emit(event)

    assert resolved == [tenant_id]
    assert client.calls[0].external_subscription_id == "external-sub-123"


def test_register_raises_not_implemented() -> None:
    registry = PluginRegistry()
    with pytest.raises(NotImplementedError, match="LagoUsageEventSink"):
        register(registry)
