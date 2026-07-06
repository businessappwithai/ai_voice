"""Framework-agnostic logic behind the `GroundedResponder` sealed canvas
component. Blocks uncited claims before they reach Chat Output — the
canvas-side half of the RAG grounding contract (`saap.core.memory.RAGService`).
"""
from __future__ import annotations

from dataclasses import dataclass

from saap.core.memory import RAGService

FALLBACK_TEXT = (
    "I don't have enough grounded information from your documents to answer that confidently. "
    "Let me connect you with someone who can help."
)


@dataclass(frozen=True)
class GroundedReply:
    text: str
    grounded: bool
    ungrounded_spans: tuple[str, ...] = ()


class GroundedResponderLogic:
    def __init__(self, rag: RAGService) -> None:
        self._rag = rag

    async def respond(self, answer_text: str, context_block: str) -> GroundedReply:
        grounded, ungrounded_spans = await self._rag.verify_grounding(answer_text, context_block)
        if grounded:
            return GroundedReply(text=answer_text, grounded=True)
        # Never let an unsupported claim reach the end user (P5) — swap
        # in the safe fallback rather than emitting a partially-grounded
        # answer with no way for the caller to tell which parts to trust.
        return GroundedReply(text=FALLBACK_TEXT, grounded=False, ungrounded_spans=ungrounded_spans)
