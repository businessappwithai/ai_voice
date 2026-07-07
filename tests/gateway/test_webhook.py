import hashlib
import hmac
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from saap.core.flow import FlowRunEvent
from saap.core.types import Message, TenantContext
from saap.gateway.channels import InboundEvent
from saap.gateway.webhook import (
    StaticWebhookSecretResolver,
    WebhookAdapter,
    WebhookAuthenticationError,
    authenticate_webhook,
    verify_webhook_signature,
)


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


async def test_authenticate_webhook_succeeds_with_valid_signature(tenant: TenantContext) -> None:
    resolver = StaticWebhookSecretResolver()
    resolver.register("acme-dental", tenant, "s3cr3t")
    body = b'{"event": "form_submitted"}'
    signature = _sign("s3cr3t", body)

    resolved = await authenticate_webhook(
        resolver, claimed_tenant_id="acme-dental", body=body, signature=signature
    )

    assert resolved == tenant


async def test_authenticate_webhook_rejects_invalid_signature(tenant: TenantContext) -> None:
    resolver = StaticWebhookSecretResolver()
    resolver.register("acme-dental", tenant, "s3cr3t")
    body = b'{"event": "form_submitted"}'

    with pytest.raises(WebhookAuthenticationError, match="signature"):
        await authenticate_webhook(
            resolver, claimed_tenant_id="acme-dental", body=body, signature="sha256=deadbeef"
        )


async def test_authenticate_webhook_rejects_unknown_tenant() -> None:
    resolver = StaticWebhookSecretResolver()
    body = b"{}"

    with pytest.raises(WebhookAuthenticationError, match="unknown tenant"):
        await authenticate_webhook(
            resolver, claimed_tenant_id="ghost-tenant", body=body, signature=_sign("whatever", body)
        )


async def test_authenticate_webhook_rejects_signature_computed_over_a_different_body(
    tenant: TenantContext,
) -> None:
    resolver = StaticWebhookSecretResolver()
    resolver.register("acme-dental", tenant, "s3cr3t")
    signature = _sign("s3cr3t", b'{"event": "original"}')

    with pytest.raises(WebhookAuthenticationError):
        await authenticate_webhook(
            resolver,
            claimed_tenant_id="acme-dental",
            body=b'{"event": "tampered"}',
            signature=signature,
        )


def test_verify_webhook_signature_accepts_raw_hex_without_prefix() -> None:
    body = b"payload"
    digest = hmac.new(b"key", body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature("key", body, digest)
    assert verify_webhook_signature("key", body, f"sha256={digest}")


async def test_webhook_adapter_listen_yields_one_authenticated_event(tenant: TenantContext) -> None:
    message = Message(role="user", content="book a cleaning")
    adapter = WebhookAdapter(tenant, "session-1", message)

    events = [e async for e in adapter.listen()]

    assert events == [
        InboundEvent(tenant=tenant, channel="webhook", session_id="session-1", message=message)
    ]


async def _events(*payloads: dict[str, str]) -> AsyncIterator[FlowRunEvent]:
    for payload in payloads:
        yield FlowRunEvent(kind="final", payload=payload)


async def test_webhook_adapter_render_collects_flow_run_events(tenant: TenantContext) -> None:
    message = Message(role="user", content="book a cleaning")
    adapter = WebhookAdapter(tenant, "session-1", message)

    await adapter.render("session-1", _events({"text": "booked"}))

    assert adapter.rendered_events == [FlowRunEvent(kind="final", payload={"text": "booked"})]
