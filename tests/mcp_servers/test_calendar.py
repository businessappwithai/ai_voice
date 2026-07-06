from datetime import datetime, timedelta

import pytest

from tests.mcp_servers._loader import load_server_module

store_module = load_server_module("calendar", "store.py")
server_module = load_server_module("calendar", "server.py")

InMemoryCalendarStore = store_module.InMemoryCalendarStore
Slot = store_module.Slot
SlotAlreadyBooked = store_module.SlotAlreadyBooked
SlotNotBooked = store_module.SlotNotBooked
SlotNotFound = store_module.SlotNotFound
build_server = server_module.build_server


def _slot(hour: int, *, booked_by: str | None = None) -> "Slot":
    day = datetime(2026, 7, 6, hour, 0)
    return Slot(slot_id=f"slot-{hour}", starts_at=day, ends_at=day + timedelta(minutes=30), booked_by=booked_by)


# --- store unit tests --------------------------------------------------------


async def test_list_available_excludes_booked_slots() -> None:
    store = InMemoryCalendarStore([_slot(9), _slot(10, booked_by="ramesh")])
    available = await store.list_available(datetime(2026, 7, 6))
    assert [s.slot_id for s in available] == ["slot-9"]


async def test_book_marks_slot_booked() -> None:
    store = InMemoryCalendarStore([_slot(9)])
    slot = await store.book("slot-9", "ramesh")
    assert slot.booked_by == "ramesh"


async def test_book_unknown_slot_raises() -> None:
    store = InMemoryCalendarStore([])
    with pytest.raises(SlotNotFound):
        await store.book("nope", "ramesh")


async def test_book_already_booked_slot_raises() -> None:
    store = InMemoryCalendarStore([_slot(9, booked_by="priya")])
    with pytest.raises(SlotAlreadyBooked):
        await store.book("slot-9", "ramesh")


async def test_cancel_frees_slot() -> None:
    store = InMemoryCalendarStore([_slot(9, booked_by="ramesh")])
    slot = await store.cancel("slot-9")
    assert slot.booked_by is None


async def test_cancel_not_booked_slot_raises() -> None:
    store = InMemoryCalendarStore([_slot(9)])
    with pytest.raises(SlotNotBooked):
        await store.cancel("slot-9")


async def test_cancel_unknown_slot_raises() -> None:
    store = InMemoryCalendarStore([])
    with pytest.raises(SlotNotFound):
        await store.cancel("nope")


# --- real FastMCP server round-trip -----------------------------------------


async def test_server_exposes_exactly_three_tools() -> None:
    server = build_server(InMemoryCalendarStore([_slot(9)]))
    tools = await server.list_tools()
    assert {t.name for t in tools} == {"list_slots", "book_slot", "cancel_slot"}


async def test_server_list_slots_tool() -> None:
    # call_tool returns (content_blocks, structured_dict) when the tool
    # function declares a dict return type; structured_dict is already
    # the parsed payload, no need to re-parse the TextContent JSON.
    server = build_server(InMemoryCalendarStore([_slot(9)]))
    _content, payload = await server.call_tool("list_slots", {"date": "2026-07-06"})
    assert payload["ok"] is True
    assert len(payload["slots"]) == 1


async def test_server_book_slot_tool_success() -> None:
    server = build_server(InMemoryCalendarStore([_slot(9)]))
    _content, payload = await server.call_tool("book_slot", {"slot_id": "slot-9", "booked_by": "ramesh"})
    assert payload == {"ok": True, "slot_id": "slot-9", "booked_by": "ramesh"}


async def test_server_book_slot_tool_not_found() -> None:
    server = build_server(InMemoryCalendarStore([]))
    _content, payload = await server.call_tool("book_slot", {"slot_id": "nope", "booked_by": "ramesh"})
    assert payload["ok"] is False


async def test_server_cancel_slot_tool_success() -> None:
    server = build_server(InMemoryCalendarStore([_slot(9, booked_by="ramesh")]))
    _content, payload = await server.call_tool("cancel_slot", {"slot_id": "slot-9"})
    assert payload == {"ok": True, "slot_id": "slot-9"}
