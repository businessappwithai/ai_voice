from datetime import UTC, datetime
from uuid import uuid4

import pytest
from saap.compliance.policy import InMemoryPolicyGuard
from saap.core.types import TenantContext, ToolCall


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


class FixedClock:
    def __init__(self, hour: int) -> None:
        self._hour = hour

    def now(self) -> datetime:
        return datetime(2026, 7, 6, self._hour, 0, tzinfo=UTC)


async def test_read_always_allowed(tenant: TenantContext) -> None:
    guard = InMemoryPolicyGuard(clock=FixedClock(3))  # 3am, outside business hours
    call = ToolCall(call_id="1", tool_name="mcp.crm.get_contact", arguments={}, risk_tier="read")
    assert await guard.evaluate(tenant, call) == "allow"


async def test_high_risk_always_requires_human(tenant: TenantContext) -> None:
    guard = InMemoryPolicyGuard(clock=FixedClock(12))
    call = ToolCall(call_id="1", tool_name="mcp.crm.delete_record", arguments={}, risk_tier="high_risk")
    assert await guard.evaluate(tenant, call) == "require_human"


async def test_write_allowed_in_business_hours(tenant: TenantContext) -> None:
    guard = InMemoryPolicyGuard(clock=FixedClock(14))
    call = ToolCall(call_id="1", tool_name="mcp.calendar.book_slot", arguments={}, risk_tier="write")
    assert await guard.evaluate(tenant, call) == "allow"


async def test_write_denied_outside_business_hours(tenant: TenantContext) -> None:
    guard = InMemoryPolicyGuard(clock=FixedClock(23))
    call = ToolCall(call_id="1", tool_name="mcp.calendar.book_slot", arguments={}, risk_tier="write")
    assert await guard.evaluate(tenant, call) == "deny"


async def test_write_denied_if_not_in_allowed_tools(tenant: TenantContext) -> None:
    guard = InMemoryPolicyGuard(clock=FixedClock(14), allowed_write_tools=frozenset({"book_slot"}))
    call = ToolCall(call_id="1", tool_name="mcp.calendar.cancel_slot", arguments={}, risk_tier="write")
    assert await guard.evaluate(tenant, call) == "deny"
