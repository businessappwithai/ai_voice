from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from saap.core.flow import ApprovalDecision, FlowRef
from saap.core.types import TenantContext, ToolCall
from saap.langflow_components.logic.hitl_checkpoint import (
    ApprovalNotFound,
    ApprovalNotPending,
    HITLCheckpointLogic,
    InMemoryApprovalStore,
)


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


def _flow() -> FlowRef:
    return FlowRef(flow_id="f1", name="dental.intake", version="1.0.0", checksum="abc", lint_report_id="r1")


def _call() -> ToolCall:
    return ToolCall(call_id="1", tool_name="mcp.billing.refund", arguments={"amount": 500}, risk_tier="high_risk")


async def test_checkpoint_creates_pending_request(tenant: TenantContext) -> None:
    logic = HITLCheckpointLogic(InMemoryApprovalStore())
    request = await logic.checkpoint(tenant, _flow(), "sess-1", _call(), "refund requested")
    assert request.tenant_id == str(tenant.tenant_id)
    pending = await logic.pending_for(tenant)
    assert [p.request_id for p in pending] == [request.request_id]


async def test_resolve_approved_marks_not_pending(tenant: TenantContext) -> None:
    store = InMemoryApprovalStore()
    logic = HITLCheckpointLogic(store)
    request = await logic.checkpoint(tenant, _flow(), "sess-1", _call(), "refund requested")

    decision = ApprovalDecision(request_id=request.request_id, approved=True, approver="agent@agency.test")
    await logic.resolve(request.request_id, decision)

    assert await store.status(request.request_id) == "approved"
    assert await logic.pending_for(tenant) == []


async def test_resolve_denied(tenant: TenantContext) -> None:
    store = InMemoryApprovalStore()
    logic = HITLCheckpointLogic(store)
    request = await logic.checkpoint(tenant, _flow(), "sess-1", _call(), "refund requested")

    decision = ApprovalDecision(request_id=request.request_id, approved=False, approver="agent@agency.test")
    await logic.resolve(request.request_id, decision)
    assert await store.status(request.request_id) == "denied"


async def test_resolve_unknown_request_raises(tenant: TenantContext) -> None:
    logic = HITLCheckpointLogic(InMemoryApprovalStore())
    decision = ApprovalDecision(request_id="nope", approved=True, approver="x")
    with pytest.raises(ApprovalNotFound):
        await logic.resolve("nope", decision)


async def test_resolve_already_decided_request_raises(tenant: TenantContext) -> None:
    store = InMemoryApprovalStore()
    logic = HITLCheckpointLogic(store)
    request = await logic.checkpoint(tenant, _flow(), "sess-1", _call(), "refund requested")
    decision = ApprovalDecision(request_id=request.request_id, approved=True, approver="a")
    await logic.resolve(request.request_id, decision)

    with pytest.raises(ApprovalNotPending):
        await logic.resolve(request.request_id, decision)


async def test_expire_overdue_auto_denies_expired_pending_requests(tenant: TenantContext) -> None:
    store = InMemoryApprovalStore()
    logic = HITLCheckpointLogic(store, ttl_seconds=1)
    request = await logic.checkpoint(tenant, _flow(), "sess-1", _call(), "refund requested")

    future = datetime.now(UTC) + timedelta(seconds=5)
    expired = await logic.expire_overdue(now=future)

    assert [e.request_id for e in expired] == [request.request_id]
    assert await store.status(request.request_id) == "expired"


async def test_expire_overdue_ignores_non_expired_requests(tenant: TenantContext) -> None:
    store = InMemoryApprovalStore()
    logic = HITLCheckpointLogic(store, ttl_seconds=3600)
    await logic.checkpoint(tenant, _flow(), "sess-1", _call(), "refund requested")

    expired = await logic.expire_overdue(now=datetime.now(UTC))
    assert expired == []


async def test_expire_overdue_does_not_reexpire_already_decided(tenant: TenantContext) -> None:
    store = InMemoryApprovalStore()
    logic = HITLCheckpointLogic(store, ttl_seconds=1)
    request = await logic.checkpoint(tenant, _flow(), "sess-1", _call(), "refund requested")
    await logic.resolve(request.request_id, ApprovalDecision(request_id=request.request_id, approved=True, approver="a"))

    future = datetime.now(UTC) + timedelta(seconds=5)
    expired = await logic.expire_overdue(now=future)
    assert expired == []
    assert await store.status(request.request_id) == "approved"
