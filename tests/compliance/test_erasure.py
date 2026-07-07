from uuid import uuid4

import pytest
from saap.compliance.audit import InMemoryAuditStore
from saap.compliance.erasure import (
    ErasureService,
    HMACCertificateSigner,
    certificate_payload_bytes,
    verify_certificate,
)
from saap.compliance.pii import TokenVault
from saap.core.fakes import FakeVectorStore
from saap.core.memory import DocumentChunk
from saap.core.types import DataClass, TenantContext


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


def _chunk(source_uri: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=uuid4(), source_uri=source_uri, text="hello", data_class=DataClass.PERSONAL
    )


async def test_erase_deletes_only_the_matching_source(tenant: TenantContext) -> None:
    store = FakeVectorStore()
    await store.upsert(tenant, [_chunk("minio://t/a.pdf"), _chunk("minio://t/a.pdf")], [[0.0], [0.0]])
    await store.upsert(tenant, [_chunk("minio://t/b.pdf")], [[0.0]])
    service = ErasureService(store, TokenVault(), InMemoryAuditStore(), HMACCertificateSigner())

    certificate = await service.erase(tenant, "minio://t/a.pdf")

    assert certificate.chunks_deleted == 2
    remaining = await store.search(tenant, [0.0], k=10)
    assert [rc.chunk.source_uri for rc in remaining] == ["minio://t/b.pdf"]


async def test_erase_destroys_the_token_vault(tenant: TenantContext) -> None:
    vault = TokenVault()
    token = vault.tokenize("IN_AADHAAR", "123456789012")
    service = ErasureService(FakeVectorStore(), vault, InMemoryAuditStore(), HMACCertificateSigner())

    await service.erase(tenant, "minio://t/a.pdf")

    assert vault.resolve(token) is None


async def test_erase_appends_an_erasure_row_to_the_audit_chain(tenant: TenantContext) -> None:
    audit_store = InMemoryAuditStore()
    service = ErasureService(FakeVectorStore(), TokenVault(), audit_store, HMACCertificateSigner())

    certificate = await service.erase(tenant, "minio://t/a.pdf")

    rows = await audit_store.rows_for(tenant)
    assert [r.kind for r in rows] == ["erasure"]
    assert rows[0].row_id == certificate.audit_row_id
    assert rows[0].row_hash == certificate.audit_row_hash


async def test_erase_certificate_signature_verifies(tenant: TenantContext) -> None:
    signer = HMACCertificateSigner()
    service = ErasureService(FakeVectorStore(), TokenVault(), InMemoryAuditStore(), signer)

    certificate = await service.erase(tenant, "minio://t/a.pdf")

    assert verify_certificate(certificate, signer)


async def test_erase_certificate_signature_rejects_tampering(tenant: TenantContext) -> None:
    signer = HMACCertificateSigner()
    service = ErasureService(FakeVectorStore(), TokenVault(), InMemoryAuditStore(), signer)

    certificate = await service.erase(tenant, "minio://t/a.pdf")
    tampered = certificate.model_copy(update={"chunks_deleted": certificate.chunks_deleted + 1})

    assert not verify_certificate(tampered, signer)


async def test_erase_certificate_signature_rejects_wrong_signer(tenant: TenantContext) -> None:
    service = ErasureService(
        FakeVectorStore(), TokenVault(), InMemoryAuditStore(), HMACCertificateSigner()
    )
    certificate = await service.erase(tenant, "minio://t/a.pdf")

    wrong_signer = HMACCertificateSigner()  # different random key
    assert not wrong_signer.verify(certificate_payload_bytes(certificate), certificate.signature)


async def test_erase_of_a_source_with_no_chunks_still_produces_a_valid_certificate(
    tenant: TenantContext,
) -> None:
    signer = HMACCertificateSigner()
    service = ErasureService(FakeVectorStore(), TokenVault(), InMemoryAuditStore(), signer)

    certificate = await service.erase(tenant, "minio://t/never-ingested.pdf")

    assert certificate.chunks_deleted == 0
    assert verify_certificate(certificate, signer)
