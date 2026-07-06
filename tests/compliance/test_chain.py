from uuid import uuid4

import pytest
from saap.compliance.chain import ComplianceChain, ComplianceViolation, Envelope
from saap.core.types import Message, TenantContext


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


class RecordingInterceptor:
    def __init__(self, name: str, log: list[str], *, deny: bool = False) -> None:
        self.name = name
        self._log = log
        self._deny = deny

    async def before(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        self._log.append(f"{self.name}.before")
        if self._deny:
            raise ComplianceViolation(self.name, "denied by test")
        return envelope

    async def after(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        self._log.append(f"{self.name}.after")
        return envelope


async def test_chain_runs_before_then_inner_then_after_in_reverse(tenant: TenantContext) -> None:
    log: list[str] = []
    chain = ComplianceChain([RecordingInterceptor("a", log), RecordingInterceptor("b", log)])
    envelope = Envelope(tenant, Message(role="user", content="hi"))

    async def inner(t: TenantContext, env: Envelope) -> Envelope:
        log.append("inner")
        return env

    await chain.wrap(tenant, envelope, inner)
    assert log == ["a.before", "b.before", "inner", "b.after", "a.after"]


async def test_violation_short_circuits_and_unwinds_only_ran_interceptors(
    tenant: TenantContext,
) -> None:
    log: list[str] = []
    chain = ComplianceChain(
        [RecordingInterceptor("a", log), RecordingInterceptor("b", log, deny=True), RecordingInterceptor("c", log)]
    )
    envelope = Envelope(tenant, Message(role="user", content="hi"))

    async def inner(t: TenantContext, env: Envelope) -> Envelope:
        log.append("inner")
        return env

    result = await chain.wrap(tenant, envelope, inner)
    # "c" never ran (b denied before c's before()); inner never ran either.
    assert log == ["a.before", "b.before", "a.after"]
    assert result.metadata["violation"] == "b"
    assert "not able to help" in result.message.content


def test_chain_requires_at_least_one_interceptor() -> None:
    with pytest.raises(ValueError):
        ComplianceChain([])


def test_envelope_with_message_merges_metadata(tenant: TenantContext) -> None:
    envelope = Envelope(tenant, Message(role="user", content="hi"), {"a": 1})
    new_message = Message(role="user", content="bye")
    updated = envelope.with_message(new_message, b=2)
    assert updated.metadata == {"a": 1, "b": 2}
    assert updated.message.content == "bye"
    assert envelope.message.content == "hi"  # original untouched
