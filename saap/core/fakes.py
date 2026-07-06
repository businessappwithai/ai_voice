"""In-memory fakes for every core Protocol, used by unit tests across
the whole codebase (Epic 0.2 acceptance: "unit-tested with fakes").

These are deliberately simple — no threading, no persistence — so
tests stay fast and deterministic. They live in saap.core (not
tests/) because plugin packages and langflow_components tests need
them too, without duplicating fake logic per-package.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import uuid4

from .events import DomainEvent
from .flow import FlowRef, FlowRunEvent
from .llm import Completion, GenerationConfig, ToolSpec
from .memory import DocumentChunk, RetrievedChunk
from .types import Message, TenantContext, ToolResult


class FakeLLMProvider:
    """Scripted responses, one per call, cycling if exhausted.
    `json_schema` requests are honored by returning the provided
    `next_json` verbatim so grounding/extraction tests are exact."""

    def __init__(self, responses: Sequence[str] = ("ok",), *, next_json: str | None = None) -> None:
        self._responses = list(responses) or ["ok"]
        self._next_json = next_json
        self._i = 0
        self.calls: list[list[Message]] = []

    async def generate(
        self,
        messages: Sequence[Message],
        *,
        config: GenerationConfig,
        tools: Sequence[ToolSpec] = (),
    ) -> Completion:
        self.calls.append(list(messages))
        if config.json_schema is not None and self._next_json is not None:
            text = self._next_json
        else:
            text = self._responses[self._i % len(self._responses)]
            self._i += 1
        return Completion(text=text, prompt_tokens=1, completion_tokens=1, latency_ms=1.0)

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        config: GenerationConfig,
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncIterator[str]:
        completion = await self.generate(messages, config=config, tools=tools)
        for chunk in completion.text.split(" "):
            yield chunk + " "

    async def health(self) -> bool:
        return True


class FakeEmbeddingProvider:
    dimension = 8

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        # Deterministic pseudo-embedding: length-derived, not semantic —
        # fine for exercising the retrieve->rerank plumbing in tests.
        return [[float((len(t) + i) % 7) for i in range(self.dimension)] for t in texts]


class FakeVectorStore:
    def __init__(self) -> None:
        self._rows: dict[str, list[DocumentChunk]] = {}

    async def upsert(
        self, tenant: TenantContext, chunks: Sequence[DocumentChunk], vectors: Sequence[list[float]]
    ) -> None:
        self._rows.setdefault(str(tenant.tenant_id), []).extend(chunks)

    async def search(
        self, tenant: TenantContext, query_vector: list[float], *, k: int = 8, filters: dict[str, Any] | None = None
    ) -> list[RetrievedChunk]:
        rows = self._rows.get(str(tenant.tenant_id), [])
        return [RetrievedChunk(chunk=c, score=1.0) for c in rows[:k]]

    async def delete_by_source(self, tenant: TenantContext, source_uri: str) -> int:
        rows = self._rows.get(str(tenant.tenant_id), [])
        keep = [c for c in rows if c.source_uri != source_uri]
        deleted = len(rows) - len(keep)
        self._rows[str(tenant.tenant_id)] = keep
        return deleted


class FakeReranker:
    async def rerank(
        self, query: str, chunks: Sequence[RetrievedChunk], top_n: int
    ) -> list[RetrievedChunk]:
        return sorted(chunks, key=lambda rc: rc.score, reverse=True)[:top_n]


class FakeLangflowRuntime:
    """Emits a scripted sequence of FlowRunEvents for `run`, ignores
    `upsert_flow` (returns the FlowRef unchanged with a fake checksum)."""

    def __init__(self, events: Sequence[FlowRunEvent] | None = None) -> None:
        self._events = list(events) if events is not None else [
            FlowRunEvent(kind="final", payload={"text": "ok"})
        ]
        self.runs: list[tuple[TenantContext, FlowRef, Message]] = []

    async def run(
        self,
        tenant: TenantContext,
        flow: FlowRef,
        message: Message,
        *,
        session_id: str,
        tweaks: dict[str, Any] | None = None,
    ) -> AsyncIterator[FlowRunEvent]:
        self.runs.append((tenant, flow, message))
        for event in self._events:
            yield event

    async def upsert_flow(self, flow_json: dict[str, Any]) -> FlowRef:
        return FlowRef(
            flow_id=str(uuid4()),
            name=flow_json.get("name", "unnamed"),
            version="0.0.0-fake",
            checksum="fake",
            lint_report_id="fake",
        )

    async def health(self) -> bool:
        return True


class FakeMCPConnection:
    def __init__(self, tools: Sequence[ToolSpec] = (), *, result: ToolResult | None = None) -> None:
        self._tools = list(tools)
        self._result = result
        self.closed = False
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[ToolSpec]:
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append((name, arguments))
        if self._result is not None:
            return self._result
        return ToolResult(call_id=str(uuid4()), ok=True, content={"echo": arguments})

    async def close(self) -> None:
        self.closed = True


class FakeEventBus:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)

    async def subscribe(self, kinds: Sequence[str]) -> AsyncIterator[DomainEvent]:
        for event in self.published:
            if event.kind in kinds:
                yield event
