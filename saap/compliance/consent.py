"""ConsentGate — L5 stage 1, fail-closed consent enforcement.

Phase 1 seeds purposes manually in the consent registry (Postgres);
Phase 3 wires this behind a real Consent Manager API (an MCP server,
per the DPDP Phase-2 statutory requirement, due 13 Nov 2026) without
changing this interceptor's contract — the registry lookup is the
seam that isolates that integration.

Fail-closed means: if the registry has no explicit grant for the
purpose this message requires, the request is refused. There is no
default-allow path.
"""
from __future__ import annotations

from typing import Protocol

from saap.core.types import TenantContext

from .chain import ComplianceViolation, Envelope


class ConsentRegistry(Protocol):
    """Backing store for granted purposes per tenant+principal.
    `TenantContext.consent_scope` is a snapshot taken at session start;
    the registry is the source of truth checked here so a same-session
    revocation (consent.revoked domain event) takes effect immediately
    rather than waiting for the next login."""

    async def has_grant(self, tenant: TenantContext, purpose: str) -> bool: ...


class StaticConsentRegistry:
    """Reads only from `TenantContext.consent_scope` — the Phase-1
    "seeded manually" registry mentioned in the plan. Real deployments
    swap in a Postgres-backed registry synced from the Consent Manager
    (Phase 3) without touching ConsentGate itself."""

    async def has_grant(self, tenant: TenantContext, purpose: str) -> bool:
        return tenant.has_consent(purpose)


class ConsentGate:
    """L5 stage 1. `required_purpose` is resolved from envelope metadata
    (set by the channel adapter or canvas component based on message
    intent — e.g. "marketing" for a campaign send, "service" for a
    support reply); absent an explicit purpose, the default "service"
    purpose is required, which is still fail-closed for a tenant that
    has granted nothing."""

    name = "consent_gate"

    def __init__(self, registry: ConsentRegistry, *, default_purpose: str = "service") -> None:
        self._registry = registry
        self._default_purpose = default_purpose

    async def before(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        purpose = envelope.metadata.get("purpose", self._default_purpose)
        if not await self._registry.has_grant(tenant, purpose):
            raise ComplianceViolation("consent_gate", f"no consent for purpose {purpose!r}")
        return envelope

    async def after(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        return envelope
