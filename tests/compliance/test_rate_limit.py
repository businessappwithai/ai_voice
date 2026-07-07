from uuid import uuid4

import pytest
from saap.compliance.chain import ComplianceViolation, Envelope
from saap.compliance.rate_limit import InMemoryRateLimitBackend, RateLimiter
from saap.core.types import Message, TenantContext


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


async def test_allows_up_to_limit(tenant: TenantContext) -> None:
    limiter = RateLimiter(InMemoryRateLimitBackend(), default_limit=3, window_seconds=60)
    envelope = Envelope(tenant, Message(role="user", content="hi"))
    for _ in range(3):
        await limiter.before(tenant, envelope)  # no raise


async def test_denies_over_limit(tenant: TenantContext) -> None:
    limiter = RateLimiter(InMemoryRateLimitBackend(), default_limit=2, window_seconds=60)
    envelope = Envelope(tenant, Message(role="user", content="hi"))
    await limiter.before(tenant, envelope)
    await limiter.before(tenant, envelope)
    with pytest.raises(ComplianceViolation):
        await limiter.before(tenant, envelope)


async def test_tool_specific_limit_overrides_default(tenant: TenantContext) -> None:
    limiter = RateLimiter(
        InMemoryRateLimitBackend(), default_limit=100, window_seconds=60, tool_limits={"book_slot": 1}
    )
    envelope = Envelope(tenant, Message(role="user", content="hi"), {"tool_call_name": "book_slot"})
    await limiter.before(tenant, envelope)
    with pytest.raises(ComplianceViolation):
        await limiter.before(tenant, envelope)


async def test_different_tenants_have_independent_budgets() -> None:
    limiter = RateLimiter(InMemoryRateLimitBackend(), default_limit=1, window_seconds=60)
    t1 = TenantContext(tenant_id=uuid4(), vertical="dental")
    t2 = TenantContext(tenant_id=uuid4(), vertical="realestate")
    await limiter.before(t1, Envelope(t1, Message(role="user", content="hi")))
    await limiter.before(t2, Envelope(t2, Message(role="user", content="hi")))  # independent budget
