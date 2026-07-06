"""Framework-agnostic logic behind the `HITLCheckpoint` sealed canvas
component (architecture Section 5.4). Persists an `ApprovalRequest`
when `MCPToolkit` yields `require_human`; the agency console approval
queue reads pending requests from the same store, and resolution
re-invokes the flow with the approval token (the pause/resume pattern
that replaces engine-level interrupts, since Langflow executes
request-scoped runs and does not natively suspend for hours/days).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import uuid4

from saap.core.flow import ApprovalDecision, ApprovalRequest, FlowRef
from saap.core.types import TenantContext, ToolCall

ApprovalStatus = Literal["pending", "approved", "denied", "expired"]


class ApprovalNotFound(Exception):
    def __init__(self, request_id: str) -> None:
        super().__init__(f"no approval request with id {request_id!r}")


class ApprovalNotPending(Exception):
    def __init__(self, request_id: str, status: ApprovalStatus) -> None:
        self.status = status
        super().__init__(f"approval request {request_id!r} is {status!r}, not pending")


class ApprovalStore(Protocol):
    async def create(self, request: ApprovalRequest) -> None: ...

    async def get(self, request_id: str) -> ApprovalRequest | None: ...

    async def status(self, request_id: str) -> ApprovalStatus | None: ...

    async def list_pending(self, tenant_id: str) -> list[ApprovalRequest]: ...

    async def decide(self, request_id: str, decision: ApprovalDecision) -> None: ...

    async def expire_overdue(self, now: datetime) -> list[ApprovalRequest]: ...


class InMemoryApprovalStore:
    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}
        self._status: dict[str, ApprovalStatus] = {}

    async def create(self, request: ApprovalRequest) -> None:
        self._requests[request.request_id] = request
        self._status[request.request_id] = "pending"

    async def get(self, request_id: str) -> ApprovalRequest | None:
        return self._requests.get(request_id)

    async def status(self, request_id: str) -> ApprovalStatus | None:
        return self._status.get(request_id)

    async def list_pending(self, tenant_id: str) -> list[ApprovalRequest]:
        return [
            r
            for r in self._requests.values()
            if r.tenant_id == tenant_id and self._status.get(r.request_id) == "pending"
        ]

    async def decide(self, request_id: str, decision: ApprovalDecision) -> None:
        current = self._status.get(request_id)
        if current is None:
            raise ApprovalNotFound(request_id)
        if current != "pending":
            raise ApprovalNotPending(request_id, current)
        self._status[request_id] = "approved" if decision.approved else "denied"

    async def expire_overdue(self, now: datetime) -> list[ApprovalRequest]:
        expired = []
        for request_id, request in self._requests.items():
            if self._status.get(request_id) != "pending":
                continue
            if datetime.fromisoformat(request.expires_at) <= now:
                self._status[request_id] = "expired"
                expired.append(request)
        return expired


class HITLCheckpointLogic:
    def __init__(self, store: ApprovalStore, *, ttl_seconds: int = 3600) -> None:
        self._store = store
        self._ttl_seconds = ttl_seconds

    async def checkpoint(
        self,
        tenant: TenantContext,
        flow: FlowRef,
        session_id: str,
        call: ToolCall,
        rationale: str,
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            request_id=str(uuid4()),
            tenant_id=str(tenant.tenant_id),
            flow=flow,
            session_id=session_id,
            tool_call=call.model_dump(),
            rationale=rationale,
            expires_at=(datetime.now(UTC) + timedelta(seconds=self._ttl_seconds)).isoformat(),
        )
        await self._store.create(request)
        return request

    async def resolve(self, request_id: str, decision: ApprovalDecision) -> ApprovalRequest:
        request = await self._store.get(request_id)
        if request is None:
            raise ApprovalNotFound(request_id)
        await self._store.decide(request_id, decision)
        return request

    async def pending_for(self, tenant: TenantContext) -> list[ApprovalRequest]:
        return await self._store.list_pending(str(tenant.tenant_id))

    async def expire_overdue(self, *, now: datetime | None = None) -> list[ApprovalRequest]:
        """Called by the scheduler (FlowScheduler-adjacent, Phase 4) on
        an interval; auto-denies by marking status "expired" rather than
        "denied" so the audit trail and console can distinguish a human
        "no" from a request nobody looked at in time."""
        return await self._store.expire_overdue(now or datetime.now(UTC))
