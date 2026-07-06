from uuid import uuid4

import pytest
from saap.compliance.chain import ComplianceChain, ComplianceViolation, Envelope
from saap.compliance.runtime import InterceptedRuntime, RuntimeRefused
from saap.core.flow import ApprovalDecision, FlowRef
from saap.core.types import Message, TenantContext


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental", consent_scope=frozenset({"service"}))


class FakeOrchestrator:
    def __init__(self) -> None:
        self.started: list[tuple] = []
        self.resumed: list[ApprovalDecision] = []
        self.cancelled: list[str] = []

    async def start(self, tenant, flow, message, session_id) -> str:  # noqa: ANN001
        self.started.append((tenant, flow, message, session_id))
        return "run-123"

    def events(self, run_id: str):  # noqa: ANN001, ANN201
        async def gen():
            return
            yield  # pragma: no cover

        return gen()

    async def resume(self, request_id: str, decision: ApprovalDecision) -> None:
        self.resumed.append(decision)

    async def cancel(self, run_id: str) -> None:
        self.cancelled.append(run_id)


class AllowInterceptor:
    name = "allow"

    async def before(self, tenant, envelope: Envelope) -> Envelope:  # noqa: ANN001
        return envelope

    async def after(self, tenant, envelope: Envelope) -> Envelope:  # noqa: ANN001
        return envelope


class DenyInterceptor:
    name = "deny"

    async def before(self, tenant, envelope: Envelope) -> Envelope:  # noqa: ANN001
        raise ComplianceViolation("deny", "test denial")

    async def after(self, tenant, envelope: Envelope) -> Envelope:  # noqa: ANN001
        return envelope


def _flow_ref() -> FlowRef:
    return FlowRef(flow_id="f1", name="dental.intake", version="1.0.0", checksum="abc", lint_report_id="r1")


async def test_start_reaches_orchestrator_when_chain_allows(tenant: TenantContext) -> None:
    orchestrator = FakeOrchestrator()
    chain = ComplianceChain([AllowInterceptor()])
    runtime = InterceptedRuntime(chain, orchestrator)

    run_id = await runtime.start(tenant, _flow_ref(), Message(role="user", content="hi"), "sess-1")
    assert run_id == "run-123"
    assert len(orchestrator.started) == 1


async def test_start_raises_runtime_refused_when_chain_denies(tenant: TenantContext) -> None:
    orchestrator = FakeOrchestrator()
    chain = ComplianceChain([DenyInterceptor()])
    runtime = InterceptedRuntime(chain, orchestrator)

    with pytest.raises(RuntimeRefused) as exc_info:
        await runtime.start(tenant, _flow_ref(), Message(role="user", content="hi"), "sess-1")
    assert "not able to help" in exc_info.value.refusal_text
    assert orchestrator.started == []  # never reached the orchestrator


async def test_resume_and_cancel_delegate_to_orchestrator(tenant: TenantContext) -> None:
    orchestrator = FakeOrchestrator()
    chain = ComplianceChain([AllowInterceptor()])
    runtime = InterceptedRuntime(chain, orchestrator)

    decision = ApprovalDecision(request_id="r1", approved=True, approver="agent@agency.test")
    await runtime.resume("r1", decision)
    assert orchestrator.resumed == [decision]

    await runtime.cancel("run-123")
    assert orchestrator.cancelled == ["run-123"]
