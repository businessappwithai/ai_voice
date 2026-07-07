"""LeadScoreExtractor — Phase 5 Epic 5.2 (real estate vertical pack):
grammar-constrained extraction of {budget, timeline, preapproved,
bedrooms} from a lead's free-text conversation, so speed-to-lead
routing (hot/warm/cold) is a pure function of validated structured
fields rather than a hopeful regex over prose.

Relies on the `LLMProvider` contract's `json_schema` guarantee (see
saap/core/llm.py: "If config.json_schema is set, output MUST validate
against it") — grammar-constrained decoding is a provider
responsibility, this component never retries or coerces malformed
output, and raises loudly if a provider violates that contract instead
of silently guessing.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError
from saap.core.llm import GenerationConfig, LLMProvider
from saap.core.types import Message


class LeadScoreFields(BaseModel, frozen=True):
    budget: int | None = None  # local currency units; None = not disclosed
    timeline: str | None = None  # "immediate" | "1-3mo" | "3-6mo" | "6mo+" | None
    preapproved: bool | None = None
    bedrooms: int | None = None


LEAD_SCORE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "budget": {"type": ["integer", "null"]},
        "timeline": {"type": ["string", "null"]},
        "preapproved": {"type": ["boolean", "null"]},
        "bedrooms": {"type": ["integer", "null"]},
    },
    "required": ["budget", "timeline", "preapproved", "bedrooms"],
}

_EXTRACTION_PROMPT = (
    "Extract the lead's budget (integer, local currency units), "
    'timeline ("immediate"|"1-3mo"|"3-6mo"|"6mo+"), whether they are '
    "mortgage pre-approved (boolean), and desired bedroom count "
    "(integer) from this conversation. Use null for any field not "
    "disclosed.\n\nConversation:\n{conversation}"
)


class LeadScoreExtractionError(Exception):
    """The model's output didn't validate against `LeadScoreFields`
    even though `json_schema` was requested — the `LLMProvider`
    contract requires honoring `json_schema` via grammar-constrained
    decoding, so this should only fire against a provider that's
    violating its own contract."""


class LeadScoreExtractorLogic:
    def __init__(self, provider: LLMProvider, *, model: str) -> None:
        self._provider = provider
        self._model = model

    async def extract(self, conversation: str) -> LeadScoreFields:
        message = Message(role="user", content=_EXTRACTION_PROMPT.format(conversation=conversation))
        completion = await self._provider.generate(
            [message],
            config=GenerationConfig(model=self._model, json_schema=LEAD_SCORE_JSON_SCHEMA),
        )
        try:
            return LeadScoreFields.model_validate(json.loads(completion.text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LeadScoreExtractionError(
                f"constrained output failed schema validation: {completion.text!r}"
            ) from exc


def score_lead(fields: LeadScoreFields) -> str:
    """"hot" / "warm" / "cold" per the plan's worked example (§13):
    pre-approved buyers with a disclosed budget and an immediate
    timeline are exactly the segment speed-to-lead response time wins
    or loses."""
    if fields.preapproved and fields.timeline == "immediate" and fields.budget:
        return "hot"
    if fields.budget or fields.timeline in ("immediate", "1-3mo"):
        return "warm"
    return "cold"
