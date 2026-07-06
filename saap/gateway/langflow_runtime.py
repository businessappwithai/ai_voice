"""LangflowHTTPRuntime — REST/streaming client for a self-hosted
Langflow server (default LangflowRuntime binding for chat, webhooks,
and scheduled campaigns; the voice path uses LangflowEmbeddedRuntime
via `lfx` instead, Phase 2, to avoid the HTTP hop).
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from saap.core.flow import FlowRef, FlowRunEvent
from saap.core.types import Message, TenantContext


class LangflowHTTPRuntime:
    def __init__(self, base_url: str, *, api_key: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        headers = {"x-api-key": api_key} if api_key else {}
        self._client = client or httpx.AsyncClient(timeout=30.0, headers=headers)

    async def run(
        self,
        tenant: TenantContext,
        flow: FlowRef,
        message: Message,
        *,
        session_id: str,
        tweaks: dict[str, Any] | None = None,
    ) -> AsyncIterator[FlowRunEvent]:
        # Tenant global variables: model endpoints, MCP allow-lists,
        # locale, branding — resolved from the tenant blueprint by the
        # caller and passed in `tweaks`; flows stay tenant-agnostic
        # templates (tenancy is data, per the flow.py contract).
        payload = {
            "input_value": message.content,
            "input_type": "chat",
            "output_type": "chat",
            "session_id": session_id,
            "tweaks": tweaks or {},
        }
        url = f"{self._base_url}/api/v1/run/{flow.flow_id}?stream=true"
        async with self._client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                event = self._parse_event(line)
                if event is not None:
                    yield event

    def _parse_event(self, line: str) -> FlowRunEvent | None:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None
        event_type = data.get("event", "message")
        return FlowRunEvent(kind=_map_event_kind(event_type), payload=data.get("data", data))

    async def upsert_flow(self, flow_json: dict[str, Any]) -> FlowRef:
        response = await self._client.post(f"{self._base_url}/api/v1/flows/", json=flow_json)
        response.raise_for_status()
        data = response.json()
        import hashlib

        checksum = hashlib.sha256(json.dumps(flow_json, sort_keys=True).encode()).hexdigest()
        return FlowRef(
            flow_id=data["id"],
            name=data.get("name", flow_json.get("name", "unnamed")),
            version=data.get("updated_at", "0.0.0"),
            checksum=checksum,
            lint_report_id="",  # populated by the caller after tools/flow_linter runs
        )

    async def health(self) -> bool:
        try:
            response = await self._client.get(f"{self._base_url}/health")
            return response.status_code == 200
        except httpx.HTTPError:
            return False


def _map_event_kind(langflow_event: str) -> str:
    mapping = {
        "token": "token",
        "add_message": "component_finished",
        "end": "final",
        "error": "error",
    }
    return mapping.get(langflow_event, langflow_event)
