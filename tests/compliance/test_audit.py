from uuid import uuid4

import pytest
from saap.compliance.audit import GENESIS_HASH, InMemoryAuditStore, TamperDetected
from saap.core.types import TenantContext


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


async def test_first_row_chains_from_genesis(tenant: TenantContext) -> None:
    store = InMemoryAuditStore()
    row = await store.append(tenant, "message", {"a": 1})
    assert row.prev_hash == GENESIS_HASH


async def test_rows_chain_sequentially(tenant: TenantContext) -> None:
    store = InMemoryAuditStore()
    first = await store.append(tenant, "message", {"a": 1})
    second = await store.append(tenant, "response", {"b": 2})
    assert second.prev_hash == first.row_hash


async def test_verify_chain_passes_on_untampered_rows(tenant: TenantContext) -> None:
    store = InMemoryAuditStore()
    await store.append(tenant, "message", {"a": 1})
    await store.append(tenant, "response", {"b": 2})
    store.verify_chain(tenant)  # no raise


async def test_verify_chain_detects_tampering(tenant: TenantContext) -> None:
    store = InMemoryAuditStore()
    await store.append(tenant, "message", {"a": 1})
    await store.append(tenant, "response", {"b": 2})

    rows = store._rows[str(tenant.tenant_id)]
    tampered = rows[0].model_copy(update={"payload": {"a": 999}})
    rows[0] = tampered

    with pytest.raises(TamperDetected):
        store.verify_chain(tenant)


async def test_different_tenants_have_independent_chains() -> None:
    store = InMemoryAuditStore()
    t1 = TenantContext(tenant_id=uuid4(), vertical="dental")
    t2 = TenantContext(tenant_id=uuid4(), vertical="realestate")
    row1 = await store.append(t1, "message", {"a": 1})
    row2 = await store.append(t2, "message", {"a": 1})
    assert row1.prev_hash == GENESIS_HASH
    assert row2.prev_hash == GENESIS_HASH  # independent chain, not chained to t1
