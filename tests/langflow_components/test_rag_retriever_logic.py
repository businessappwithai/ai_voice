from uuid import uuid4

import pytest
from saap.core.fakes import FakeEmbeddingProvider, FakeLLMProvider, FakeReranker, FakeVectorStore
from saap.core.memory import DataClass, DocumentChunk, RAGService
from saap.core.types import TenantContext
from saap.langflow_components.logic.rag_retriever import RAGRetrieverLogic


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


async def test_retrieve_returns_grounded_answer_with_citations(tenant: TenantContext) -> None:
    store = FakeVectorStore()
    rag = RAGService(
        embedder=FakeEmbeddingProvider(), store=store, reranker=FakeReranker(), verifier_llm=FakeLLMProvider()
    )
    chunk = DocumentChunk(
        chunk_id=uuid4(), source_uri="minio://x/handbook.pdf", text="Open 9-5", data_class=DataClass.INTERNAL
    )
    await store.upsert(tenant, [chunk], [[0.0] * 8])

    logic = RAGRetrieverLogic(rag)
    answer = await logic.retrieve(tenant, "what are your hours")
    assert len(answer.citations) == 1
    assert answer.citations[0].source_uri == "minio://x/handbook.pdf"
