"""SAAP twenty-crm MCP server (Phase 4 Epic 4.2) — `create_contact`,
`book_slot`, `log_activity`, `pipelines`, matching the plan's tool set
so agents stay CRM-agnostic (a vertical flow calls these tool names
regardless of which CRM backs a given deployment).

`book_slot` here logs a CRM-side activity record for an appointment
(the CRM's own timeline of what was booked) — it is a distinct concern
from the `calendar` MCP server's actual slot authority (Epic 1.3):
a real vertical flow calls `calendar.book_slot` to reserve the slot and
`twenty-crm.book_slot` to record it against the contact's CRM history.

Tool results are always `{"ok": bool, ...}`, matching the calendar
server's convention, so `MCPToolkitLogic`'s dispatch path never needs
a try/except around a raised server-side exception.
"""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from store import ContactNotFound, CRMStore, InMemoryCRMStore


def build_server(store: CRMStore | None = None) -> FastMCP:
    store = store or InMemoryCRMStore()
    server: FastMCP = FastMCP(name="twenty-crm")

    @server.tool(description="Create a CRM contact")
    async def create_contact(name: str, email: str | None = None, phone: str | None = None) -> dict[str, Any]:
        contact = await store.create_contact(name, email=email, phone=phone)
        return {"ok": True, "contact_id": contact.contact_id, "name": contact.name}

    @server.tool(description="Log an appointment booking against a contact's CRM timeline")
    async def book_slot(contact_id: str, starts_at: str, ends_at: str, title: str) -> dict[str, Any]:
        try:
            activity = await store.log_activity(
                contact_id, "booking", f"{title} | {starts_at} - {ends_at}"
            )
        except ContactNotFound as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "activity_id": activity.activity_id, "contact_id": contact_id}

    @server.tool(description="Log a free-text activity note against a contact")
    async def log_activity(contact_id: str, detail: str) -> dict[str, Any]:
        try:
            activity = await store.log_activity(contact_id, "note", detail)
        except ContactNotFound as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "activity_id": activity.activity_id, "contact_id": contact_id}

    @server.tool(description="Get a contact's current sales/service pipeline stage")
    async def pipelines(contact_id: str) -> dict[str, Any]:
        try:
            stage = await store.pipeline_stage(contact_id)
        except ContactNotFound as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "contact_id": contact_id, "stage": stage}

    return server


if __name__ == "__main__":
    build_server().run()
