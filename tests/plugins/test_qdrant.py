from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from qdrant_client.http import models as qmodels
from saap.core.memory import DataClass, DocumentChunk
from saap.core.types import TenantContext
from saap.plugins.memory.qdrant import SHARED_COLLECTION, QdrantStore


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


@pytest.fixture
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.collection_exists.return_value = True
    return client


async def test_shared_mode_uses_shared_collection_name(tenant: TenantContext, mock_client: AsyncMock) -> None:
    store = QdrantStore(mock_client, collection_per_tenant=False)
    assert store._collection_name(tenant) == SHARED_COLLECTION


async def test_per_tenant_mode_uses_tenant_scoped_collection_name(
    tenant: TenantContext, mock_client: AsyncMock
) -> None:
    store = QdrantStore(mock_client, collection_per_tenant=True)
    assert store._collection_name(tenant) == f"tenant_{tenant.tenant_id}"


async def test_upsert_sends_tenant_id_in_payload(tenant: TenantContext, mock_client: AsyncMock) -> None:
    store = QdrantStore(mock_client)
    chunk = DocumentChunk(
        chunk_id=uuid4(), source_uri="minio://x/handbook.pdf", text="hi", data_class=DataClass.INTERNAL
    )
    await store.upsert(tenant, [chunk], [[0.1] * 1024])

    mock_client.upsert.assert_awaited_once()
    _, kwargs = mock_client.upsert.call_args
    points = kwargs["points"]
    assert points[0].payload["tenant_id"] == str(tenant.tenant_id)
    assert points[0].payload["source_uri"] == "minio://x/handbook.pdf"


async def test_search_applies_tenant_filter_in_shared_mode(
    tenant: TenantContext, mock_client: AsyncMock
) -> None:
    mock_client.search.return_value = []
    store = QdrantStore(mock_client, collection_per_tenant=False)
    await store.search(tenant, [0.1] * 1024, k=5)

    _, kwargs = mock_client.search.call_args
    query_filter: qmodels.Filter = kwargs["query_filter"]
    assert query_filter is not None
    conditions = query_filter.must
    assert any(
        isinstance(c, qmodels.FieldCondition) and c.key == "tenant_id" for c in conditions
    )


async def test_search_skips_tenant_filter_in_per_tenant_mode(
    tenant: TenantContext, mock_client: AsyncMock
) -> None:
    mock_client.search.return_value = []
    store = QdrantStore(mock_client, collection_per_tenant=True)
    await store.search(tenant, [0.1] * 1024, k=5)

    _, kwargs = mock_client.search.call_args
    assert kwargs["query_filter"] is None


async def test_delete_by_source_counts_before_deleting(tenant: TenantContext, mock_client: AsyncMock) -> None:
    mock_client.count.return_value.count = 3
    store = QdrantStore(mock_client)
    deleted = await store.delete_by_source(tenant, "minio://x/handbook.pdf")
    assert deleted == 3
    mock_client.delete.assert_awaited_once()


async def test_ensure_collection_creates_if_missing(tenant: TenantContext, mock_client: AsyncMock) -> None:
    mock_client.collection_exists.return_value = False
    store = QdrantStore(mock_client)
    await store._ensure_collection("some_collection")
    mock_client.create_collection.assert_awaited_once()


async def test_ensure_collection_is_idempotent(tenant: TenantContext, mock_client: AsyncMock) -> None:
    mock_client.collection_exists.return_value = False
    store = QdrantStore(mock_client)
    await store._ensure_collection("some_collection")
    await store._ensure_collection("some_collection")
    mock_client.create_collection.assert_awaited_once()  # only the first call actually creates
