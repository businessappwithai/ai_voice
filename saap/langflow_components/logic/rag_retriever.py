"""Framework-agnostic logic behind the `RAGRetriever` canvas component
— tenant-scoped hybrid retrieve + rerank, outputting cited context for
the downstream `GroundedResponder`."""
from __future__ import annotations

from saap.core.memory import GroundedAnswer, RAGService
from saap.core.types import TenantContext


class RAGRetrieverLogic:
    def __init__(self, rag: RAGService) -> None:
        self._rag = rag

    async def retrieve(self, tenant: TenantContext, query: str) -> GroundedAnswer:
        return await self._rag.answer(tenant, query)
