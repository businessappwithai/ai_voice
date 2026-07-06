"""SAAP calendar MCP server (Phase 1 Epic 1.3) — the second first-party
server named in the Phase-1 milestone gate: "books a calendar slot
through MCP (auto-allowed write in business hours)".

Exposes exactly three tools — `list_slots`, `book_slot`, `cancel_slot`
— matching the static per-tenant allow-list contract in
`saap.core.mcp.MCPServerConfig` (never `*`). Tool results are always
`{"ok": bool, ...}` so `MCPToolkitLogic`'s dispatch path never needs a
try/except around a raised server-side exception.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP
from store import (
    CalendarStore,
    InMemoryCalendarStore,
    SlotAlreadyBooked,
    SlotNotBooked,
    SlotNotFound,
)


def build_server(store: CalendarStore | None = None) -> FastMCP:
    store = store or InMemoryCalendarStore()
    server: FastMCP = FastMCP(name="calendar")

    @server.tool(description="List available appointment slots for a given ISO 8601 date")
    async def list_slots(date: str) -> dict[str, Any]:
        day = datetime.fromisoformat(date)
        slots = await store.list_available(day)
        return {
            "ok": True,
            "slots": [
                {"slot_id": s.slot_id, "starts_at": s.starts_at.isoformat(), "ends_at": s.ends_at.isoformat()}
                for s in slots
            ],
        }

    @server.tool(description="Book an appointment slot for a named principal")
    async def book_slot(slot_id: str, booked_by: str) -> dict[str, Any]:
        try:
            slot = await store.book(slot_id, booked_by)
        except SlotNotFound as exc:
            return {"ok": False, "error": str(exc)}
        except SlotAlreadyBooked as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "slot_id": slot.slot_id, "booked_by": slot.booked_by}

    @server.tool(description="Cancel a previously booked appointment slot")
    async def cancel_slot(slot_id: str) -> dict[str, Any]:
        try:
            slot = await store.cancel(slot_id)
        except SlotNotFound as exc:
            return {"ok": False, "error": str(exc)}
        except SlotNotBooked as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "slot_id": slot.slot_id}

    return server


if __name__ == "__main__":
    build_server().run()
