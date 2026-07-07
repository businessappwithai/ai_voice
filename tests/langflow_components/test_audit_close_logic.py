from uuid import uuid4

import pytest
from saap.compliance.chain import ComplianceChain, Envelope
from saap.core.types import Message, TenantContext
from saap.langflow_components.logic.audit_close import AuditCloseLogic
from saap.langflow_components.logic.compliance_ingress import ComplianceIngressLogic


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


class RecordingInterceptor:
    def __init__(self, name: str, log: list[str]) -> None:
        self.name = name
        self._log = log

    async def before(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        self._log.append(f"{self.name}.before")
        return envelope

    async def after(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        self._log.append(f"{self.name}.after")
        return envelope


async def test_audit_close_runs_after_phase_for_ingress_ran_interceptors(tenant: TenantContext) -> None:
    log: list[str] = []
    chain = ComplianceChain([RecordingInterceptor("a", log), RecordingInterceptor("b", log)])
    ingress = ComplianceIngressLogic(chain)
    close = AuditCloseLogic(chain)

    envelope = await ingress.process(tenant, Message(role="user", content="hi"))
    log.append("canvas")
    await close.close(tenant, envelope)

    assert log == ["a.before", "b.before", "canvas", "b.after", "a.after"]
