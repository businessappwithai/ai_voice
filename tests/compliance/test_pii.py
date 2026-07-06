from uuid import uuid4

import pytest
from saap.compliance.chain import Envelope
from saap.compliance.pii import PIIMaskingInterceptor, SimplePIIAnalyzer, TokenVault
from saap.core.types import DataClass, Message, TenantContext


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


def test_token_vault_roundtrip() -> None:
    vault = TokenVault()
    token = vault.tokenize("IN_AADHAAR", "1234 5678 9012")
    assert token.startswith("<IN_AADHAAR_")
    assert vault.resolve(token) == "1234 5678 9012"


def test_token_vault_unknown_token_resolves_to_none() -> None:
    vault = TokenVault()
    assert vault.resolve("<IN_AADHAAR_deadbeef>") is None


def test_token_vault_destroy_all_is_crypto_shredding() -> None:
    vault = TokenVault()
    token = vault.tokenize("IN_PAN", "ABCDE1234F")
    vault.destroy_all()
    assert vault.resolve(token) is None


async def test_masking_interceptor_masks_aadhaar_and_phone(tenant: TenantContext) -> None:
    vault = TokenVault()
    interceptor = PIIMaskingInterceptor(SimplePIIAnalyzer(), vault)
    envelope = Envelope(
        tenant,
        Message(
            role="user",
            content="Book Ramesh, Aadhaar 1234 5678 9012, phone 9876543210",
            data_class=DataClass.PERSONAL,
        ),
    )
    result = await interceptor.before(tenant, envelope)
    assert "1234 5678 9012" not in result.message.content
    assert "9876543210" not in result.message.content
    assert "<IN_AADHAAR_" in result.message.content
    assert "<IN_PHONE_" in result.message.content


async def test_masking_interceptor_skips_public_data_class(tenant: TenantContext) -> None:
    vault = TokenVault()
    interceptor = PIIMaskingInterceptor(SimplePIIAnalyzer(), vault)
    envelope = Envelope(
        tenant,
        Message(role="user", content="Aadhaar 1234 5678 9012", data_class=DataClass.PUBLIC),
    )
    result = await interceptor.before(tenant, envelope)
    assert result.message.content == "Aadhaar 1234 5678 9012"


async def test_resolve_for_tool_reinjects_real_values(tenant: TenantContext) -> None:
    vault = TokenVault()
    interceptor = PIIMaskingInterceptor(SimplePIIAnalyzer(), vault)
    envelope = Envelope(
        tenant,
        Message(role="user", content="Aadhaar 1234 5678 9012", data_class=DataClass.PERSONAL),
    )
    masked = await interceptor.before(tenant, envelope)
    resolved = interceptor.resolve_for_tool(tenant, {"note": masked.message.content})
    assert resolved["note"] == "Aadhaar 1234 5678 9012"
