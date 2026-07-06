"""WebChatAdapter — WebSocket channel for the embeddable chat widget
(Phase 1 Epic 1.6). One adapter instance per live connection.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import WebSocket
from saap.core.flow import FlowRunEvent
from saap.core.types import Message, TenantContext

from .channels import InboundEvent


class WebChatAdapter:
    channel = "webchat"

    def __init__(self, websocket: WebSocket, tenant: TenantContext, session_id: str) -> None:
        self._ws = websocket
        self._tenant = tenant
        self._session_id = session_id

    async def listen(self) -> AsyncIterator[InboundEvent]:
        while True:
            data = await self._ws.receive_json()
            content = (data.get("content") or "").strip()
            if not content:
                continue
            yield InboundEvent(
                tenant=self._tenant,
                channel=self.channel,
                session_id=self._session_id,
                message=Message(role="user", content=content),
            )

    async def render(self, session_id: str, events: AsyncIterator[FlowRunEvent]) -> None:
        async for event in events:
            await self._ws.send_json({"kind": event.kind, "payload": event.payload})

    async def render_refusal(self, refusal_text: str) -> None:
        await self._ws.send_json({"kind": "final", "payload": {"text": refusal_text}})
