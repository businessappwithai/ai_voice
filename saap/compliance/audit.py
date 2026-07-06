"""Append-only, hash-chained audit trail (L5 stage 5).

Each row carries sha256(prev_row_hash || row_payload) — a hash chain
making silent tampering detectable (the "immutable audit trail" DPDP
expects). `AuditRecorder` is an Interceptor so every request that
enters the compliance chain gets a row, including refusals raised by
an earlier interceptor (ConsentGate/PolicyGuard denials are themselves
audit-worthy events).

The real store is Postgres (see migrations/versions — `audit_log`
table); `InMemoryAuditStore` below is the same hash-chain logic against
a Python list, used by unit tests and any environment without Postgres
wired up yet.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from saap.core.types import TenantContext

from .chain import Envelope

GENESIS_HASH = "0" * 64


class AuditRow(BaseModel, frozen=True):
    row_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    kind: str  # "message" | "tool_call" | "refusal" | "approval" | ...
    payload: dict[str, Any]
    prev_hash: str
    row_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def compute_row_hash(prev_hash: str, tenant_id: str, kind: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"tenant_id": tenant_id, "kind": kind, "payload": payload}, sort_keys=True, default=str
    )
    return hashlib.sha256(f"{prev_hash}{canonical}".encode()).hexdigest()


class AuditStore(Protocol):
    async def append(self, tenant: TenantContext, kind: str, payload: dict[str, Any]) -> AuditRow: ...

    async def last_hash(self, tenant: TenantContext) -> str: ...

    async def rows_for(self, tenant: TenantContext) -> list[AuditRow]: ...


class TamperDetected(Exception):
    def __init__(self, tenant_id: str, row_id: UUID) -> None:
        super().__init__(
            f"audit chain tamper detected for tenant {tenant_id}: row {row_id} hash mismatch"
        )


class InMemoryAuditStore:
    """Per-tenant append-only list with the same hash-chain semantics
    the Postgres-backed store uses. `verify_chain` walks the whole
    chain recomputing hashes — the same check a nightly integrity job
    runs against the real table."""

    def __init__(self) -> None:
        self._rows: dict[str, list[AuditRow]] = {}

    async def last_hash(self, tenant: TenantContext) -> str:
        rows = self._rows.get(str(tenant.tenant_id), [])
        return rows[-1].row_hash if rows else GENESIS_HASH

    async def append(self, tenant: TenantContext, kind: str, payload: dict[str, Any]) -> AuditRow:
        tenant_id = str(tenant.tenant_id)
        prev_hash = await self.last_hash(tenant)
        row_hash = compute_row_hash(prev_hash, tenant_id, kind, payload)
        row = AuditRow(
            tenant_id=tenant_id, kind=kind, payload=payload, prev_hash=prev_hash, row_hash=row_hash
        )
        self._rows.setdefault(tenant_id, []).append(row)
        return row

    async def rows_for(self, tenant: TenantContext) -> list[AuditRow]:
        return list(self._rows.get(str(tenant.tenant_id), []))

    def verify_chain(self, tenant: TenantContext) -> None:
        """Raises TamperDetected on the first row whose stored hash
        doesn't match a fresh recomputation — i.e. any row edited after
        the fact, no matter how the edit was made."""
        rows = self._rows.get(str(tenant.tenant_id), [])
        expected_prev = GENESIS_HASH
        for row in rows:
            recomputed = compute_row_hash(expected_prev, row.tenant_id, row.kind, row.payload)
            if recomputed != row.row_hash or row.prev_hash != expected_prev:
                raise TamperDetected(row.tenant_id, row.row_id)
            expected_prev = row.row_hash


class AuditRecorder:
    """L5 stage 5 (also runs on the way out, i.e. `after`, so refusals
    from earlier interceptors are captured too)."""

    name = "audit_recorder"

    def __init__(self, store: AuditStore) -> None:
        self._store = store

    async def before(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        row = await self._store.append(
            tenant,
            kind="message",
            payload={"role": envelope.message.role, "content_hash": _content_hash(envelope.message.content)},
        )
        return envelope.with_message(envelope.message, audit_row_id=str(row.row_id))

    async def after(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        kind = "refusal" if envelope.metadata.get("compliance_violation") else "response"
        await self._store.append(
            tenant,
            kind=kind,
            payload={
                "content_hash": _content_hash(envelope.message.content),
                "violation": envelope.metadata.get("compliance_violation"),
            },
        )
        return envelope


def _content_hash(content: str) -> str:
    # We hash rather than store raw content in the audit row: the audit
    # trail proves *what happened* (which interceptor saw what shape of
    # event, in what order) without itself becoming a second copy of
    # sensitive data that then needs its own erasure workflow.
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
