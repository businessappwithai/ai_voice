"""SAAP gateway — FastAPI entrypoint (Phase 1 Epic 1.6, L6/L7).

Boots with a dev-friendly runtime factory: if LANGFLOW_URL and
LANGFLOW_FLOW_ID are set, chat runs through the real self-hosted
Langflow server; otherwise it falls back to DirectOllamaRuntime so
`uvicorn saap.gateway.app:app` works with nothing but Ollama running.
See saap.gateway.dev_runtime for why that fallback must never be used
tenant-facing.
"""
from __future__ import annotations

import os
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from saap.compliance import ComplianceChain, InterceptedRuntime, RuntimeRefused
from saap.compliance.audit import AuditRecorder, InMemoryAuditStore
from saap.compliance.chain import Interceptor
from saap.compliance.consent import ConsentGate, StaticConsentRegistry
from saap.compliance.pii import PIIMaskingInterceptor, SimplePIIAnalyzer, TokenVault
from saap.compliance.policy import InMemoryPolicyGuard, PolicyGuardInterceptor
from saap.compliance.rate_limit import InMemoryRateLimitBackend, RateLimiter
from saap.core.flow import FlowRef, LangflowRuntime, Orchestrator
from saap.plugins.llm.ollama import OllamaProvider

from .auth import AuthenticationError, DevSharedSecretVerifier, TokenVerifier, claims_to_tenant
from .dev_runtime import DEV_FLOW_REF, DirectOllamaRuntime
from .langflow_runtime import LangflowHTTPRuntime
from .orchestrator import InProcessOrchestrator
from .webchat import WebChatAdapter


def build_compliance_chain() -> ComplianceChain:
    interceptors: list[Interceptor] = [
        ConsentGate(StaticConsentRegistry()),
        PIIMaskingInterceptor(SimplePIIAnalyzer(), TokenVault()),
        PolicyGuardInterceptor(InMemoryPolicyGuard()),
        RateLimiter(InMemoryRateLimitBackend()),
        AuditRecorder(InMemoryAuditStore()),
    ]
    return ComplianceChain(interceptors)


def build_runtime_and_flow() -> tuple[LangflowRuntime, FlowRef]:
    langflow_url = os.environ.get("LANGFLOW_URL")
    langflow_flow_id = os.environ.get("LANGFLOW_FLOW_ID")
    if langflow_url and langflow_flow_id:
        runtime: LangflowRuntime = LangflowHTTPRuntime(
            langflow_url, api_key=os.environ.get("LANGFLOW_API_KEY")
        )
        flow = FlowRef(
            flow_id=langflow_flow_id,
            name=os.environ.get("LANGFLOW_FLOW_NAME", "vertical_agent_canonical"),
            version=os.environ.get("LANGFLOW_FLOW_VERSION", "unknown"),
            checksum=os.environ.get("LANGFLOW_FLOW_CHECKSUM", "unverified"),
            lint_report_id=os.environ.get("LANGFLOW_LINT_REPORT_ID", "unknown"),
        )
        return runtime, flow

    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    fast_model = os.environ.get("SAAP_FAST_MODEL", "qwen2.5:3b")
    return DirectOllamaRuntime(OllamaProvider(ollama_url), model=fast_model), DEV_FLOW_REF


def build_token_verifier() -> TokenVerifier:
    return DevSharedSecretVerifier()


def create_app() -> FastAPI:
    app = FastAPI(title="SAAP Gateway", version="0.1.0")

    chain = build_compliance_chain()
    runtime, flow_ref = build_runtime_and_flow()
    orchestrator: Orchestrator = InProcessOrchestrator(runtime)
    intercepted = InterceptedRuntime(chain, orchestrator)
    verifier = build_token_verifier()

    app.state.intercepted_runtime = intercepted
    app.state.flow_ref = flow_ref
    app.state.token_verifier = verifier

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": await runtime.health()}

    @app.websocket("/ws/chat")
    async def ws_chat(websocket: WebSocket, token: str) -> None:
        try:
            claims = verifier.verify(token)
        except AuthenticationError:
            await websocket.close(code=4401, reason="invalid widget token")
            return

        tenant = claims_to_tenant(claims)
        session_id = str(uuid4())
        await websocket.accept()
        adapter = WebChatAdapter(websocket, tenant, session_id)

        try:
            async for inbound in adapter.listen():
                try:
                    run_id = await intercepted.start(
                        tenant, flow_ref, inbound.message, session_id
                    )
                except RuntimeRefused as refused:
                    await adapter.render_refusal(refused.refusal_text)
                    continue
                await adapter.render(session_id, intercepted.events(run_id))
        except WebSocketDisconnect:
            pass
        finally:
            if websocket.client_state != WebSocketState.DISCONNECTED:
                await websocket.close()

    return app


app = create_app()
