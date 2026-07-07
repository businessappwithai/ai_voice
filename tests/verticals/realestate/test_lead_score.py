import json

import pytest
from saap.core.fakes import FakeLLMProvider
from saap.verticals.realestate.lead_score import (
    LeadScoreExtractionError,
    LeadScoreExtractorLogic,
    LeadScoreFields,
    score_lead,
)


def _fake_provider(fields: dict) -> FakeLLMProvider:
    # `responses` is deliberately not valid JSON: FakeLLMProvider only
    # returns `next_json` when `config.json_schema` is set, so a
    # successful extract() proves the constrained-decoding path was
    # actually requested, not just that any text came back.
    return FakeLLMProvider(responses=("not valid json",), next_json=json.dumps(fields))


async def test_extract_parses_valid_constrained_output() -> None:
    provider = _fake_provider(
        {"budget": 500000, "timeline": "immediate", "preapproved": True, "bedrooms": 3}
    )
    extractor = LeadScoreExtractorLogic(provider, model="qwen2.5:3b")

    fields = await extractor.extract("I need a 3BR, pre-approved, ready to move now.")

    assert fields == LeadScoreFields(
        budget=500000, timeline="immediate", preapproved=True, bedrooms=3
    )


async def test_extract_handles_all_fields_undisclosed() -> None:
    provider = _fake_provider(
        {"budget": None, "timeline": None, "preapproved": None, "bedrooms": None}
    )
    extractor = LeadScoreExtractorLogic(provider, model="qwen2.5:3b")

    fields = await extractor.extract("just browsing")

    assert fields == LeadScoreFields()


async def test_extract_raises_on_non_json_output() -> None:
    provider = FakeLLMProvider(responses=("still not json",), next_json="not json either")
    extractor = LeadScoreExtractorLogic(provider, model="qwen2.5:3b")

    with pytest.raises(LeadScoreExtractionError):
        await extractor.extract("anything")


async def test_extract_raises_when_schema_validation_fails() -> None:
    # budget as a string, not an int -> fails LeadScoreFields validation
    # even though it IS valid JSON.
    provider = _fake_provider({"budget": "lots", "timeline": None, "preapproved": None, "bedrooms": None})
    extractor = LeadScoreExtractorLogic(provider, model="qwen2.5:3b")

    with pytest.raises(LeadScoreExtractionError):
        await extractor.extract("anything")


def test_score_lead_hot_when_preapproved_immediate_with_budget() -> None:
    fields = LeadScoreFields(budget=500000, timeline="immediate", preapproved=True, bedrooms=3)
    assert score_lead(fields) == "hot"


def test_score_lead_warm_when_budget_disclosed_but_not_immediate() -> None:
    fields = LeadScoreFields(budget=500000, timeline="6mo+", preapproved=False, bedrooms=2)
    assert score_lead(fields) == "warm"


def test_score_lead_warm_when_timeline_is_near_term_without_budget() -> None:
    fields = LeadScoreFields(budget=None, timeline="1-3mo", preapproved=None, bedrooms=None)
    assert score_lead(fields) == "warm"


def test_score_lead_cold_when_nothing_disclosed() -> None:
    assert score_lead(LeadScoreFields()) == "cold"


def test_score_lead_cold_when_preapproved_but_no_budget_or_timeline() -> None:
    fields = LeadScoreFields(budget=None, timeline=None, preapproved=True, bedrooms=4)
    assert score_lead(fields) == "cold"
