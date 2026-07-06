from uuid import uuid4

import pytest
from saap.core.fakes import FakeEmbeddingProvider, FakeLLMProvider, FakeReranker, FakeVectorStore
from saap.core.memory import DataClass, DocumentChunk, RAGService
from saap.core.types import TenantContext


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


@pytest.fixture
def rag(tenant: TenantContext) -> RAGService:
    return RAGService(
        embedder=FakeEmbeddingProvider(),
        store=FakeVectorStore(),
        reranker=FakeReranker(),
        verifier_llm=FakeLLMProvider(),
    )


async def test_retrieve_returns_upserted_chunks(rag: RAGService, tenant: TenantContext) -> None:
    chunk = DocumentChunk(
        chunk_id=uuid4(),
        source_uri="minio://tenant/handbook.pdf#p1",
        text="Office hours are 9am-5pm.",
        data_class=DataClass.INTERNAL,
    )
    await rag._store.upsert(tenant, [chunk], [[0.0] * 8])

    results = await rag.retrieve(tenant, "what are your hours?")
    assert len(results) == 1
    assert results[0].chunk.chunk_id == chunk.chunk_id


async def test_delete_by_source_is_exact(rag: RAGService, tenant: TenantContext) -> None:
    kept = DocumentChunk(
        chunk_id=uuid4(), source_uri="minio://tenant/a.pdf", text="a", data_class=DataClass.INTERNAL
    )
    removed = DocumentChunk(
        chunk_id=uuid4(), source_uri="minio://tenant/b.pdf", text="b", data_class=DataClass.INTERNAL
    )
    await rag._store.upsert(tenant, [kept, removed], [[0.0] * 8, [0.0] * 8])

    deleted_count = await rag._store.delete_by_source(tenant, "minio://tenant/b.pdf")
    assert deleted_count == 1

    remaining = await rag.retrieve(tenant, "anything")
    assert {r.chunk.chunk_id for r in remaining} == {kept.chunk_id}


async def test_verify_grounding_flags_sentence_without_citation(rag: RAGService) -> None:
    grounded, ungrounded = await rag.verify_grounding(
        "The clinic is open on weekdays. This has no citation at all.",
        context_block="[1] The clinic is open on weekdays.",
    )
    assert grounded is False
    assert len(ungrounded) >= 1
