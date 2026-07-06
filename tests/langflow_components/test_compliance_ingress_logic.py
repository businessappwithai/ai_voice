from uuid import uuid4

import pytest
from saap.compliance.chain import ComplianceChain, ComplianceViolation
from saap.core.types import Message, TenantContext
from saap.langflow_components.logic.compliance_ingress import ComplianceIngressLogic


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental", consent_scope=frozenset({"service"}))


class AllowInterceptor:
    name = "allow"

    async def before(self, tenant, envelope):  # noqa: ANN001
        return envelope

    async def after(self, tenant, envelope):  # noqa: ANN001
        return envelope


class DenyInterceptor:
    name = "deny"

    async def before(self, tenant, envelope):  # noqa: ANN001
        raise ComplianceViolation("deny", "test denial")

    async def after(self, tenant, envelope):  # noqa: ANN001
        return envelope


async def test_process_returns_masked_envelope_when_allowed(tenant: TenantContext) -> None:
    logic = ComplianceIngressLogic(ComplianceChain([AllowInterceptor()]))
    envelope = await logic.process(tenant, Message(role="user", content="hi"))
    assert envelope.message.content == "hi"
    assert not ComplianceIngressLogic.is_refused(envelope)


async def test_process_marks_refusal_on_violation(tenant: TenantContext) -> None:
    logic = ComplianceIngressLogic(ComplianceChain([DenyInterceptor()]))
    envelope = await logic.process(tenant, Message(role="user", content="hi"))
    assert ComplianceIngressLogic.is_refused(envelope)
    assert "not able to help" in envelope.message.content
