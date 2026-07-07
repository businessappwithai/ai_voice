"""FlowScheduler — Phase 4 Epic 4.3: "logic-free" campaign dispatch.

Selects `campaign_enrollments` rows that are due, checks consent isn't
revoked (fail closed — a revoked purpose halts a mid-flight campaign,
matching the `consent.revoked` handling in Epic 3.1), and POSTs each
to its campaign `FlowRef`. Crash-safety comes from the same optimistic
`version` column the `campaign_enrollments` migration already carries
(migrations/versions/0001_initial_schema.py): `claim()` is a
compare-and-swap on `version`, so two scheduler ticks racing over the
same row — including "the scheduler crashed after claiming but before
dispatching, then restarted" — can never both dispatch it.

`EnrollmentStore` is a Protocol; the real backing is the Postgres table
above via a plain `UPDATE ... WHERE id = :id AND version = :version`
(no first-party Postgres-repository adapter exists in this codebase
yet, so that binding isn't included here — see README). This module is
the "≈100 lines" of scheduling logic the plan calls "logic-free" — it
has no campaign-specific behavior of its own, only claim/consent-check/
dispatch/settle.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class CampaignEnrollment:
    id: UUID
    tenant_id: UUID
    principal_id: str
    campaign: str  # FlowRef name; also the consent purpose checked before dispatch
    state: str  # "pending" | "in_progress" | "done" | "failed"
    next_action_at: datetime | None
    version: int


class EnrollmentStore(Protocol):
    async def due(self, now: datetime) -> list[CampaignEnrollment]:
        """Rows with state == "pending" and next_action_at <= now."""
        ...

    async def claim(self, enrollment_id: UUID, *, expected_version: int) -> CampaignEnrollment | None:
        """Compare-and-swap: pending + version match -> in_progress,
        version + 1. Returns None if another tick already claimed it
        (version mismatch) or it's no longer pending."""
        ...

    async def complete(self, enrollment_id: UUID, *, expected_version: int) -> None: ...

    async def fail(self, enrollment_id: UUID, *, expected_version: int, reason: str) -> None: ...


class ConsentRegistry(Protocol):
    """Live consent check at dispatch time — NOT the `TenantContext`
    snapshot taken when the enrollment was created, since consent can
    be revoked at any point during a multi-step campaign."""

    async def has_consent(self, tenant_id: UUID, principal_id: str, purpose: str) -> bool: ...


class FlowDispatcher(Protocol):
    async def dispatch(self, enrollment: CampaignEnrollment) -> None:
        """POSTs to the enrollment's campaign FlowRef. Raising signals
        dispatch failure; `FlowScheduler` catches it and marks the row
        failed rather than letting one bad enrollment kill the tick."""
        ...


class InMemoryEnrollmentStore:
    """Same optimistic compare-and-swap semantics as the real Postgres
    table, against a Python dict — for tests and any environment
    without Postgres wired up yet."""

    def __init__(self, enrollments: list[CampaignEnrollment] | None = None) -> None:
        self._rows: dict[UUID, CampaignEnrollment] = {e.id: e for e in (enrollments or [])}

    async def due(self, now: datetime) -> list[CampaignEnrollment]:
        return [
            e
            for e in self._rows.values()
            if e.state == "pending" and e.next_action_at is not None and e.next_action_at <= now
        ]

    async def claim(self, enrollment_id: UUID, *, expected_version: int) -> CampaignEnrollment | None:
        row = self._rows.get(enrollment_id)
        if row is None or row.state != "pending" or row.version != expected_version:
            return None
        claimed = replace(row, state="in_progress", version=row.version + 1)
        self._rows[enrollment_id] = claimed
        return claimed

    async def complete(self, enrollment_id: UUID, *, expected_version: int) -> None:
        row = self._rows.get(enrollment_id)
        if row is None or row.version != expected_version:
            return
        self._rows[enrollment_id] = replace(row, state="done", version=row.version + 1)

    async def fail(self, enrollment_id: UUID, *, expected_version: int, reason: str) -> None:
        row = self._rows.get(enrollment_id)
        if row is None or row.version != expected_version:
            return
        self._rows[enrollment_id] = replace(row, state="failed", version=row.version + 1)


class FlowScheduler:
    def __init__(
        self, store: EnrollmentStore, consent: ConsentRegistry, dispatcher: FlowDispatcher
    ) -> None:
        self._store = store
        self._consent = consent
        self._dispatcher = dispatcher

    async def tick(self, now: datetime) -> None:
        for enrollment in await self._store.due(now):
            claimed = await self._store.claim(enrollment.id, expected_version=enrollment.version)
            if claimed is None:
                continue  # lost the race to another tick/replica — not an error

            if not await self._consent.has_consent(
                claimed.tenant_id, claimed.principal_id, claimed.campaign
            ):
                await self._store.fail(claimed.id, expected_version=claimed.version, reason="consent_revoked")
                continue

            try:
                await self._dispatcher.dispatch(claimed)
            except Exception as exc:  # noqa: BLE001 - one bad enrollment must not kill the tick
                await self._store.fail(claimed.id, expected_version=claimed.version, reason=str(exc))
                continue

            await self._store.complete(claimed.id, expected_version=claimed.version)
