"""DirectOllamaRuntime — a LangflowRuntime stand-in for zero-dependency
local development: streams straight from an LLMProvider instead of
going through a deployed Langflow flow.

This exists ONLY so `uvicorn saap.gateway.app:app` is runnable on a
laptop with nothing but Ollama running — it has none of the canvas
guarantees (no ComplianceIngress/GroundedResponder/MCPToolkit sealing,
no RAG grounding). Production and any tenant-facing deployment MUST use
`LangflowHTTPRuntime` against a real flow built from the SAAP
component library (Phase 1 Epic 1.5) — swapping it in is one line in
`saap.gateway.app`'s runtime factory, not a code change here.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from saap.core.flow import FlowRef, FlowRunEvent
from saap.core.llm import GenerationConfig, LLMProvider
from saap.core.types import Message, TenantContext

DEV_FLOW_REF = FlowRef(
    flow_id="dev-direct-ollama",
    name="dev.direct_chat",
    version="0.0.0-dev",
    checksum="unpinned",
    lint_report_id="none - not a real flow, dev fallback only",
)


class DirectOllamaRuntime:
    def __init__(self, provider: LLMProvider, *, model: str) -> None:
        self._provider = provider
        self._model = model

    async def run(
        self,
        tenant: TenantContext,
        flow: FlowRef,
        message: Message,
        *,
        session_id: str,
        tweaks: dict[str, Any] | None = None,
    ) -> AsyncIterator[FlowRunEvent]:
        config = GenerationConfig(model=self._model)
        full_text = ""
        async for chunk in self._provider.stream([message], config=config):
            full_text += chunk
            yield FlowRunEvent(kind="token", payload={"text": chunk})
        yield FlowRunEvent(kind="final", payload={"text": full_text})

    async def upsert_flow(self, flow_json: dict[str, Any]) -> FlowRef:
        raise NotImplementedError("DirectOllamaRuntime is a dev read-only fallback; no flow storage")

    async def health(self) -> bool:
        return await self._provider.health()
