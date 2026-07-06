from uuid import uuid4

import pytest
from saap.compliance.pii import SimplePIIAnalyzer
from saap.core.fakes import FakeEmbeddingProvider, FakeVectorStore
from saap.core.types import DataClass, TenantContext
from saap.ingest.pipeline import (
    IngestionPipeline,
    InMemoryLineageStore,
    ParsedBlock,
    ParsedDocument,
    PlainTextParser,
    PresidioPIIClassifier,
    StructureAwareChunker,
)


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


class StaticLoader:
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def load(self, source_uri: str) -> bytes:
        return self._content


def _pipeline(content: bytes, *, exclude=frozenset({DataClass.SENSITIVE_PERSONAL})):  # noqa: ANN001
    classifier = PresidioPIIClassifier(SimplePIIAnalyzer())
    chunker = StructureAwareChunker(classifier, target_words=50, overlap_ratio=0.1)
    store = FakeVectorStore()
    lineage = InMemoryLineageStore()
    pipeline = IngestionPipeline(
        StaticLoader(content), PlainTextParser(), chunker, FakeEmbeddingProvider(), store, lineage,
        exclude_data_classes=exclude,
    )
    return pipeline, store, lineage


async def test_plain_text_parser_splits_on_blank_lines_and_detects_headings() -> None:
    parser = PlainTextParser()
    doc = await parser.parse("x.txt", b"# Heading\n\nBody paragraph one.\n\nBody paragraph two.")
    assert doc.blocks[0].is_heading is True
    assert doc.blocks[0].text == "# Heading"
    assert doc.blocks[1].text == "Body paragraph one."
    assert doc.blocks[2].text == "Body paragraph two."


async def test_chunker_starts_new_chunk_at_heading() -> None:
    classifier = PresidioPIIClassifier(SimplePIIAnalyzer())
    chunker = StructureAwareChunker(classifier, target_words=1000, overlap_ratio=0.1)
    doc = ParsedDocument(
        source_uri="x.txt",
        blocks=(
            ParsedBlock(text="intro words here", is_heading=False),
            ParsedBlock(text="# Section Two", is_heading=True),
            ParsedBlock(text="more words here", is_heading=False),
        ),
    )
    tenant = TenantContext(tenant_id=uuid4(), vertical="dental")
    chunks = chunker.chunk(doc, tenant)
    assert len(chunks) == 2
    assert chunks[0].text == "intro words here"
    assert chunks[1].text == "# Section Two more words here"


async def test_chunker_splits_long_text_with_overlap() -> None:
    classifier = PresidioPIIClassifier(SimplePIIAnalyzer())
    chunker = StructureAwareChunker(classifier, target_words=10, overlap_ratio=0.2)
    words = " ".join(f"word{i}" for i in range(25))
    doc = ParsedDocument(source_uri="x.txt", blocks=(ParsedBlock(text=words),))
    tenant = TenantContext(tenant_id=uuid4(), vertical="dental")
    chunks = chunker.chunk(doc, tenant)
    assert len(chunks) >= 2
    # overlap: last 2 words of chunk 0 reappear at the start of chunk 1
    first_words = chunks[0].text.split()
    second_words = chunks[1].text.split()
    assert first_words[-2:] == second_words[:2]


async def test_presidio_classifier_tags_aadhaar_as_spii() -> None:
    classifier = PresidioPIIClassifier(SimplePIIAnalyzer())
    assert classifier.classify("Patient Aadhaar 1234 5678 9012") == DataClass.SENSITIVE_PERSONAL


async def test_presidio_classifier_tags_plain_text_as_internal() -> None:
    classifier = PresidioPIIClassifier(SimplePIIAnalyzer())
    assert classifier.classify("Office hours are 9 to 5.") == DataClass.INTERNAL


async def test_sync_source_upserts_chunks_and_records_lineage(tenant: TenantContext) -> None:
    pipeline, store, lineage = _pipeline(b"Office hours are 9 to 5 on weekdays.")
    report = await pipeline.sync_source(tenant, "minio://t/handbook.txt")
    assert report.chunks_upserted == 1
    assert report.chunks_skipped_unchanged == 0
    hashes = await lineage.hashes_for_source(tenant, "minio://t/handbook.txt")
    assert len(hashes) == 1


async def test_sync_source_excludes_spii_chunks(tenant: TenantContext) -> None:
    pipeline, store, lineage = _pipeline(b"Patient Aadhaar 1234 5678 9012 was seen today.")
    report = await pipeline.sync_source(tenant, "minio://t/patient.txt")
    assert report.chunks_upserted == 0
    assert report.chunks_excluded_spii == 1


async def test_sync_source_is_idempotent_on_unchanged_content(tenant: TenantContext) -> None:
    pipeline, store, lineage = _pipeline(b"Office hours are 9 to 5 on weekdays.")
    first = await pipeline.sync_source(tenant, "minio://t/handbook.txt")
    second = await pipeline.sync_source(tenant, "minio://t/handbook.txt")
    assert first.chunks_upserted == 1
    assert second.chunks_upserted == 0
    assert second.chunks_skipped_unchanged == 1


async def test_delete_source_removes_from_store_and_lineage(tenant: TenantContext) -> None:
    pipeline, store, lineage = _pipeline(b"Office hours are 9 to 5 on weekdays.")
    await pipeline.sync_source(tenant, "minio://t/handbook.txt")
    deleted = await pipeline.delete_source(tenant, "minio://t/handbook.txt")
    assert deleted == 1
    assert await lineage.hashes_for_source(tenant, "minio://t/handbook.txt") == set()
