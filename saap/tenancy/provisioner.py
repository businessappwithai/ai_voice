"""TenantProvisioner — idempotent apply/destroy across every resource
a tenant blueprint touches (Phase 4 Epic 4.1): Keycloak realm, Qdrant/
pgvector isolation unit, Postgres schema, OPA data document, MCP
server configs, CRM workspace, ingestion sources.

Each resource is a `ResourceProvisioner`: same idempotent
`apply(dry_run=...)` / `destroy` shape regardless of what it's
actually provisioning, so `TenantProvisioner` can orchestrate a list of
them uniformly (the same pattern `ComplianceChain` uses for
interceptors). `dry_run=True` computes what would change without
mutating anything — `TenantProvisioner.plan` uses this for drift
detection (Epic 4.1's "drift detection reports manual changes"
acceptance criterion); `dry_run=False` performs it, and must be a
no-op (`changed=False`) when the resource already matches the
blueprint ("re-applying a blueprint is a no-op").
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel

from .blueprint import TenantBlueprint


class ProvisionRecord(BaseModel, frozen=True):
    provisioner: str
    tenant_id: str
    changed: bool
    detail: dict[str, Any] = {}


class ResourceProvisioner(Protocol):
    name: str

    async def apply(
        self, tenant_id: UUID, blueprint: TenantBlueprint, *, dry_run: bool = False
    ) -> ProvisionRecord: ...

    async def destroy(self, tenant_id: UUID) -> None:
        """Must be safe to call on a never-applied or already-destroyed
        tenant (idempotent teardown, not just idempotent create)."""
        ...


class TenantProvisioner:
    def __init__(self, provisioners: Sequence[ResourceProvisioner]) -> None:
        self._provisioners = list(provisioners)

    async def plan(self, tenant_id: UUID, blueprint: TenantBlueprint) -> list[ProvisionRecord]:
        return [await p.apply(tenant_id, blueprint, dry_run=True) for p in self._provisioners]

    async def apply(self, tenant_id: UUID, blueprint: TenantBlueprint) -> list[ProvisionRecord]:
        return [await p.apply(tenant_id, blueprint, dry_run=False) for p in self._provisioners]

    async def destroy(self, tenant_id: UUID) -> None:
        """Resource teardown only, in reverse of application order.
        Compliance-grade tenant offboarding ("erasure job + resource
        teardown", Epic 4.1) additionally requires running
        `ErasureService.erase` (saap.compliance.erasure) for every
        source this tenant ever ingested — this codebase has no
        per-tenant source registry to enumerate them from yet, so a
        real `saap tenant destroy` CLI is responsible for sequencing
        that alongside this call."""
        for p in reversed(self._provisioners):
            await p.destroy(tenant_id)
