from uuid import uuid4

import pytest
from saap.compliance.chain import Envelope
from saap.compliance.pii import (
    ICD10_RE,
    PIIMaskingInterceptor,
    SimplePIIAnalyzer,
    TokenVault,
    build_vertical_recognizers,
)
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


# --- ICD-10 vertical recognizer (Epic 5.1) ----------------------------------


@pytest.mark.parametrize("code", ["F32.9", "E11.9", "Z00.00", "S72.001A", "A00"])
def test_icd10_regex_matches_real_codes(code: str) -> None:
    assert ICD10_RE.fullmatch(code)


@pytest.mark.parametrize("token", ["U07.1", "hello", "12.34", "AB1.2"])
def test_icd10_regex_rejects_non_icd_tokens(token: str) -> None:
    # U-prefixed codes are reserved for provisional WHO codes, not
    # ICD-10-CM proper; plain words/numeric-only/two-letter-prefixed
    # tokens must not false-positive as diagnosis codes.
    assert not ICD10_RE.fullmatch(token)


def test_build_vertical_recognizers_for_dental_returns_one_recognizer() -> None:
    recognizers = build_vertical_recognizers("dental")
    assert len(recognizers) == 1
    assert recognizers[0].supported_entities == ["ICD10"]


def test_build_vertical_recognizers_for_unknown_vertical_is_empty() -> None:
    assert build_vertical_recognizers("realestate") == []


def test_simple_pii_analyzer_without_vertical_ignores_icd10_codes() -> None:
    analyzer = SimplePIIAnalyzer()
    entities = analyzer.analyze("Diagnosis: F32.9, follow-up in 6 weeks")
    assert entities == []


def test_simple_pii_analyzer_with_dental_vertical_detects_icd10() -> None:
    analyzer = SimplePIIAnalyzer(vertical="dental")
    entities = analyzer.analyze("Diagnosis: F32.9, follow-up in 6 weeks")
    assert [e.entity_type for e in entities] == ["ICD10"]
    assert entities[0].text == "F32.9"


def test_simple_pii_analyzer_with_healthcare_vertical_detects_icd10() -> None:
    analyzer = SimplePIIAnalyzer(vertical="healthcare")
    entities = analyzer.analyze("code E11.9 noted")
    assert [e.entity_type for e in entities] == ["ICD10"]


def test_simple_pii_analyzer_with_unrecognized_vertical_has_no_extra_patterns() -> None:
    analyzer = SimplePIIAnalyzer(vertical="realestate")
    entities = analyzer.analyze("Diagnosis: F32.9")
    assert entities == []


async def test_masking_interceptor_masks_icd10_for_dental_vertical(tenant: TenantContext) -> None:
    vault = TokenVault()
    interceptor = PIIMaskingInterceptor(SimplePIIAnalyzer(vertical="dental"), vault)
    envelope = Envelope(
        tenant,
        Message(role="user", content="Patient diagnosis F32.9", data_class=DataClass.SENSITIVE_PERSONAL),
    )
    result = await interceptor.before(tenant, envelope)
    assert "F32.9" not in result.message.content
    assert "<ICD10_" in result.message.content
