from saap.core.fakes import FakeEmbeddingProvider, FakeLLMProvider, FakeReranker, FakeVectorStore
from saap.core.memory import RAGService
from saap.langflow_components.logic.grounded_responder import FALLBACK_TEXT, GroundedResponderLogic


def _logic(*, verifier_next_json: str | None = None) -> GroundedResponderLogic:
    rag = RAGService(
        embedder=FakeEmbeddingProvider(),
        store=FakeVectorStore(),
        reranker=FakeReranker(),
        verifier_llm=FakeLLMProvider(next_json=verifier_next_json),
    )
    return GroundedResponderLogic(rag)


async def test_grounded_answer_passes_through() -> None:
    # A citation marker alone only clears the cheap structural check;
    # verify_grounding also asks the verifier LLM whether the cited
    # chunk actually entails the claim, so the fake must be scripted
    # to return a positive entailment judgment.
    logic = _logic(verifier_next_json='{"supported": true}')
    # The citation marker must land inside the sentence (before the
    # terminal period) — "text [1]." — not after it, since sentence
    # splitting happens on ". " and a marker in its own trailing
    # fragment wouldn't count as attached to the claim it supports.
    reply = await logic.respond("Office hours are 9-5 [1].", context_block="[1] Office hours are 9-5.")
    assert reply.grounded is True
    assert reply.text == "Office hours are 9-5 [1]."


async def test_ungrounded_answer_is_replaced_with_fallback() -> None:
    logic = _logic()
    reply = await logic.respond("This sentence has no citation at all.", context_block="[1] Unrelated fact.")
    assert reply.grounded is False
    assert reply.text == FALLBACK_TEXT
    assert len(reply.ungrounded_spans) >= 1


async def test_cited_but_unsupported_claim_is_replaced_with_fallback() -> None:
    """A citation marker is present, but the verifier LLM judges the
    cited chunk doesn't actually support the claim — must still fail,
    not just check for marker presence."""
    logic = _logic(verifier_next_json='{"supported": false}')
    reply = await logic.respond("The clinic offers free parking [1].", context_block="[1] Office hours are 9-5.")
    assert reply.grounded is False
    assert reply.text == FALLBACK_TEXT
