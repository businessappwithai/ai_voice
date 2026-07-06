"""Backing store for the calendar MCP server (Phase 1 Epic 1.3).

Real deployments swap in a CalDAV-backed store behind the same
`CalendarStore` protocol (the plan calls out CalDAV as the calendar
integration); `InMemoryCalendarStore` is the dev/test default and is
enough to exercise the Phase-1 milestone gate's booking demo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Slot:
    slot_id: str
    starts_at: datetime
    ends_at: datetime
    booked_by: str | None = None


class SlotNotFound(Exception):
    def __init__(self, slot_id: str) -> None:
        super().__init__(f"slot {slot_id!r} not found")


class SlotAlreadyBooked(Exception):
    def __init__(self, slot_id: str) -> None:
        super().__init__(f"slot {slot_id!r} is already booked")


class SlotNotBooked(Exception):
    def __init__(self, slot_id: str) -> None:
        super().__init__(f"slot {slot_id!r} is not currently booked")


class CalendarStore(Protocol):
    async def list_available(self, day: datetime) -> list[Slot]: ...

    async def book(self, slot_id: str, booked_by: str) -> Slot: ...

    async def cancel(self, slot_id: str) -> Slot: ...


class InMemoryCalendarStore:
    def __init__(self, slots: list[Slot] | None = None) -> None:
        self._slots: dict[str, Slot] = {s.slot_id: s for s in (slots or [])}

    async def list_available(self, day: datetime) -> list[Slot]:
        return [
            s
            for s in self._slots.values()
            if s.starts_at.date() == day.date() and s.booked_by is None
        ]

    async def book(self, slot_id: str, booked_by: str) -> Slot:
        slot = self._slots.get(slot_id)
        if slot is None:
            raise SlotNotFound(slot_id)
        if slot.booked_by is not None:
            raise SlotAlreadyBooked(slot_id)
        updated = Slot(slot.slot_id, slot.starts_at, slot.ends_at, booked_by=booked_by)
        self._slots[slot_id] = updated
        return updated

    async def cancel(self, slot_id: str) -> Slot:
        slot = self._slots.get(slot_id)
        if slot is None:
            raise SlotNotFound(slot_id)
        if slot.booked_by is None:
            raise SlotNotBooked(slot_id)
        updated = Slot(slot.slot_id, slot.starts_at, slot.ends_at, booked_by=None)
        self._slots[slot_id] = updated
        return updated
