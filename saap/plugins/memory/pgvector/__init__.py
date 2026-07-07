"""PgVectorStore — second VectorStore implementation, over Postgres +
the pgvector extension. License: PostgreSQL License (Postgres itself);
pgvector extension is dual PostgreSQL/MIT.

Exists to prove the VectorStore interface really is swappable (P3),
alongside QdrantStore — same tenant isolation contract (collection-per-
tenant vs. shared+payload-filter, chosen per `data_residency`), same
`delete_by_source` exactness for DPDP erasure lineage.

Registered as entry point `memory.pgvector`.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from saap.core.memory import DocumentChunk, RetrievedChunk, VectorStore
from saap.core.registry import PluginRegistry
from saap.core.types import TenantContext
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

SHARED_TABLE = "saap_shared_chunks"


def _tenant_table_name(tenant: TenantContext) -> str:
    return f"tenant_{str(tenant.tenant_id).replace('-', '_')}_chunks"


def _quote_ident(name: str) -> str:
    # Table names here are either the fixed SHARED_TABLE constant or
    # derived from a UUID (hex digits, hyphens -> underscores) never
    # from unsanitized user input, but quoting defensively costs nothing.
    return '"' + name.replace('"', '""') + '"'


class PgVectorStore:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        vector_size: int = 1024,  # BGE-M3 dense dimension, matches QdrantStore's default
        collection_per_tenant: bool = False,
    ) -> None:
        self._engine = engine
        self._vector_size = vector_size
        self._collection_per_tenant = collection_per_tenant
        self._ensured: set[str] = set()

    def _table_name(self, tenant: TenantContext) -> str:
        return _tenant_table_name(tenant) if self._collection_per_tenant else SHARED_TABLE

    async def _ensure_table(self, conn: AsyncConnection, table_name: str) -> None:
        if table_name in self._ensured:
            return
        quoted = _quote_ident(table_name)
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(
            sa.text(
                f"""
                CREATE TABLE IF NOT EXISTS {quoted} (
                    chunk_id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL,
                    source_uri TEXT NOT NULL,
                    text TEXT NOT NULL,
                    data_class TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}',
                    embedding VECTOR({self._vector_size}) NOT NULL
                )
                """
            )
        )
        self._ensured.add(table_name)

    async def upsert(
        self, tenant: TenantContext, chunks: Sequence[DocumentChunk], vectors: Sequence[list[float]]
    ) -> None:
        table_name = self._table_name(tenant)
        quoted = _quote_ident(table_name)
        async with self._engine.begin() as conn:
            await self._ensure_table(conn, table_name)
            for chunk, vector in zip(chunks, vectors, strict=True):
                await conn.execute(
                    sa.text(
                        f"""
                        INSERT INTO {quoted}
                            (chunk_id, tenant_id, source_uri, text, data_class, metadata, embedding)
                        VALUES
                            (:chunk_id, :tenant_id, :source_uri, :text, :data_class, :metadata, :embedding)
                        ON CONFLICT (chunk_id) DO UPDATE SET
                            source_uri = EXCLUDED.source_uri,
                            text = EXCLUDED.text,
                            data_class = EXCLUDED.data_class,
                            metadata = EXCLUDED.metadata,
                            embedding = EXCLUDED.embedding
                        """
                    ),
                    {
                        "chunk_id": str(chunk.chunk_id),
                        "tenant_id": str(tenant.tenant_id),
                        "source_uri": chunk.source_uri,
                        "text": chunk.text,
                        "data_class": chunk.data_class.value,
                        "metadata": json.dumps(chunk.metadata),
                        "embedding": str(list(vector)),
                    },
                )

    async def search(
        self,
        tenant: TenantContext,
        query_vector: list[float],
        *,
        k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        table_name = self._table_name(tenant)
        quoted = _quote_ident(table_name)
        where_clauses = [] if self._collection_per_tenant else ["tenant_id = :tenant_id"]
        params: dict[str, Any] = {"tenant_id": str(tenant.tenant_id), "query_vector": str(list(query_vector)), "k": k}
        for key, value in (filters or {}).items():
            param_name = f"filter_{key}"
            where_clauses.append(f"metadata ->> :{param_name}_key = :{param_name}_value")
            params[f"{param_name}_key"] = key
            params[f"{param_name}_value"] = str(value)
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        async with self._engine.begin() as conn:
            await self._ensure_table(conn, table_name)
            result = await conn.execute(
                sa.text(
                    f"""
                    SELECT chunk_id, source_uri, text, data_class, metadata,
                           1 - (embedding <=> (:query_vector)::vector) AS score
                    FROM {quoted}
                    {where_sql}
                    ORDER BY embedding <=> (:query_vector)::vector
                    LIMIT :k
                    """
                ),
                params,
            )
            rows = result.mappings().all()

        return [
            RetrievedChunk(
                chunk=DocumentChunk(
                    chunk_id=UUID(str(row["chunk_id"])),
                    source_uri=row["source_uri"],
                    text=row["text"],
                    data_class=row["data_class"],
                    metadata=row["metadata"] or {},
                ),
                score=row["score"],
            )
            for row in rows
        ]

    async def delete_by_source(self, tenant: TenantContext, source_uri: str) -> int:
        table_name = self._table_name(tenant)
        quoted = _quote_ident(table_name)
        where_clauses = ["source_uri = :source_uri"]
        if not self._collection_per_tenant:
            where_clauses.append("tenant_id = :tenant_id")
        where_sql = " AND ".join(where_clauses)

        async with self._engine.begin() as conn:
            await self._ensure_table(conn, table_name)
            result = await conn.execute(
                sa.text(f"DELETE FROM {quoted} WHERE {where_sql}"),
                {"source_uri": source_uri, "tenant_id": str(tenant.tenant_id)},
            )
            return result.rowcount


def register(registry: PluginRegistry) -> None:
    def _factory() -> PgVectorStore:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine("postgresql+asyncpg://saap:saap_dev_only@localhost:5432/saap")
        return PgVectorStore(engine)

    registry.register(VectorStore, "pgvector", _factory, license="PostgreSQL")
