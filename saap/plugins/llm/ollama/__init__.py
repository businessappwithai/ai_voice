"""OllamaProvider — edge/dev LLMProvider backed by a local Ollama daemon.

License: MIT (Ollama itself; this adapter is SAAP code, also MIT).
Registered as entry point `llm.ollama` in the `saap.plugins` group
(see pyproject.toml) so `PluginRegistry.load_entry_points()` picks it
up with zero core changes (P3).
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


def _to_ollama_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    return [{"role": m.role, "content": m.content} for m in messages]


def _to_ollama_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.input_schema},
        }
        for t in tools
    ]


class OllamaProvider:
    """Talks to `/api/chat` on a local Ollama daemon. Streaming uses
    NDJSON chunks; `config.json_schema` is passed through Ollama's
    native `format` parameter, which performs grammar-constrained
    decoding server-side (guarantee #2 of the LLMProvider contract)."""

    def __init__(self, base_url: str = "http://localhost:11434", *, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=120.0)

    async def generate(
        self,
        messages: Sequence[Message],
        *,
        config: GenerationConfig,
        tools: Sequence[ToolSpec] = (),
    ) -> Completion:
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": _to_ollama_messages(messages),
            "stream": False,
            "options": {"temperature": config.temperature, "num_predict": config.max_tokens},
        }
        if config.stop:
            payload["options"]["stop"] = list(config.stop)
        if config.json_schema is not None:
            payload["format"] = config.json_schema
        if tools:
            payload["tools"] = _to_ollama_tools(tools)

        start = time.perf_counter()
        response = await self._client.post(f"{self._base_url}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        latency_ms = (time.perf_counter() - start) * 1000

        message = data.get("message", {})
        tool_calls = tuple(
            ToolCall(
                call_id=f"ollama-{i}",
                tool_name=tc["function"]["name"],
                arguments=tc["function"].get("arguments", {}),
            )
            for i, tc in enumerate(message.get("tool_calls", []) or [])
        )
        return Completion(
            text=message.get("content", ""),
            tool_calls=tool_calls,
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            latency_ms=latency_ms,
        )

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        config: GenerationConfig,
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": _to_ollama_messages(messages),
            "stream": True,
            "options": {"temperature": config.temperature, "num_predict": config.max_tokens},
        }
        if config.json_schema is not None:
            payload["format"] = config.json_schema

        async with self._client.stream("POST", f"{self._base_url}/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
                if chunk.get("done"):
                    break

    async def health(self) -> bool:
        try:
            response = await self._client.get(f"{self._base_url}/api/tags")
            return response.status_code == 200
        except httpx.HTTPError:
            return False


def register(registry: PluginRegistry) -> None:
    """Entry point target: `saap.plugins.llm.ollama:register`.
    Deployment.yaml binds `llm.fast`/`llm.reason` keys to concrete
    base_urls; this default factory is the single-node dev binding."""
    registry.register(
        LLMProvider,
        "ollama",
        lambda: OllamaProvider(),
        license="MIT",
    )
