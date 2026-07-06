"""Orchestration contracts, Langflow edition.

The unit of behavior is not a code-defined graph but a **flow**: a JSON
document authored on the Langflow canvas. These contracts govern how
the platform references, executes, and governs flows — they are the
seam that keeps everything outside the canvas testable and typed.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from pydantic import BaseModel

from .types import Message, TenantContext


class FlowRef(BaseModel, frozen=True):
    """Immutable pointer to one *version* of a flow.

    Flows are exported from Langflow as JSON, committed to Git under
    `flows/<vertical>/<name>/<semver>.json`, and registered with a
    content checksum. Tenants bind to FlowRefs via blueprints — never
    to "whatever is currently on the canvas", which is how a visual
    tool stays production-safe.
    """

    flow_id: str  # Langflow flow UUID in the runtime
    name: str  # "dental.intake"
    version: str  # "2.3.0"
    checksum: str  # sha256 of the exported JSON
    lint_report_id: str  # proof it passed the Flow Linter


class FlowRunEvent(BaseModel, frozen=True):
    """Uniform stream envelope mapped from Langflow's streaming events:
    token deltas, component start/finish, HITL pauses, final output."""

    kind: str  # "token" | "component_started" | "component_finished"
    # | "awaiting_approval" | "final" | "error"
    payload: dict[str, Any]


class LangflowRuntime(Protocol):
    """Client for the self-hosted Langflow runtime.

    Implementations:
      * ``LangflowHTTPRuntime`` — REST/streaming API of the Langflow
        server (default for chat, webhooks, scheduled campaigns).
      * ``LangflowEmbeddedRuntime`` — executes the exported flow JSON
        in-process via `lfx` (voice workers, Phase 2 — removes the HTTP hop).

    Guarantees:
      1. `run` always injects tenant **global variables** (Langflow's
         per-request tweaks) resolved from the tenant blueprint — model
         endpoints, MCP allow-lists, locale, branding. Flows are
         tenant-agnostic templates; tenancy is data.
      2. `session_id` = the channel session, giving Langflow's built-in
         chat memory correct conversation scoping per caller.
      3. Streaming supports early cancel (voice barge-in).
    """

    async def run(
        self,
        tenant: TenantContext,
        flow: FlowRef,
        message: Message,
        *,
        session_id: str,
        tweaks: dict[str, Any] | None = None,
    ) -> AsyncIterator[FlowRunEvent]: ...

    async def upsert_flow(self, flow_json: dict[str, Any]) -> FlowRef:
        """Deploy pipeline only — humans design in a dev workspace;
        promotion to the prod runtime goes through Git + linter."""
        ...

    async def health(self) -> bool: ...


class ApprovalRequest(BaseModel, frozen=True):
    """Human-in-the-loop payload emitted by the HITLCheckpoint component.
    Resolution re-invokes the flow with the approval token — the
    pause/resume pattern that replaces engine-level interrupts."""

    request_id: str
    tenant_id: str
    flow: FlowRef
    session_id: str
    tool_call: dict[str, Any]
    rationale: str
    expires_at: str  # auto-deny on expiry


class ApprovalDecision(BaseModel, frozen=True):
    request_id: str
    approved: bool
    approver: str
    reason: str | None = None


class Orchestrator(Protocol):
    """Thin facade the gateway and voice workers use; binds runtime +
    compliance chain + approval queue. One implementation:
    ``LangflowOrchestrator``. The Protocol exists so tests can inject
    a fake, not to hedge on the engine choice."""

    async def start(
        self, tenant: TenantContext, flow: FlowRef, message: Message, session_id: str
    ) -> str: ...  # run_id

    def events(self, run_id: str) -> AsyncIterator[FlowRunEvent]: ...

    async def resume(self, request_id: str, decision: ApprovalDecision) -> None: ...

    async def cancel(self, run_id: str) -> None: ...
