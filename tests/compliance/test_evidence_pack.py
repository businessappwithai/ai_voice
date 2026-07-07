from uuid import uuid4

import pytest
from saap.compliance.audit import InMemoryAuditStore
from saap.compliance.breach import BreachAlert
from saap.compliance.erasure import ErasureService, HMACCertificateSigner
from saap.compliance.evidence_pack import build_evidence_pack
from saap.compliance.pii import TokenVault
from saap.core.fakes import FakeVectorStore
from saap.core.types import TenantContext


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


async def test_build_evidence_pack_passes_verification_on_untampered_chain(
    tenant: TenantContext,
) -> None:
    audit_store = InMemoryAuditStore()
    await audit_store.append(tenant, "message", {"a": 1})

    pack = build_evidence_pack(tenant, audit_store)

    assert pack.audit_chain_verification.passed is True
    assert pack.audit_chain_verification.tamper_detail is None
    assert pack.tenant_id == str(tenant.tenant_id)


async def test_build_evidence_pack_flags_tampered_chain(tenant: TenantContext) -> None:
    audit_store = InMemoryAuditStore()
    await audit_store.append(tenant, "message", {"a": 1})
    await audit_store.append(tenant, "response", {"b": 2})
    rows = audit_store._rows[str(tenant.tenant_id)]  # noqa: SLF001 - white-box tamper injection
    rows[0] = rows[0].model_copy(update={"payload": {"a": 999}})

    pack = build_evidence_pack(tenant, audit_store)

    assert pack.audit_chain_verification.passed is False
    assert pack.audit_chain_verification.tamper_detail is not None


async def test_build_evidence_pack_includes_erasure_certificates(tenant: TenantContext) -> None:
    audit_store = InMemoryAuditStore()
    erasure_service = ErasureService(FakeVectorStore(), TokenVault(), audit_store, HMACCertificateSigner())
    certificate = await erasure_service.erase(tenant, "minio://t/a.pdf")

    pack = build_evidence_pack(tenant, audit_store, erasure_certificates=[certificate])

    assert pack.erasure_certificates == (certificate,)


async def test_build_evidence_pack_includes_breach_alerts(tenant: TenantContext) -> None:
    audit_store = InMemoryAuditStore()
    alert = BreachAlert(tenant_id=str(tenant.tenant_id), kind="tamper_detected", detail="x")

    pack = build_evidence_pack(tenant, audit_store, breach_alerts=[alert])

    assert pack.breach_alerts == (alert,)


async def test_build_evidence_pack_defaults_are_empty(tenant: TenantContext) -> None:
    audit_store = InMemoryAuditStore()

    pack = build_evidence_pack(tenant, audit_store)

    assert pack.erasure_certificates == ()
    assert pack.breach_alerts == ()
    assert pack.encryption_attestations == ()
    assert pack.processor_contracts == ()
