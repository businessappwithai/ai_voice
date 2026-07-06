"""Framework-agnostic logic behind the `ModelRouterLLM` canvas
component — the drop-in LLM component designers use by picking a task
*profile* ("fast"/"reason"/"extract"), never a raw model endpoint."""
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from saap.core.llm import Completion, ModelRouter, ToolSpec
from saap.core.types import Message, TenantContext


class ModelRouterLLMLogic:
    def __init__(self, router: ModelRouter) -> None:
        self._router = router

    async def generate(
        self,
        tenant: TenantContext,
        profile: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> Completion:
        provider, config = await self._router.route(tenant, profile)
        return await provider.generate(messages, config=config, tools=tools)

    async def stream(
        self,
        tenant: TenantContext,
        profile: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncIterator[str]:
        provider, config = await self._router.route(tenant, profile)
        async for chunk in provider.stream(messages, config=config, tools=tools):
            yield chunk
