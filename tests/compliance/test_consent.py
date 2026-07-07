from uuid import uuid4

import pytest
from saap.compliance.chain import ComplianceViolation, Envelope
from saap.compliance.consent import ConsentGate, StaticConsentRegistry
from saap.core.types import Message, TenantContext


async def test_fails_closed_without_grant() -> None:
    tenant = TenantContext(tenant_id=uuid4(), vertical="dental")  # no consent_scope granted
    gate = ConsentGate(StaticConsentRegistry())
    envelope = Envelope(tenant, Message(role="user", content="hi"))
    with pytest.raises(ComplianceViolation):
        await gate.before(tenant, envelope)


async def test_allows_when_purpose_granted() -> None:
    tenant = TenantContext(
        tenant_id=uuid4(), vertical="dental", consent_scope=frozenset({"service"})
    )
    gate = ConsentGate(StaticConsentRegistry())
    envelope = Envelope(tenant, Message(role="user", content="hi"))
    result = await gate.before(tenant, envelope)
    assert result is envelope


async def test_checks_explicit_purpose_from_metadata() -> None:
    tenant = TenantContext(
        tenant_id=uuid4(), vertical="dental", consent_scope=frozenset({"service"})
    )
    gate = ConsentGate(StaticConsentRegistry())
    envelope = Envelope(tenant, Message(role="user", content="hi"), {"purpose": "marketing"})
    with pytest.raises(ComplianceViolation):
        await gate.before(tenant, envelope)
