"""Backing store for the twenty-crm MCP server (Phase 4 Epic 4.2).

`CRMStore` is deployment-agnostic on purpose: no HTTP client against
Twenty's actual REST/GraphQL API is included here. Twenty is a fast-
moving open-source project with no stable Python SDK to verify a
client's request/response shapes against, and this environment has no
network path to a running Twenty instance either — writing a specific
endpoint/field-name binding without either of those would mean
shipping a guess at a live external API with false confidence, the
same reasoning that kept a DPDP Consent Manager client out of Epic 3.1
and a `piper-tts` binding out of the Piper adapter. `InMemoryCRMStore`
is the real, tested default; a `TwentyRestCRMStore` implementing this
same protocol against a real Twenty instance is the piece a deployment
with one supplies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class Contact:
    contact_id: str
    name: str
    email: str | None = None
    phone: str | None = None


@dataclass(frozen=True)
class Activity:
    activity_id: str
    contact_id: str
    kind: str  # "booking" | "note"
    detail: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ContactNotFound(Exception):
    def __init__(self, contact_id: str) -> None:
        super().__init__(f"contact {contact_id!r} not found")


class CRMStore(Protocol):
    async def create_contact(
        self, name: str, *, email: str | None = None, phone: str | None = None
    ) -> Contact: ...

    async def log_activity(self, contact_id: str, kind: str, detail: str) -> Activity: ...

    async def activities_for(self, contact_id: str) -> list[Activity]: ...

    async def pipeline_stage(self, contact_id: str) -> str | None:
        """None if the contact isn't in any pipeline yet."""
        ...

    async def set_pipeline_stage(self, contact_id: str, stage: str) -> None: ...


class InMemoryCRMStore:
    def __init__(self) -> None:
        self._contacts: dict[str, Contact] = {}
        self._activities: dict[str, list[Activity]] = {}
        self._pipeline_stages: dict[str, str] = {}

    async def create_contact(
        self, name: str, *, email: str | None = None, phone: str | None = None
    ) -> Contact:
        contact = Contact(contact_id=str(uuid4()), name=name, email=email, phone=phone)
        self._contacts[contact.contact_id] = contact
        return contact

    def _require_contact(self, contact_id: str) -> None:
        if contact_id not in self._contacts:
            raise ContactNotFound(contact_id)

    async def log_activity(self, contact_id: str, kind: str, detail: str) -> Activity:
        self._require_contact(contact_id)
        activity = Activity(activity_id=str(uuid4()), contact_id=contact_id, kind=kind, detail=detail)
        self._activities.setdefault(contact_id, []).append(activity)
        return activity

    async def activities_for(self, contact_id: str) -> list[Activity]:
        self._require_contact(contact_id)
        return list(self._activities.get(contact_id, []))

    async def pipeline_stage(self, contact_id: str) -> str | None:
        self._require_contact(contact_id)
        return self._pipeline_stages.get(contact_id)

    async def set_pipeline_stage(self, contact_id: str, stage: str) -> None:
        self._require_contact(contact_id)
        self._pipeline_stages[contact_id] = stage
