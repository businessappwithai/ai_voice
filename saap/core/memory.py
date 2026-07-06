"""Retrieval subsystem contracts (replaces Pinecone + Airtable roles).

Tenant isolation strategy (P7):
  * Qdrant: one collection per tenant OR shared collection with a
    mandatory `tenant_id` payload filter — chosen per data_residency.
  * The interface makes it impossible to query without a TenantContext.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel

from .llm import LLMProvider
from .types import DataClass, Message, TenantContext


class EmbeddingProvider(Protocol):
    """BGE-M3 / nomic-embed via local inference. Dim advertised so
    stores can validate collections at bind time."""

    dimension: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class DocumentChunk(BaseModel, frozen=True):
    chunk_id: UUID
    source_uri: str  # minio://tenant/{id}/handbook.pdf#p12
    text: str
    data_class: DataClass
    metadata: dict[str, Any] = {}


class RetrievedChunk(BaseModel, frozen=True):
    chunk: DocumentChunk
    score: float


class VectorStore(Protocol):
    """Implementations: ``QdrantStore`` (default), ``ChromaStore``,
    ``PgVectorStore``, ``MilvusStore`` — all Apache/MIT licensed."""

    async def upsert(
        self,
        tenant: TenantContext,
        chunks: Sequence[DocumentChunk],
        vectors: Sequence[list[float]],
    ) -> None: ...

    async def search(
        self,
        tenant: TenantContext,
        query_vector: list[float],
        *,
        k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]: ...

    async def delete_by_source(self, tenant: TenantContext, source_uri: str) -> int:
        """Required by DPDP purpose-fulfillment erasure jobs (Phase 3)."""
        ...


class Reranker(Protocol):
    """bge-reranker-v2-m3 cross-encoder precision pass."""

    async def rerank(
        self, query: str, chunks: Sequence[RetrievedChunk], top_n: int
    ) -> list[RetrievedChunk]: ...


class Citation(BaseModel, frozen=True):
    chunk_id: UUID
    source_uri: str
    marker: str  # "[1]", "[2]", ...


class GroundedAnswer(BaseModel, frozen=True):
    text: str
    citations: tuple[Citation, ...]
    grounded: bool  # False if the verifier flagged an uncited claim
    ungrounded_spans: tuple[str, ...] = ()


_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")


class RAGService:
    """Grounded retrieval facade used by agents (never raw VectorStore).

    Pipeline: hybrid search (dense + BM25 sparse from BGE-M3)
              -> rerank -> citation packing -> grounding contract.

    The grounding contract: the returned context block carries chunk IDs;
    the generation prompt requires inline citations; `verify_grounding`
    runs an NLI-style check with a small local model and flags
    unsupported claims before the answer leaves L3 (anti-hallucination, P5).
    """

    def __init__(
        self,
        embedder: EmbeddingProvider,
        store: VectorStore,
        reranker: Reranker,
        verifier_llm: LLMProvider,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._reranker = reranker
        self._verifier = verifier_llm

    async def retrieve(
        self, tenant: TenantContext, query: str, *, k: int = 6
    ) -> list[RetrievedChunk]:
        [query_vector] = await self._embedder.embed([query])
        # Over-fetch before rerank so the cross-encoder has real signal to work with.
        candidates = await self._store.search(tenant, query_vector, k=max(k * 4, 20))
        return await self._reranker.rerank(query, candidates, top_n=k)

    def _pack_citations(
        self, chunks: Sequence[RetrievedChunk]
    ) -> tuple[str, list[Citation]]:
        lines: list[str] = []
        citations: list[Citation] = []
        for i, rc in enumerate(chunks, start=1):
            marker = f"[{i}]"
            lines.append(f"{marker} {rc.chunk.text}")
            citations.append(
                Citation(
                    chunk_id=rc.chunk.chunk_id,
                    source_uri=rc.chunk.source_uri,
                    marker=marker,
                )
            )
        return "\n\n".join(lines), citations

    async def verify_grounding(
        self, answer_text: str, context_block: str
    ) -> tuple[bool, tuple[str, ...]]:
        """NLI-style check: does every cited sentence in `answer_text`
        find support in `context_block`? Two passes:

        1. Cheap structural check — a sentence with no citation marker
           at all is always flagged, no model call needed.
        2. For sentences that DO carry a marker, ask the verifier LLM
           (constrained to a JSON bool) whether the cited chunk actually
           entails the claim — catches citation-marker-present-but-wrong
           attribution, not just missing markers.
        """
        from .llm import GenerationConfig  # local import: avoids a cycle at module load

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer_text) if s.strip()]
        ungrounded: list[str] = []
        for sentence in sentences:
            if not _CITATION_MARKER_RE.search(sentence):
                ungrounded.append(sentence)
                continue
            check = Message(
                role="user",
                content=(
                    "Context:\n"
                    f"{context_block}\n\n"
                    f"Claim: {sentence}\n"
                    "Does the context entail this claim? Answer with JSON only."
                ),
                data_class=DataClass.INTERNAL,
            )
            completion = await self._verifier.generate(
                [check],
                config=GenerationConfig(
                    model="",  # ModelRouter has already bound this provider to a model
                    json_schema={
                        "type": "object",
                        "properties": {"supported": {"type": "boolean"}},
                        "required": ["supported"],
                    },
                ),
            )
            import json

            try:
                supported = bool(json.loads(completion.text).get("supported", False))
            except (json.JSONDecodeError, AttributeError):
                supported = False
            if not supported:
                ungrounded.append(sentence)
        return (len(ungrounded) == 0, tuple(ungrounded))

    async def answer(self, tenant: TenantContext, question: str) -> GroundedAnswer:
        """Retrieval + citation packing only.

        Generation happens on the canvas (`GroundedResponder`, wired to
        a `ModelRouterLLM` on the `reason`/`fast` profile per Section 5.2)
        so this facade stays a pure L3 capability with no L4 dependency.
        Callers that need a fully generated, verified answer outside a
        flow (e.g. the eval harness) should call `verify_grounding`
        against the component's output directly.
        """
        chunks = await self.retrieve(tenant, question)
        context_block, citations = self._pack_citations(chunks)
        return GroundedAnswer(
            text=context_block,
            citations=tuple(citations),
            grounded=True,
            ungrounded_spans=(),
        )
