"""LagoUsageEventSink — UsageEventSink backed by the official
`lago-python-client` (MIT; verified via `pip show`/the wheel's bundled
LICENSE — pure Python, no bundled binaries, no entanglement risk).

Verified against the real installed package (v1.49.0):
`lago_python_client.events.clients.EventClient.create(self,
input_object: BaseModel, timeout=None) -> Optional[EventResponse]` and
`lago_python_client.models.event.Event`'s real fields (transaction_id,
external_subscription_id, code, timestamp, precise_total_amount_cents,
properties) — but `EventClient.create` is a *synchronous* call (plain
httpx, not `httpx.AsyncClient`), bridged here via `run_in_executor` so
it never blocks the event loop, and this has NEVER been exercised
against a live Lago instance (no network path to one in this
sandbox) — tested only against `LagoEventClientProtocol`, a fake
matching that verified real signature.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from lago_python_client.events.clients import EventClient
from lago_python_client.models.event import Event
from saap.core.billing import UsageEvent
from saap.core.registry import PluginRegistry


class LagoEventClientProtocol(Protocol):
    """Narrowed to the one real `EventClient` method this adapter
    calls, so tests inject a fake without needing a real `httpx`
    transport."""

    def create(self, input_object: Event, timeout: object = None) -> object: ...


class LagoUsageEventSink:
    def __init__(
        self,
        client: LagoEventClientProtocol | EventClient,
        *,
        subscription_resolver: Callable[[UUID], str],
    ) -> None:
        """`subscription_resolver` maps a SAAP tenant id to the
        `external_subscription_id` Lago expects — that mapping lives in
        the tenant blueprint/provisioner (Epic 4.1), not here."""
        self._client = client
        self._subscription_resolver = subscription_resolver

    async def emit(self, event: UsageEvent) -> None:
        lago_event = Event(
            transaction_id=event.transaction_id,
            external_subscription_id=self._subscription_resolver(event.tenant_id),
            code=event.metric_code,
            timestamp=int(event.occurred_at.timestamp()),
            precise_total_amount_cents=None,
            properties={"quantity": event.quantity},
        )
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._client.create, lago_event)


def register(registry: PluginRegistry) -> None:
    raise NotImplementedError(
        "no LagoUsageEventSink factory is wired yet — construct one directly with "
        "lago_python_client.client.Client(api_key=..., api_url=...).events and a "
        "tenant_id -> external_subscription_id resolver from your tenant provisioner. "
        "Not auto-wired here because doing so would require a Lago API key/URL this "
        "sandbox has no way to provision or verify against."
    )
