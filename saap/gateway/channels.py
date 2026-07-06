"""Channel adapters normalize every entry point (web chat, SIP call,
webhook, email, WhatsApp bridge) into a single `InboundEvent` and
render `FlowRunEvent` streams back out. Adding a channel never touches
agents or compliance code (P3).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from pydantic import BaseModel
from saap.core.flow import FlowRunEvent
from saap.core.types import Message, TenantContext


class InboundEvent(BaseModel, frozen=True):
    """Channel-agnostic envelope entering the compliance chain (L5)."""

    tenant: TenantContext
    channel: str  # "webchat" | "sip" | "webhook" | ...
    session_id: str  # channel-scoped conversation key
    message: Message
    raw_ref: str | None = None  # minio:// pointer to original payload


class ChannelAdapter(Protocol):
    """Implementations: ``WebChatAdapter`` (FastAPI WebSocket),
    ``VoiceSessionAdapter`` (LiveKit, Phase 2), ``WebhookAdapter``
    (signed HMAC ingress for client systems), ``EmailAdapter``
    (IMAP/JMAP poll), ``MatrixWhatsAppAdapter`` (open-source mautrix
    bridge, Phase 4).

    Contract:
      * `listen` yields InboundEvents; the adapter is responsible for
        channel auth (widget JWT, SIP trunk ACL, HMAC verification)
        BEFORE constructing a TenantContext — an unauthenticated payload
        must never obtain one.
      * `render` maps FlowRunEvents to channel semantics: tokens -> SSE
        deltas for web, sentences -> TTS for voice, final -> templated
        reply for email.
    """

    channel: str

    def listen(self) -> AsyncIterator[InboundEvent]: ...

    async def render(self, session_id: str, events: AsyncIterator[FlowRunEvent]) -> None: ...
