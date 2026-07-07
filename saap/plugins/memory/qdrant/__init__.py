"""QdrantStore — default VectorStore implementation.

License: Apache-2.0. Registered as entry point `memory.qdrant`.

Tenant isolation strategy (P7, per saap.core.memory's contract):
  * `data_residency` on TenantContext selects the isolation mode:
      - collection-per-tenant (stronger isolation, more collections)
      - shared collection + mandatory tenant_id payload filter
        (fewer collections, filter enforced on every query)
  * The shared mode is the default here because most tenants don't
    require physical separation; a tenant whose contract or jurisdiction
    demands it gets `collection_per_tenant=True` in its blueprint.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels
from saap.core.memory import DocumentChunk, RetrievedChunk, VectorStore
from saap.core.registry import PluginRegistry
from saap.core.types import TenantContext

SHARED_COLLECTION = "saap_shared"


class QdrantStore:
    def __init__(
        self,
        client: AsyncQdrantClient | None = None,
        *,
        url: str = "http://localhost:6333",
        vector_size: int = 1024,  # BGE-M3 dense dimension
        collection_per_tenant: bool = False,
    ) -> None:
        self._client = client or AsyncQdrantClient(url=url)
        self._vector_size = vector_size
        self._collection_per_tenant = collection_per_tenant
        self._ensured: set[str] = set()

    def _collection_name(self, tenant: TenantContext) -> str:
        if self._collection_per_tenant:
            return f"tenant_{tenant.tenant_id}"
        return SHARED_COLLECTION

    async def _ensure_collection(self, name: str) -> None:
        if name in self._ensured:
            return
        exists = await self._client.collection_exists(name)
        if not exists:
            await self._client.create_collection(
                collection_name=name,
                vectors_config=qmodels.VectorParams(
                    size=self._vector_size, distance=qmodels.Distance.COSINE
                ),
            )
        self._ensured.add(name)

    def _tenant_filter(self, tenant: TenantContext) -> qmodels.Filter | None:
        if self._collection_per_tenant:
            return None  # isolation is physical; no filter needed
        return qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="tenant_id", match=qmodels.MatchValue(value=str(tenant.tenant_id))
                )
            ]
        )

    async def upsert(
        self, tenant: TenantContext, chunks: Sequence[DocumentChunk], vectors: Sequence[list[float]]
    ) -> None:
        collection = self._collection_name(tenant)
        await self._ensure_collection(collection)
        points = [
            qmodels.PointStruct(
                id=str(chunk.chunk_id),
                vector=vector,
                payload={
                    "tenant_id": str(tenant.tenant_id),
                    "source_uri": chunk.source_uri,
                    "text": chunk.text,
                    "data_class": chunk.data_class.value,
                    "metadata": chunk.metadata,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        await self._client.upsert(collection_name=collection, points=points)

    async def search(
        self,
        tenant: TenantContext,
        query_vector: list[float],
        *,
        k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        collection = self._collection_name(tenant)
        await self._ensure_collection(collection)
        tenant_filter = self._tenant_filter(tenant)
        query_filter = tenant_filter
        if filters:
            extra_conditions = [
                qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=value))
                for key, value in filters.items()
            ]
            must = list(tenant_filter.must) if tenant_filter else []
            query_filter = qmodels.Filter(must=[*must, *extra_conditions])

        results = await self._client.search(
            collection_name=collection,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=k,
        )
        return [
            RetrievedChunk(
                chunk=DocumentChunk(
                    chunk_id=UUID(str(point.id)),
                    source_uri=point.payload["source_uri"],
                    text=point.payload["text"],
                    data_class=point.payload["data_class"],
                    metadata=point.payload.get("metadata", {}),
                ),
                score=point.score,
            )
            for point in results
        ]

    async def delete_by_source(self, tenant: TenantContext, source_uri: str) -> int:
        collection = self._collection_name(tenant)
        await self._ensure_collection(collection)
        must = [
            qmodels.FieldCondition(key="source_uri", match=qmodels.MatchValue(value=source_uri))
        ]
        if not self._collection_per_tenant:
            must.append(
                qmodels.FieldCondition(
                    key="tenant_id", match=qmodels.MatchValue(value=str(tenant.tenant_id))
                )
            )
        # Count before delete so the erasure job can log an exact figure
        # in its signed certificate (Phase 3 requirement).
        count_result = await self._client.count(
            collection_name=collection, count_filter=qmodels.Filter(must=must)
        )
        await self._client.delete(
            collection_name=collection,
            points_selector=qmodels.FilterSelector(filter=qmodels.Filter(must=must)),
        )
        return count_result.count


def register(registry: PluginRegistry) -> None:
    registry.register(
        VectorStore,
        "qdrant",
        lambda: QdrantStore(),
        license="Apache-2.0",
    )
