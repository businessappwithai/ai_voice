"""WebhookAdapter — HMAC-signed ingress channel (Phase 4 Epic 4.5).

For client systems (CRM automations, third-party forms, inbound SMS
providers) that POST events directly rather than going through the
chat widget or a phone call. Per the `ChannelAdapter` contract, auth
happens BEFORE a `TenantContext` is constructed: `authenticate_webhook`
looks up the claimed tenant's shared secret and verifies the request
signature against it, and only a caller holding a verified `TenantContext`
can build a `WebhookAdapter` at all — there's no path from an
unauthenticated payload to one.

A webhook POST is one request/response, not a long-lived connection
like the WebSocket chat channel, so `WebhookAdapter` is a one-shot,
per-request instance: `listen()` yields exactly the one already-
authenticated `InboundEvent`, and `render()` collects the resulting
`FlowRunEvent`s into `rendered_events` for the route handler to fold
into a single JSON HTTP response.
"""
from __future__ import annotations

import hashlib
import hmac
from collections.abc import AsyncIterator
from typing import Protocol

from saap.core.flow import FlowRunEvent
from saap.core.types import Message, TenantContext

from .channels import InboundEvent


class WebhookAuthenticationError(Exception):
    pass


class WebhookSecretResolver(Protocol):
    """Resolves a claimed tenant id to its `TenantContext` and HMAC
    shared secret in one lookup — resolved from the platform's own
    tenant registry, never trusted from the request payload itself, so
    a forged `tenant_id` can't be used to fetch its own secret and pass
    verification against itself."""

    async def resolve(self, claimed_tenant_id: str) -> tuple[TenantContext, str] | None: ...


class StaticWebhookSecretResolver:
    """In-memory `tenant_id -> (TenantContext, secret)` map. Tests and
    dev/CI only; production resolves against the tenant blueprint
    registry (Phase 4 Epic 4.1) instead."""

    def __init__(self, registrations: dict[str, tuple[TenantContext, str]] | None = None) -> None:
        self._registrations = dict(registrations or {})

    def register(self, claimed_tenant_id: str, tenant: TenantContext, secret: str) -> None:
        self._registrations[claimed_tenant_id] = (tenant, secret)

    async def resolve(self, claimed_tenant_id: str) -> tuple[TenantContext, str] | None:
        return self._registrations.get(claimed_tenant_id)


def verify_webhook_signature(secret: str, body: bytes, signature: str) -> bool:
    """Constant-time HMAC-SHA256 check against a `sha256=<hex>` header
    (the GitHub/Stripe webhook signing convention)."""
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    provided = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


async def authenticate_webhook(
    resolver: WebhookSecretResolver, *, claimed_tenant_id: str, body: bytes, signature: str
) -> TenantContext:
    resolved = await resolver.resolve(claimed_tenant_id)
    if resolved is None:
        raise WebhookAuthenticationError(f"unknown tenant {claimed_tenant_id!r}")
    tenant, secret = resolved
    if not verify_webhook_signature(secret, body, signature):
        raise WebhookAuthenticationError("HMAC signature verification failed")
    return tenant


class WebhookAdapter:
    channel = "webhook"

    def __init__(self, tenant: TenantContext, session_id: str, message: Message) -> None:
        self._tenant = tenant
        self._session_id = session_id
        self._message = message
        self.rendered_events: list[FlowRunEvent] = []

    async def listen(self) -> AsyncIterator[InboundEvent]:
        yield InboundEvent(
            tenant=self._tenant,
            channel=self.channel,
            session_id=self._session_id,
            message=self._message,
        )

    async def render(self, session_id: str, events: AsyncIterator[FlowRunEvent]) -> None:
        async for event in events:
            self.rendered_events.append(event)
