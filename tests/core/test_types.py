import pytest
from pydantic import ValidationError
from saap.core.types import DataClass, Locale, Message, TenantContext, ToolCall, ToolResult


def test_tenant_context_requires_tenant_id() -> None:
    with pytest.raises(ValidationError):
        TenantContext(vertical="dental")  # type: ignore[call-arg]


def test_tenant_context_is_frozen() -> None:
    from uuid import uuid4

    tenant = TenantContext(tenant_id=uuid4(), vertical="dental")
    with pytest.raises(ValidationError):
        tenant.vertical = "realestate"  # type: ignore[misc]


def test_tenant_context_has_consent() -> None:
    from uuid import uuid4

    tenant = TenantContext(
        tenant_id=uuid4(), vertical="dental", consent_scope=frozenset({"marketing"})
    )
    assert tenant.has_consent("marketing")
    assert not tenant.has_consent("billing")


def test_message_default_data_class_is_personal() -> None:
    msg = Message(role="user", content="hi")
    assert msg.data_class == DataClass.PERSONAL


def test_message_is_frozen() -> None:
    msg = Message(role="user", content="hi")
    with pytest.raises(ValidationError):
        msg.content = "bye"  # type: ignore[misc]


def test_tool_call_default_risk_tier_is_read() -> None:
    call = ToolCall(call_id="1", tool_name="mcp.crm.get_contact", arguments={})
    assert call.risk_tier == "read"


def test_tool_result_frozen() -> None:
    result = ToolResult(call_id="1", ok=True, content={"a": 1})
    with pytest.raises(ValidationError):
        result.ok = False  # type: ignore[misc]


def test_locale_enum_members() -> None:
    assert Locale.EN_IN == "en-IN"
    assert Locale.TA_IN == "ta-IN"
