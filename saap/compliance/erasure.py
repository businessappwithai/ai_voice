"""ErasureService — DPDP Phase-3 erasure engineering (plan Epic 3.2).

Tears down every retained artifact for one ingested source and produces
a signed, audit-chained certificate — the auditable proof-of-deletion
DPDP expects when a purpose expires or a data principal exercises their
erasure right.

What's wired here: `VectorStore.delete_by_source` (lineage-exact,
already required by every adapter — see `saap.core.memory`) and
`TokenVault.destroy_all` (crypto-shredding the PII placeholder vault,
`saap.compliance.pii`), with the result appended into the same
hash-chained `AuditStore` everything else in L5 writes to (`kind=
"erasure"`), then HMAC-signed.

Deliberately not included: Postgres source-row purge and MinIO object
deletion. Both are real requirements of the plan's Dagster erasure job,
but neither has a first-party store adapter in this codebase yet
(`saap.plugins` has no Postgres tenant-record or MinIO client), and
guessing at Dagster's op API to wire a job that can't be run against
anything real would be worse than leaving the gap explicit — this
service covers the two stores this codebase actually has working
adapters for, ready to compose into the full job once those adapters
land.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from saap.core.memory import VectorStore
from saap.core.types import TenantContext

from .audit import AuditStore
from .pii import TokenVault


class ErasureCertificate(BaseModel, frozen=True):
    certificate_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    source_uri: str
    chunks_deleted: int
    vault_destroyed: bool
    audit_row_id: UUID
    audit_row_hash: str
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    signature: str = ""  # populated by ErasureService; empty here is not a valid certificate


class CertificateSigner(Protocol):
    def sign(self, payload: bytes) -> str: ...

    def verify(self, payload: bytes, signature: str) -> bool: ...


class HMACCertificateSigner:
    """Real HMAC-SHA256 signing with an injectable key (tests supply
    one directly; production sources it from OpenBao, same pattern as
    `TokenVault`'s AES key — see saap/compliance/pii.py)."""

    def __init__(self, key: bytes | None = None) -> None:
        self._key = key or os.urandom(32)

    def sign(self, payload: bytes) -> str:
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(payload), signature)


def certificate_payload_bytes(certificate: ErasureCertificate) -> bytes:
    """Canonical bytes signed/verified — every field except `signature`
    itself, so the signature covers the whole certificate body."""
    canonical = json.dumps(
        certificate.model_dump(mode="json", exclude={"signature"}),
        sort_keys=True,
    )
    return canonical.encode("utf-8")


def verify_certificate(certificate: ErasureCertificate, signer: CertificateSigner) -> bool:
    return signer.verify(certificate_payload_bytes(certificate), certificate.signature)


class ErasureService:
    def __init__(
        self,
        vector_store: VectorStore,
        token_vault: TokenVault,
        audit_store: AuditStore,
        signer: CertificateSigner,
    ) -> None:
        self._vector_store = vector_store
        self._token_vault = token_vault
        self._audit_store = audit_store
        self._signer = signer

    async def erase(self, tenant: TenantContext, source_uri: str) -> ErasureCertificate:
        chunks_deleted = await self._vector_store.delete_by_source(tenant, source_uri)
        self._token_vault.destroy_all()

        audit_row = await self._audit_store.append(
            tenant,
            kind="erasure",
            payload={"source_uri": source_uri, "chunks_deleted": chunks_deleted},
        )

        certificate = ErasureCertificate(
            tenant_id=str(tenant.tenant_id),
            source_uri=source_uri,
            chunks_deleted=chunks_deleted,
            vault_destroyed=True,
            audit_row_id=audit_row.row_id,
            audit_row_hash=audit_row.row_hash,
        )
        signature = self._signer.sign(certificate_payload_bytes(certificate))
        return certificate.model_copy(update={"signature": signature})
