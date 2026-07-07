"""Blueprint-driven ingestion for `rag_sources` (Phase 1 Epic 1.2;
architecture Section 12.2). Production wiring runs each `sync_source`
call as a Dagster asset so re-indexing is incremental and observable;
`IngestionPipeline` itself is Dagster-agnostic — it's a plain async
class callable from Dagster, a cron script, or synchronously, as in
the tests here.

Stages (each an interface, each swappable, per P3):

  Loader (MinIO/local/URL) -> Parser (Docling: PDF/DOCX/PPTX -> structured
  blocks; PlainTextParser below handles .txt/.md natively as the
  dependency-free default) -> PIIClassifier (tags each block's
  DataClass — SPII blocks can be excluded per tenant policy BEFORE they
  ever reach the vector store) -> Chunker (structure-aware: headings
  kept as boundaries, 512-word target, 15% overlap) -> Embedder ->
  VectorStore.upsert + lineage row.

Lineage is what makes DPDP erasure exact: every chunk row keys back to
(tenant, source_uri, content_hash), so `delete_by_source` is a lookup,
not a scan. It also makes re-sync idempotent: unchanged content hashes
are skipped.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from saap.compliance.pii import PIIAnalyzer
from saap.core.memory import DocumentChunk, EmbeddingProvider, VectorStore
from saap.core.types import DataClass, TenantContext


@dataclass(frozen=True)
class ParsedBlock:
    text: str
    is_heading: bool = False
    is_table: bool = False


@dataclass(frozen=True)
class ParsedDocument:
    source_uri: str
    blocks: tuple[ParsedBlock, ...]


class DocumentLoader(Protocol):
    """Fetches raw bytes for a source_uri. Implementations: MinIO,
    local filesystem, HTTP URL."""

    async def load(self, source_uri: str) -> bytes: ...


class DocumentParser(Protocol):
    """Docling (MIT) default for PDF/DOCX/PPTX; `unstructured` adapter
    available. `PlainTextParser` below is the dependency-free default
    for .txt/.md, useful for tests and simple tenants alike."""

    async def parse(self, source_uri: str, content: bytes) -> ParsedDocument: ...


class PIIClassifier(Protocol):
    """Tags each block's DataClass; SPII blocks can be excluded per
    tenant policy BEFORE they ever reach the vector store."""

    def classify(self, text: str) -> DataClass: ...


class Chunker(Protocol):
    def chunk(self, doc: ParsedDocument, tenant: TenantContext) -> Sequence[DocumentChunk]: ...


class LineageStore(Protocol):
    """Keys every chunk back to (tenant, source_uri, content_hash) so
    `delete_by_source` (DPDP erasure, Phase 3) is a lookup, not a scan,
    and re-sync can skip unchanged content."""

    async def record(
        self, tenant: TenantContext, chunk_id: UUID, source_uri: str, content_hash: str
    ) -> None: ...

    async def hashes_for_source(self, tenant: TenantContext, source_uri: str) -> set[str]: ...

    async def clear_source(self, tenant: TenantContext, source_uri: str) -> None: ...


@dataclass(frozen=True)
class IngestReport:
    source_uri: str
    chunks_upserted: int
    chunks_skipped_unchanged: int
    chunks_excluded_spii: int


class PlainTextParser:
    """Handles .txt/.md natively by splitting on blank lines; a real
    Docling-backed parser slots in for PDF/DOCX without changing
    `IngestionPipeline` (P3) — same `DocumentParser` protocol."""

    async def parse(self, source_uri: str, content: bytes) -> ParsedDocument:
        text = content.decode("utf-8", errors="replace")
        blocks = []
        for para in text.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            blocks.append(ParsedBlock(text=para, is_heading=para.startswith("#")))
        return ParsedDocument(source_uri=source_uri, blocks=tuple(blocks))


class PresidioPIIClassifier:
    """Wraps a `PIIAnalyzer` (saap.compliance.pii); a block containing
    an Indian-market sensitive entity (Aadhaar/PAN) is tagged SPII so
    tenant policy can exclude it before embedding; a block with any
    other detected entity is PERSONAL; otherwise INTERNAL."""

    SPII_ENTITY_TYPES = frozenset({"IN_AADHAAR", "IN_PAN"})

    def __init__(self, analyzer: PIIAnalyzer) -> None:
        self._analyzer = analyzer

    def classify(self, text: str) -> DataClass:
        entities = self._analyzer.analyze(text)
        if any(e.entity_type in self.SPII_ENTITY_TYPES for e in entities):
            return DataClass.SENSITIVE_PERSONAL
        if entities:
            return DataClass.PERSONAL
        return DataClass.INTERNAL


class StructureAwareChunker:
    """512-word target, 15% overlap; a heading always starts a new
    chunk boundary (never split mid-section)."""

    def __init__(
        self,
        classifier: PIIClassifier,
        *,
        target_words: int = 512,
        overlap_ratio: float = 0.15,
    ) -> None:
        self._classifier = classifier
        self._target_words = target_words
        self._overlap_words = int(target_words * overlap_ratio)

    def chunk(self, doc: ParsedDocument, tenant: TenantContext) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        current_words: list[str] = []
        for block in doc.blocks:
            if block.is_heading and current_words:
                chunks.append(self._flush(current_words, doc.source_uri))
                current_words = []
            current_words.extend(block.text.split())
            while len(current_words) >= self._target_words:
                chunks.append(self._flush(current_words[: self._target_words], doc.source_uri))
                current_words = current_words[self._target_words - self._overlap_words :]
        if current_words:
            chunks.append(self._flush(current_words, doc.source_uri))
        return chunks

    def _flush(self, words: list[str], source_uri: str) -> DocumentChunk:
        text = " ".join(words)
        return DocumentChunk(
            chunk_id=uuid4(), source_uri=source_uri, text=text, data_class=self._classifier.classify(text)
        )


class InMemoryLineageStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], list[tuple[UUID, str]]] = {}

    async def record(
        self, tenant: TenantContext, chunk_id: UUID, source_uri: str, content_hash: str
    ) -> None:
        key = (str(tenant.tenant_id), source_uri)
        self._rows.setdefault(key, []).append((chunk_id, content_hash))

    async def hashes_for_source(self, tenant: TenantContext, source_uri: str) -> set[str]:
        key = (str(tenant.tenant_id), source_uri)
        return {h for _, h in self._rows.get(key, [])}

    async def clear_source(self, tenant: TenantContext, source_uri: str) -> None:
        self._rows.pop((str(tenant.tenant_id), source_uri), None)


class IngestionPipeline:
    def __init__(
        self,
        loader: DocumentLoader,
        parser: DocumentParser,
        chunker: Chunker,
        embedder: EmbeddingProvider,
        store: VectorStore,
        lineage: LineageStore,
        *,
        exclude_data_classes: frozenset[DataClass] = frozenset({DataClass.SENSITIVE_PERSONAL}),
    ) -> None:
        self._loader = loader
        self._parser = parser
        self._chunker = chunker
        self._embedder = embedder
        self._store = store
        self._lineage = lineage
        self._exclude_data_classes = exclude_data_classes

    async def sync_source(self, tenant: TenantContext, source_uri: str) -> IngestReport:
        """Idempotent: unchanged content hashes are skipped. Emits a
        report; production wiring turns this into Langfuse spans + a
        per-source freshness metric Grafana alerts on."""
        content = await self._loader.load(source_uri)
        doc = await self._parser.parse(source_uri, content)
        all_chunks = self._chunker.chunk(doc, tenant)
        existing_hashes = await self._lineage.hashes_for_source(tenant, source_uri)

        to_upsert: list[DocumentChunk] = []
        content_hashes: dict[UUID, str] = {}
        excluded_spii = 0
        skipped_unchanged = 0

        for chunk in all_chunks:
            if chunk.data_class in self._exclude_data_classes:
                excluded_spii += 1
                continue
            content_hash = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
            if content_hash in existing_hashes:
                skipped_unchanged += 1
                continue
            content_hashes[chunk.chunk_id] = content_hash
            to_upsert.append(chunk)

        if to_upsert:
            vectors = await self._embedder.embed([c.text for c in to_upsert])
            await self._store.upsert(tenant, to_upsert, vectors)
            for chunk in to_upsert:
                await self._lineage.record(tenant, chunk.chunk_id, source_uri, content_hashes[chunk.chunk_id])

        return IngestReport(
            source_uri=source_uri,
            chunks_upserted=len(to_upsert),
            chunks_skipped_unchanged=skipped_unchanged,
            chunks_excluded_spii=excluded_spii,
        )

    async def delete_source(self, tenant: TenantContext, source_uri: str) -> int:
        """DPDP erasure prerequisite (Phase 3): exact deletion via
        lineage, not a content scan."""
        deleted = await self._store.delete_by_source(tenant, source_uri)
        await self._lineage.clear_source(tenant, source_uri)
        return deleted
