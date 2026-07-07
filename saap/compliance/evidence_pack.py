"""DPDP Phase-3 evidence pack assembly (Phase 6).

Assembles the artifacts a real compliance sign-off needs into one
bundle per tenant: erasure certificates already issued
(`ErasureService`), any breach alerts raised (`saap.compliance.breach`),
and a fresh audit-chain integrity check
(`InMemoryAuditStore.verify_chain`). Encryption-at-rest/in-transit
attestations and processor contracts are deployment/legal artifacts
this codebase has no way to generate — they aren't code outputs — so
`build_evidence_pack` doesn't invent them; a caller attaches those
separately when compiling the final pack for submission.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from saap.core.types import TenantContext

from .audit import InMemoryAuditStore, TamperDetected
from .breach import BreachAlert
from .erasure import ErasureCertificate


class AuditChainVerification(BaseModel, frozen=True):
    tenant_id: str
    verified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    passed: bool
    tamper_detail: str | None = None


class EvidencePack(BaseModel, frozen=True):
    tenant_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    erasure_certificates: tuple[ErasureCertificate, ...] = ()
    breach_alerts: tuple[BreachAlert, ...] = ()
    audit_chain_verification: AuditChainVerification
    encryption_attestations: tuple[str, ...] = ()  # deployment-supplied, not generated here
    processor_contracts: tuple[str, ...] = ()  # legal artifacts, not generated here


def build_evidence_pack(
    tenant: TenantContext,
    audit_store: InMemoryAuditStore,
    *,
    erasure_certificates: Sequence[ErasureCertificate] = (),
    breach_alerts: Sequence[BreachAlert] = (),
) -> EvidencePack:
    try:
        audit_store.verify_chain(tenant)
    except TamperDetected as exc:
        verification = AuditChainVerification(
            tenant_id=str(tenant.tenant_id), passed=False, tamper_detail=str(exc)
        )
    else:
        verification = AuditChainVerification(tenant_id=str(tenant.tenant_id), passed=True)

    return EvidencePack(
        tenant_id=str(tenant.tenant_id),
        erasure_certificates=tuple(erasure_certificates),
        breach_alerts=tuple(breach_alerts),
        audit_chain_verification=verification,
    )
