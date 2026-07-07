"""Local LLM provider abstraction.

The orchestration layer NEVER imports vllm/ollama/llama_cpp directly.
It talks to `LLMProvider`; the registry binds the concrete engine per
deployment profile (edge -> Ollama, datacenter -> vLLM).

There is intentionally no provider for hosted APIs (no OpenAIProvider,
no AnthropicProvider) — the type system is the enforcement mechanism
for the open-source/local mandate (P1/P2).
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel

from .types import Message, TenantContext, ToolCall


class GenerationConfig(BaseModel, frozen=True):
    model: str  # local model tag, e.g. "qwen2.5:72b-instruct-q4"
    temperature: float = 0.2
    max_tokens: int = 1024
    stop: tuple[str, ...] = ()
    json_schema: dict[str, Any] | None = None  # constrained decoding (outlines/xgrammar)


class ToolSpec(BaseModel, frozen=True):
    """JSON-Schema tool description handed to the model (MCP-derived)."""

    name: str
    description: str
    input_schema: dict[str, Any]


class Completion(BaseModel, frozen=True):
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0


@runtime_checkable
class LLMProvider(Protocol):
    """Contract for any local inference backend.

    Implementations
    ---------------
    * ``VLLMProvider``     — OpenAI-compatible HTTP to a self-hosted vLLM
                             cluster; continuous batching; tensor parallel.
    * ``OllamaProvider``   — /api/chat on a local Ollama daemon; GGUF quant.
    * ``LlamaCppProvider`` — in-process llama.cpp bindings for edge boxes.

    Guarantees implementations MUST honor
    -------------------------------------
    1. `generate` and `stream` are safe under concurrency (asyncio).
    2. If `config.json_schema` is set, output MUST validate against it
       (use grammar-constrained decoding, not "hope + retry").
    3. Latency and token counts are populated for Langfuse tracing.
    """

    async def generate(
        self,
        messages: Sequence[Message],
        *,
        config: GenerationConfig,
        tools: Sequence[ToolSpec] = (),
    ) -> Completion: ...

    def stream(
        self,
        messages: Sequence[Message],
        *,
        config: GenerationConfig,
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncIterator[str]:
        """Token stream for voice/chat UIs; must support early cancel
        (caller cancels on barge-in — see VoicePipeline, Phase 2)."""
        ...

    async def health(self) -> bool: ...


class TenantModelPolicy(BaseModel, frozen=True):
    """Per-tenant override of a task profile -> concrete model tag.

    Row in Postgres (tenancy schema). Absence of an override means the
    deployment-wide default for that profile applies.
    """

    tenant_id: UUID
    profile: str  # "fast" | "reason" | "extract"
    model_tag: str


class TenantModelPolicyStore(Protocol):
    async def get_override(self, tenant_id: UUID, profile: str) -> str | None: ...

    async def set_override(self, tenant_id: UUID, profile: str, model_tag: str) -> None: ...


class NoOverridesPolicyStore:
    """Trivial policy store: every tenant gets deployment defaults.

    Used until saap.tenancy ships a Postgres-backed store; also handy
    in tests.
    """

    async def get_override(self, tenant_id: UUID, profile: str) -> str | None:
        return None

    async def set_override(self, tenant_id: UUID, profile: str, model_tag: str) -> None:
        raise NotImplementedError("NoOverridesPolicyStore is read-only")


class ModelRouter:
    """Cost/latency-aware routing across local models (P3, P5).

    Routes by task profile rather than hardcoding model names in agents:

    * ``fast``    -> 3-8B model on Ollama    (intent routing, voice turns)
    * ``reason``  -> 32-72B on vLLM          (multi-step tool planning)
    * ``extract`` -> small model + JSON grammar (structured extraction)

    Tenants may pin overrides (e.g., a legal tenant pins `reason` to a
    LoRA-adapted Qwen 72B) via `TenantModelPolicy` in Postgres.
    """

    def __init__(
        self,
        providers: dict[str, LLMProvider],
        policy_store: TenantModelPolicyStore,
        *,
        default_models: dict[str, str],
    ) -> None:
        """
        providers: profile -> LLMProvider bound for that profile
            (e.g. {"fast": OllamaProvider(...), "reason": VLLMProvider(...)})
        default_models: profile -> model tag used absent a tenant override
        """
        self._providers = providers
        self._policy_store = policy_store
        self._default_models = default_models

    async def route(
        self, tenant: TenantContext, task: str
    ) -> tuple[LLMProvider, GenerationConfig]:
        if task not in self._providers:
            raise KeyError(
                f"no provider bound for task profile {task!r}; "
                f"known profiles: {sorted(self._providers)}"
            )
        provider = self._providers[task]
        model_tag = await self._policy_store.get_override(
            tenant.tenant_id, task
        ) or self._default_models.get(task)
        if model_tag is None:
            raise KeyError(f"no default model configured for profile {task!r}")
        return provider, GenerationConfig(model=model_tag)
