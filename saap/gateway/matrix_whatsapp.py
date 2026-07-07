"""MatrixWhatsAppAdapter — ChannelAdapter over a Matrix homeserver
bridged to WhatsApp via mautrix-whatsapp (Phase 4 Epic 4.5).

Verified against the real, installed `matrix-nio` client (v0.25.2,
ISC licensed): `AsyncClient.room_send(room_id, message_type, content,
tx_id=None)` and `AsyncClient.add_event_callback(callback, filter)`
(callback receives `(MatrixRoom, Event)`, and nio's own sync loop
constructs real `RoomMessageText` instances via
`RoomMessageText.from_dict(...)`, which this module's tests use
directly rather than a hand-rolled stand-in). Never exercised against
a real Matrix homeserver or mautrix-whatsapp bridge — no network path
to one in this sandbox — so this is tested only against a fake
`AsyncClient` matching that verified real signature, the same rigor
tier as `FasterWhisperSTT`.

Per the `ChannelAdapter` contract, auth happens before any
`TenantContext` is trusted: `RoomTenantResolver.resolve` maps an
inbound Matrix room id to a tenant, and an unrecognized room never
produces an `InboundEvent` — there's no path from an unmapped room to
a constructed `TenantContext`.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Protocol

from saap.core.flow import FlowRunEvent
from saap.core.types import Message, TenantContext

from .channels import InboundEvent


class MatrixRoomEvent(Protocol):
    sender: str
    body: str
    event_id: str


class MatrixRoomProtocol(Protocol):
    room_id: str


class MatrixClientProtocol(Protocol):
    """Narrowed to the two real `nio.AsyncClient` methods this adapter
    calls, so tests inject a fake without needing a real homeserver
    connection."""

    async def room_send(
        self, room_id: str, message_type: str, content: dict[str, Any], tx_id: str | None = None
    ) -> object: ...

    def add_event_callback(
        self,
        callback: Callable[[MatrixRoomProtocol, MatrixRoomEvent], Awaitable[None] | None],
        event_filter: Any,
    ) -> None: ...


class RoomTenantResolver(Protocol):
    async def resolve(self, room_id: str) -> TenantContext | None: ...


class StaticRoomTenantResolver:
    """In-memory `room_id -> TenantContext` map. Tests and dev/CI only;
    production resolves against the tenant blueprint registry
    (Epic 4.1) instead."""

    def __init__(self, rooms: dict[str, TenantContext] | None = None) -> None:
        self._rooms = dict(rooms or {})

    def register(self, room_id: str, tenant: TenantContext) -> None:
        self._rooms[room_id] = tenant

    async def resolve(self, room_id: str) -> TenantContext | None:
        return self._rooms.get(room_id)


class MatrixWhatsAppAdapter:
    channel = "whatsapp"

    def __init__(
        self,
        client: MatrixClientProtocol,
        resolver: RoomTenantResolver,
        *,
        own_user_id: str,
        event_filter: Any = None,
    ) -> None:
        self._client = client
        self._resolver = resolver
        self._own_user_id = own_user_id
        self._event_filter = event_filter
        self._queue: asyncio.Queue[InboundEvent] = asyncio.Queue()

    async def _on_message(self, room: MatrixRoomProtocol, event: MatrixRoomEvent) -> None:
        if event.sender == self._own_user_id:
            return  # ignore our own echoed messages, never re-process them as inbound
        tenant = await self._resolver.resolve(room.room_id)
        if tenant is None:
            return  # unrecognized room: never construct a TenantContext for it
        await self._queue.put(
            InboundEvent(
                tenant=tenant,
                channel=self.channel,
                session_id=room.room_id,
                message=Message(role="user", content=event.body),
            )
        )

    async def listen(self) -> AsyncIterator[InboundEvent]:
        self._client.add_event_callback(self._on_message, self._event_filter)
        while True:
            yield await self._queue.get()

    async def render(self, session_id: str, events: AsyncIterator[FlowRunEvent]) -> None:
        async for event in events:
            if event.kind != "final":
                continue
            text = event.payload.get("text")
            if text:
                await self._client.room_send(
                    session_id, "m.room.message", {"msgtype": "m.text", "body": text}
                )
