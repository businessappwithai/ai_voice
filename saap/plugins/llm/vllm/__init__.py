"""VLLMProvider — production LLMProvider over a self-hosted vLLM
cluster's OpenAI-compatible endpoint (continuous batching, paged
attention, tensor parallel). License: Apache-2.0.

Second LLMProvider adapter, proving the interface really is swappable
(P3) alongside OllamaProvider — same contract, different backend
(deployment.yaml binds edge/dev -> ollama, datacenter -> vllm).
"""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
from saap.core.llm import Completion, GenerationConfig, LLMProvider, ToolSpec
from saap.core.registry import PluginRegistry
from saap.core.types import Message, ToolCall


def _to_openai_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    return [{"role": m.role, "content": m.content} for m in messages]


def _to_openai_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.input_schema},
        }
        for t in tools
    ]


class VLLMProvider:
    """Talks to `/v1/chat/completions` on a self-hosted vLLM
    OpenAI-compatible server. `config.json_schema` maps to vLLM's
    `guided_json` extra_body extension — grammar-constrained decoding
    via outlines/xgrammar under the hood, satisfying guarantee #2 of
    the LLMProvider contract server-side."""

    def __init__(
        self, base_url: str = "http://localhost:8000", *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=120.0)

    def _payload(
        self,
        messages: Sequence[Message],
        config: GenerationConfig,
        tools: Sequence[ToolSpec],
        *,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": _to_openai_messages(messages),
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "stream": stream,
        }
        if config.stop:
            payload["stop"] = list(config.stop)
        if tools:
            payload["tools"] = _to_openai_tools(tools)
        if config.json_schema is not None:
            payload["extra_body"] = {"guided_json": config.json_schema}
        return payload

    async def generate(
        self,
        messages: Sequence[Message],
        *,
        config: GenerationConfig,
        tools: Sequence[ToolSpec] = (),
    ) -> Completion:
        payload = self._payload(messages, config, tools, stream=False)
        start = time.perf_counter()
        response = await self._client.post(f"{self._base_url}/v1/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        latency_ms = (time.perf_counter() - start) * 1000

        choice = data["choices"][0]
        message = choice["message"]
        tool_calls = tuple(
            ToolCall(
                call_id=tc.get("id", f"vllm-{i}"),
                tool_name=tc["function"]["name"],
                arguments=json.loads(tc["function"].get("arguments") or "{}"),
            )
            for i, tc in enumerate(message.get("tool_calls") or [])
        )
        usage = data.get("usage", {})
        return Completion(
            text=message.get("content") or "",
            tool_calls=tool_calls,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
        )

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        config: GenerationConfig,
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, config, tools, stream=True)
        async with self._client.stream(
            "POST", f"{self._base_url}/v1/chat/completions", json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[len("data:") :].strip()
                if data_str == "[DONE]":
                    break
                chunk = json.loads(data_str)
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content

    async def health(self) -> bool:
        try:
            response = await self._client.get(f"{self._base_url}/health")
            return response.status_code == 200
        except httpx.HTTPError:
            return False


def register(registry: PluginRegistry) -> None:
    registry.register(LLMProvider, "vllm", lambda: VLLMProvider(), license="Apache-2.0")
