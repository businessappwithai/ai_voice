"""Integration tests against a real local Postgres + pgvector instance
(not mocked) — this environment has both installed. CI should run this
file against the same `postgres:16` service the migration-check job
already spins up, with `CREATE EXTENSION vector` available via the
`pgvector/pgvector` image or an `apt install postgresql-16-pgvector`
step.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from saap.core.memory import DataClass, DocumentChunk
from saap.core.types import TenantContext
from saap.plugins.memory.pgvector import PgVectorStore
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

DATABASE_URL = "postgresql+asyncpg://saap:saap_dev_only@localhost:5432/saap"


@pytest.fixture
async def engine():
    # Function-scoped: pytest-asyncio's default event loop is
    # per-test, and an asyncpg connection pool bound to one loop
    # breaks on the next test's loop ("another operation is in
    # progress" / "Event loop is closed") if shared across tests.
    eng = create_async_engine(DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


def _chunk(text: str, source_uri: str = "minio://t/handbook.txt") -> DocumentChunk:
    return DocumentChunk(chunk_id=uuid4(), source_uri=source_uri, text=text, data_class=DataClass.INTERNAL)


def _vector(seed: float) -> list[float]:
    return [seed] * 8


async def test_upsert_and_search_shared_mode(engine: AsyncEngine, tenant: TenantContext) -> None:
    store = PgVectorStore(engine, vector_size=8, collection_per_tenant=False)
    chunk = _chunk("Office hours are 9 to 5.")
    await store.upsert(tenant, [chunk], [_vector(0.1)])

    results = await store.search(tenant, _vector(0.1), k=5)
    assert len(results) == 1
    assert results[0].chunk.chunk_id == chunk.chunk_id
    assert results[0].chunk.text == "Office hours are 9 to 5."


async def test_search_respects_tenant_isolation_in_shared_mode(engine: AsyncEngine) -> None:
    store = PgVectorStore(engine, vector_size=8, collection_per_tenant=False)
    t1 = TenantContext(tenant_id=uuid4(), vertical="dental")
    t2 = TenantContext(tenant_id=uuid4(), vertical="realestate")

    await store.upsert(t1, [_chunk("t1 data")], [_vector(0.2)])
    await store.upsert(t2, [_chunk("t2 data")], [_vector(0.2)])

    results_t1 = await store.search(t1, _vector(0.2), k=10)
    assert all(r.chunk.text == "t1 data" for r in results_t1)
    assert len(results_t1) == 1


async def test_search_orders_by_similarity(engine: AsyncEngine, tenant: TenantContext) -> None:
    store = PgVectorStore(engine, vector_size=8, collection_per_tenant=False)
    close = _chunk("close match")
    far = _chunk("far match")
    await store.upsert(tenant, [close, far], [_vector(0.5), _vector(5.0)])

    results = await store.search(tenant, _vector(0.5), k=2)
    assert results[0].chunk.chunk_id == close.chunk_id


async def test_delete_by_source_is_exact(engine: AsyncEngine, tenant: TenantContext) -> None:
    store = PgVectorStore(engine, vector_size=8, collection_per_tenant=False)
    keep = _chunk("keep me", source_uri="minio://t/a.txt")
    remove = _chunk("remove me", source_uri="minio://t/b.txt")
    await store.upsert(tenant, [keep, remove], [_vector(0.3), _vector(0.3)])

    deleted_count = await store.delete_by_source(tenant, "minio://t/b.txt")
    assert deleted_count == 1

    remaining = await store.search(tenant, _vector(0.3), k=10)
    assert {r.chunk.chunk_id for r in remaining} == {keep.chunk_id}


async def test_delete_by_source_does_not_cross_tenants(engine: AsyncEngine) -> None:
    store = PgVectorStore(engine, vector_size=8, collection_per_tenant=False)
    t1 = TenantContext(tenant_id=uuid4(), vertical="dental")
    t2 = TenantContext(tenant_id=uuid4(), vertical="realestate")
    same_source = "minio://shared-name/doc.txt"
    await store.upsert(t1, [_chunk("t1 doc", source_uri=same_source)], [_vector(0.7)])
    await store.upsert(t2, [_chunk("t2 doc", source_uri=same_source)], [_vector(0.7)])

    deleted_count = await store.delete_by_source(t1, same_source)
    assert deleted_count == 1

    remaining_t2 = await store.search(t2, _vector(0.7), k=10)
    assert len(remaining_t2) == 1  # t2's row survives t1's delete


async def test_upsert_is_idempotent_via_on_conflict(engine: AsyncEngine, tenant: TenantContext) -> None:
    store = PgVectorStore(engine, vector_size=8, collection_per_tenant=False)
    chunk = _chunk("original text")
    await store.upsert(tenant, [chunk], [_vector(0.4)])

    updated_chunk = DocumentChunk(
        chunk_id=chunk.chunk_id, source_uri=chunk.source_uri, text="updated text", data_class=DataClass.INTERNAL
    )
    await store.upsert(tenant, [updated_chunk], [_vector(0.4)])

    results = await store.search(tenant, _vector(0.4), k=10)
    assert len(results) == 1  # same chunk_id, not duplicated
    assert results[0].chunk.text == "updated text"


async def test_collection_per_tenant_mode_isolates_physically(engine: AsyncEngine) -> None:
    store = PgVectorStore(engine, vector_size=8, collection_per_tenant=True)
    t1 = TenantContext(tenant_id=uuid4(), vertical="dental")
    t2 = TenantContext(tenant_id=uuid4(), vertical="realestate")

    await store.upsert(t1, [_chunk("t1 only")], [_vector(0.9)])
    await store.upsert(t2, [_chunk("t2 only")], [_vector(0.9)])

    results_t1 = await store.search(t1, _vector(0.9), k=10)
    results_t2 = await store.search(t2, _vector(0.9), k=10)
    assert [r.chunk.text for r in results_t1] == ["t1 only"]
    assert [r.chunk.text for r in results_t2] == ["t2 only"]


async def test_search_with_metadata_filter(engine: AsyncEngine, tenant: TenantContext) -> None:
    store = PgVectorStore(engine, vector_size=8, collection_per_tenant=False)
    chunk_a = DocumentChunk(
        chunk_id=uuid4(), source_uri="minio://t/a.txt", text="section A", data_class=DataClass.INTERNAL,
        metadata={"section": "a"},
    )
    chunk_b = DocumentChunk(
        chunk_id=uuid4(), source_uri="minio://t/b.txt", text="section B", data_class=DataClass.INTERNAL,
        metadata={"section": "b"},
    )
    await store.upsert(tenant, [chunk_a, chunk_b], [_vector(0.6), _vector(0.6)])

    results = await store.search(tenant, _vector(0.6), k=10, filters={"section": "a"})
    assert [r.chunk.text for r in results] == ["section A"]
