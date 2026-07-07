import pytest

from tests.mcp_servers._loader import load_server_module

store_module = load_server_module("twenty-crm", "store.py")
server_module = load_server_module("twenty-crm", "server.py")

ContactNotFound = store_module.ContactNotFound
InMemoryCRMStore = store_module.InMemoryCRMStore
build_server = server_module.build_server


# --- store unit tests --------------------------------------------------------


async def test_create_contact_assigns_an_id() -> None:
    store = InMemoryCRMStore()
    contact = await store.create_contact("Ramesh Kumar", email="ramesh@example.com")
    assert contact.name == "Ramesh Kumar"
    assert contact.contact_id


async def test_log_activity_unknown_contact_raises() -> None:
    store = InMemoryCRMStore()
    with pytest.raises(ContactNotFound):
        await store.log_activity("nope", "note", "called about pricing")


async def test_activities_for_returns_in_order() -> None:
    store = InMemoryCRMStore()
    contact = await store.create_contact("Priya")
    await store.log_activity(contact.contact_id, "note", "first call")
    await store.log_activity(contact.contact_id, "note", "second call")
    activities = await store.activities_for(contact.contact_id)
    assert [a.detail for a in activities] == ["first call", "second call"]


async def test_pipeline_stage_defaults_to_none() -> None:
    store = InMemoryCRMStore()
    contact = await store.create_contact("Priya")
    assert await store.pipeline_stage(contact.contact_id) is None


async def test_set_pipeline_stage_updates_it() -> None:
    store = InMemoryCRMStore()
    contact = await store.create_contact("Priya")
    await store.set_pipeline_stage(contact.contact_id, "qualified")
    assert await store.pipeline_stage(contact.contact_id) == "qualified"


# --- real FastMCP server round-trip -----------------------------------------


async def test_server_exposes_exactly_four_tools() -> None:
    server = build_server(InMemoryCRMStore())
    tools = await server.list_tools()
    assert {t.name for t in tools} == {"create_contact", "book_slot", "log_activity", "pipelines"}


async def test_server_create_contact_tool() -> None:
    server = build_server(InMemoryCRMStore())
    _content, payload = await server.call_tool("create_contact", {"name": "Ramesh Kumar"})
    assert payload["ok"] is True
    assert payload["name"] == "Ramesh Kumar"


async def test_server_book_slot_tool_success() -> None:
    store = InMemoryCRMStore()
    contact = await store.create_contact("Ramesh Kumar")
    server = build_server(store)
    _content, payload = await server.call_tool(
        "book_slot",
        {
            "contact_id": contact.contact_id,
            "starts_at": "2026-07-08T10:00:00",
            "ends_at": "2026-07-08T10:30:00",
            "title": "Cleaning appointment",
        },
    )
    assert payload["ok"] is True
    activities = await store.activities_for(contact.contact_id)
    assert activities[0].kind == "booking"


async def test_server_book_slot_tool_unknown_contact() -> None:
    server = build_server(InMemoryCRMStore())
    _content, payload = await server.call_tool(
        "book_slot",
        {"contact_id": "nope", "starts_at": "x", "ends_at": "y", "title": "z"},
    )
    assert payload["ok"] is False


async def test_server_log_activity_tool_success() -> None:
    store = InMemoryCRMStore()
    contact = await store.create_contact("Ramesh Kumar")
    server = build_server(store)
    _content, payload = await server.call_tool(
        "log_activity", {"contact_id": contact.contact_id, "detail": "asked about pricing"}
    )
    assert payload["ok"] is True
    activities = await store.activities_for(contact.contact_id)
    assert activities[0].kind == "note"
    assert activities[0].detail == "asked about pricing"


async def test_server_pipelines_tool_returns_none_stage_by_default() -> None:
    store = InMemoryCRMStore()
    contact = await store.create_contact("Ramesh Kumar")
    server = build_server(store)
    _content, payload = await server.call_tool("pipelines", {"contact_id": contact.contact_id})
    assert payload == {"ok": True, "contact_id": contact.contact_id, "stage": None}


async def test_server_pipelines_tool_unknown_contact() -> None:
    server = build_server(InMemoryCRMStore())
    _content, payload = await server.call_tool("pipelines", {"contact_id": "nope"})
    assert payload["ok"] is False
