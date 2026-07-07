import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from nio import MatrixRoom, RoomMessageText
from saap.core.flow import FlowRunEvent
from saap.core.types import TenantContext
from saap.gateway.matrix_whatsapp import MatrixWhatsAppAdapter, StaticRoomTenantResolver

OWN_USER_ID = "@saap-bot:example.org"


class FakeMatrixClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict[str, Any]]] = []
        self._callback: Any = None

    def add_event_callback(self, callback: Any, event_filter: Any) -> None:
        self._callback = callback

    async def room_send(
        self, room_id: str, message_type: str, content: dict[str, Any], tx_id: str | None = None
    ) -> None:
        self.sent.append((room_id, message_type, content))

    async def simulate_incoming(self, room: MatrixRoom, event: RoomMessageText) -> None:
        assert self._callback is not None, "listen() must be called before simulating events"
        await self._callback(room, event)


def _room(room_id: str) -> MatrixRoom:
    return MatrixRoom(room_id, OWN_USER_ID)


def _text_event(sender: str, body: str) -> RoomMessageText:
    return RoomMessageText.from_dict(
        {
            "event_id": f"$evt-{uuid4()}",
            "sender": sender,
            "origin_server_ts": 123456789,
            "content": {"msgtype": "m.text", "body": body},
        }
    )


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


async def _events(*payloads: dict[str, str]) -> AsyncIterator[FlowRunEvent]:
    for payload in payloads:
        yield FlowRunEvent(kind="final", payload=payload)


async def test_listen_yields_inbound_event_for_a_mapped_room(tenant: TenantContext) -> None:
    room_id = "!room1:example.org"
    resolver = StaticRoomTenantResolver({room_id: tenant})
    client = FakeMatrixClient()
    adapter = MatrixWhatsAppAdapter(client, resolver, own_user_id=OWN_USER_ID)

    agen = adapter.listen()
    started = asyncio.ensure_future(agen.__anext__())
    await asyncio.sleep(0)  # let listen() register the callback before we simulate
    await client.simulate_incoming(_room(room_id), _text_event("@customer:example.org", "book a cleaning"))

    inbound = await started
    assert inbound.tenant == tenant
    assert inbound.channel == "whatsapp"
    assert inbound.session_id == room_id
    assert inbound.message.role == "user"
    assert inbound.message.content == "book a cleaning"


async def test_listen_ignores_messages_from_unrecognized_rooms(tenant: TenantContext) -> None:
    resolver = StaticRoomTenantResolver({"!known:example.org": tenant})
    client = FakeMatrixClient()
    adapter = MatrixWhatsAppAdapter(client, resolver, own_user_id=OWN_USER_ID)

    agen = adapter.listen()
    started = asyncio.ensure_future(agen.__anext__())
    await asyncio.sleep(0)
    await client.simulate_incoming(
        _room("!unknown:example.org"), _text_event("@customer:example.org", "hi")
    )
    await client.simulate_incoming(
        _room("!known:example.org"), _text_event("@customer:example.org", "hi from known room")
    )

    inbound = await started
    assert inbound.session_id == "!known:example.org"
    assert inbound.message.content == "hi from known room"


async def test_listen_ignores_the_bots_own_echoed_messages(tenant: TenantContext) -> None:
    room_id = "!room1:example.org"
    resolver = StaticRoomTenantResolver({room_id: tenant})
    client = FakeMatrixClient()
    adapter = MatrixWhatsAppAdapter(client, resolver, own_user_id=OWN_USER_ID)

    agen = adapter.listen()
    started = asyncio.ensure_future(agen.__anext__())
    await asyncio.sleep(0)
    await client.simulate_incoming(_room(room_id), _text_event(OWN_USER_ID, "our own reply"))
    await client.simulate_incoming(_room(room_id), _text_event("@customer:example.org", "real message"))

    inbound = await started
    assert inbound.message.content == "real message"


async def test_render_sends_final_events_as_text_messages() -> None:
    resolver = StaticRoomTenantResolver()
    client = FakeMatrixClient()
    adapter = MatrixWhatsAppAdapter(client, resolver, own_user_id=OWN_USER_ID)

    await adapter.render("!room1:example.org", _events({"text": "your slot is confirmed"}))

    assert client.sent == [
        ("!room1:example.org", "m.room.message", {"msgtype": "m.text", "body": "your slot is confirmed"})
    ]


async def test_render_skips_non_final_events() -> None:
    resolver = StaticRoomTenantResolver()
    client = FakeMatrixClient()
    adapter = MatrixWhatsAppAdapter(client, resolver, own_user_id=OWN_USER_ID)

    async def mixed_events() -> AsyncIterator[FlowRunEvent]:
        yield FlowRunEvent(kind="token", payload={"text": "partial"})
        yield FlowRunEvent(kind="final", payload={"text": "done"})

    await adapter.render("!room1:example.org", mixed_events())

    assert client.sent == [("!room1:example.org", "m.room.message", {"msgtype": "m.text", "body": "done"})]
