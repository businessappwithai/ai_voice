# Sovereign AI Automation Platform (SAAP)
## A Fully Open-Source, Local-First Architecture for AI Automation Agencies

**Version:** 2.0 (Langflow-native orchestration) · **Status:** Reference Architecture · **License Policy:** OSI-approved licenses only (MIT / Apache-2.0 / BSD / MPL-2.0; AGPL permitted for self-hosted infrastructure)

---

## 1. Purpose and Scope

This document defines the complete reference architecture for an AI Automation Agency (AAA) platform as described in the accompanying strategic analysis, re-imagined under one non-negotiable constraint: **every component — inference, orchestration, memory, voice, telephony, compliance, and CRM — must be open source and runnable on infrastructure the agency controls.** No proprietary SaaS (Vapi, Retell, Synthflow, GoHighLevel, Pinecone, OpenAI, Anthropic API) appears anywhere in the runtime path.

The architecture delivers the same commercial capabilities the strategic analysis identifies as high-value:

1. **AI Operating Systems** for client businesses — agents that read and act on the client's real operational data via the Model Context Protocol (MCP).
2. **Autonomous Voice AI** — full-duplex, sub-second-latency phone agents built from open speech models.
3. **Vertical RAG knowledge systems** — hallucination-grounded agents over client documents.
4. **Multilingual pipelines** — Indic and global language support using open models (AI4Bharat IndicTrans2 family) rather than closed translation APIs.
5. **Compliance-by-architecture** — DPDP/GDPR-grade PII masking, consent enforcement, immutable audit trails, and human-in-the-loop (HITL) gates, all self-hosted.
6. **Multi-tenant agency operations** — one deployment, many isolated client sub-accounts ("snapshots" as code).

### 1.1 Design Principles

| # | Principle | Consequence in the architecture |
|---|-----------|--------------------------------|
| P1 | **Open source only** | Every dependency carries an OSI-approved license; a license gate in CI rejects anything else. |
| P2 | **Local-first inference** | All LLM, embedding, STT, TTS, and translation models run on agency/client hardware (Ollama, vLLM, llama.cpp). Data never leaves the trust boundary. |
| P3 | **Interface-driven modularity** | Every capability is defined as an abstract interface (`Protocol`/ABC). Concrete engines (Qdrant vs. Chroma, Ollama vs. vLLM) are swappable plugins registered at runtime. |
| P4 | **MCP as the universal tool bus** | All external-system access (CRM, calendars, ticketing, databases) flows through MCP servers. No bespoke N×M connectors. |
| P5 | **Deterministic guardrails around probabilistic cores** | LLMs propose; policy engines, schema validators, and HITL gates dispose. High-risk actions never execute on model output alone. |
| P6 | **Compliance as middleware, not afterthought** | PII masking, consent checks, and audit logging are interceptors in the pipeline that no agent can bypass. |
| P7 | **Multi-tenancy by construction** | Tenant ID is a first-class field on every message, memory record, tool call, and audit event. Physical isolation options (per-tenant vector collections, per-tenant DB schemas) are configuration, not code changes. |
| P8 | **Vendor-neutral state** | All state lives in PostgreSQL, Qdrant, Redis, and object storage (MinIO) — all self-hostable, all exportable. |

### 1.2 Non-Goals

- Training foundation models from scratch (fine-tuning adapters via open tooling is in scope).
- Replacing the agency's human sales process — the platform automates delivery, audit tooling, and operations.
- Supporting closed-model fallbacks. There is deliberately no `OpenAIProvider` in this codebase.

---

## 2. Open-Source Technology Selection

Every proprietary component named in the strategic analysis is mapped to an open-source, self-hostable equivalent. Licenses are stated because P1 makes them an architectural property, not a legal footnote.

### 2.1 LLM Inference (replaces Claude/GPT APIs)

| Component | Choice | License | Role |
|-----------|--------|---------|------|
| Model server (throughput) | **vLLM** | Apache-2.0 | Production GPU serving with continuous batching, paged attention, OpenAI-compatible local endpoint |
| Model server (edge/dev) | **Ollama** (wraps llama.cpp) | MIT | Single-node, CPU/GPU, model lifecycle management, quantized GGUF |
| Bare-metal runtime | **llama.cpp** | MIT | Embedded/edge inference, CPU-only client sites |
| Reasoning models | **Llama 3.3 70B**, **Qwen 2.5 72B/32B**, **Mistral Small 3**, **DeepSeek-R1 distills** | Llama Community / Apache-2.0 / Apache-2.0 / MIT | Tool-calling dialog engines |
| Small fast models | **Qwen 2.5 7B**, **Llama 3.2 3B**, **Phi-4** | Apache-2.0 / Llama / MIT | Routing, classification, PII pre-screen, low-latency voice turns |
| Embeddings | **BGE-M3**, **nomic-embed-text**, **E5-Mistral** | MIT / Apache-2.0 / MIT | Multilingual dense + sparse retrieval |
| Reranking | **bge-reranker-v2-m3** | Apache-2.0 | Precision pass over retrieved chunks |
| Fine-tuning | **Unsloth**, **PEFT/LoRA**, **Axolotl** | Apache-2.0 | Vertical adapters (dental intake tone, legal intake style) |

### 2.2 Agent Orchestration and Workflow (Langflow — sole engine)

Per the platform mandate, **Langflow** (MIT, `github.com/langflow-ai/langflow`) is the *only* orchestration and workflow engine. Every agent, automation, campaign, and audit pipeline is a Langflow **flow**: designed visually on the canvas, exported as versioned JSON, and executed by the self-hosted Langflow runtime. There is no LangGraph, CrewAI, AutoGen, Temporal, or n8n anywhere in the stack — anything that looks like workflow logic must be expressible on the canvas, which is what keeps the system operable by non-engineers.

| Component | Choice | License | Role |
|-----------|--------|---------|------|
| Visual designer + runtime | **Langflow** (self-hosted) | MIT | Drag-and-drop flow IDE; REST + streaming execution API; session-scoped memory; Python **custom components**; native **MCP client and MCP server** support; local models via Ollama/OpenAI-compatible (vLLM) components |
| Embedded runtime | **lfx** (Langflow's runtime package) | MIT | Runs exported flows in-process inside the voice workers, avoiding an HTTP hop on the latency-critical path (§7) |
| Flow triggering | **SAAP FlowScheduler** (thin APScheduler service) | MIT | Cron/interval/event triggers that do nothing but call Langflow's `/api/v1/run/{flow_id}` — zero business logic lives outside flows |
| Tool protocol | **MCP** (Langflow-native) | MIT / LF-stewarded spec | Flows consume tenant MCP servers as tools; finished flows are themselves publishable as MCP servers for composition |

> **Design consequence:** SAAP's job shrinks to (a) a library of hardened **custom components** that expose platform services (compliance, RAG, model routing, MCP pool) inside the Langflow canvas, and (b) governance around flows (versioning, linting, tenancy, scheduling). The canvas is the programming surface; the platform is the guardrail.

### 2.3 Memory, Data, and Retrieval (replaces Pinecone/Airtable)

| Component | Choice | License | Role |
|-----------|--------|---------|------|
| Vector DB | **Qdrant** (primary), Chroma/Milvus/pgvector adapters | Apache-2.0 | Tenant-scoped semantic memory |
| Relational + pgvector | **PostgreSQL 16** | PostgreSQL License | System of record, consent registry, audit trail |
| Structured "Airtable" | **NocoDB** or **Baserow** | AGPL-3.0 / MIT+premium² | Client-facing structured data UIs |
| Cache / queues / pub-sub | **Redis** (or **Valkey**) | RSALv2² / BSD-3 | Session state, VAD frame buffers, rate limits |
| Object storage | **MinIO** | AGPL-3.0 | Call recordings, document originals |
| Document parsing | **Docling**, **unstructured** | MIT / Apache-2.0 | PDF/DOCX → chunkable text for RAG |
| Orchestrated ETL | **Apache Airflow** or **Dagster** | Apache-2.0 | Nightly re-index, data-retention deletion jobs |

> ² Where a project's newest license drifts from OSI (Redis ≥7.4), the architecture pins the fork/alternative (**Valkey**, BSD-3) — this is exactly what the license gate exists to catch.

### 2.4 Voice Stack (replaces Vapi / Retell / Synthflow / Bland)

| Component | Choice | License | Role |
|-----------|--------|---------|------|
| Realtime media + agent framework | **LiveKit + LiveKit Agents** | Apache-2.0 | WebRTC rooms, SIP bridge, turn-taking runtime |
| SIP / PSTN | **FreeSWITCH** or **Asterisk** | MPL-1.1 / GPL-2.0 | Carrier trunks, IVR fallback, call control |
| STT | **faster-whisper** (CTranslate2 Whisper), **Vosk** (embedded) | MIT / Apache-2.0 | Streaming transcription |
| VAD | **Silero VAD** | MIT | Barge-in detection, endpointing |
| TTS | **Piper** (low-latency), **Coqui XTTS-v2**³ | MIT / Coqui Public³ | Sub-100 ms synthesis / expressive cloning |
| Turn-taking | LiveKit turn detector + Silero | Apache-2.0 / MIT | Full-duplex interruption handling |

> ³ XTTS-v2 model weights carry the Coqui Public Model License (non-commercial clauses). For strict commercial P1 compliance default to **Piper** voices; treat XTTS as an optional plugin the license gate marks "restricted".

### 2.5 Multilingual / Indic Pipeline (replaces Bhashini's hosted APIs with its open lineage)

| Component | Choice | License | Role |
|-----------|--------|---------|------|
| Translation (22 Indic languages) | **AI4Bharat IndicTrans2** | MIT (code) / open weights | Text↔text NMT, En↔Indic and Indic↔Indic |
| Indic STT | **IndicConformer / IndicWhisper**, fine-tuned Whisper | MIT / Apache-2.0 | Tamil/Hindi/… speech recognition |
| Indic TTS | **Indic-TTS (AI4Bharat)**, Piper Indic voices | MIT | Regional-language synthesis |
| Transliteration | **IndicXlit** | MIT | Roman↔native script normalization |

### 2.6 Compliance, Security, Observability (replaces Protecto-style SaaS)

| Component | Choice | License | Role |
|-----------|--------|---------|------|
| PII detection/masking | **Microsoft Presidio** | MIT | Inline analyzer + anonymizer interceptor |
| Policy engine | **Open Policy Agent (OPA)** | Apache-2.0 | Declarative action-authorization (Rego policies per tenant) |
| Secrets | **HashiCorp Vault** (or **Infisical**, MIT) | BUSL² → prefer **OpenBao** (MPL-2.0) | Tenant credential isolation for MCP servers |
| AuthN/Z | **Keycloak** | Apache-2.0 | OAuth 2.1 for remote MCP servers, agency SSO |
| LLM observability | **Langfuse** | MIT (core) | Traces, evals, cost/latency per tenant |
| Metrics/logs | **Prometheus + Grafana + Loki** | Apache-2.0 / AGPL | SLOs, sub-second-latency dashboards |
| Guardrails | **NeMo Guardrails** / **Guardrails-AI** | Apache-2.0 | Topical rails, jailbreak screens, output schemas |
| CRM (replaces GoHighLevel) | **Twenty** or **EspoCRM** / **SuiteCRM** | AGPL-3.0 / AGPL | White-labelable client CRM with REST APIs wrapped as MCP servers |

---

## 3. Layered System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  L7  EXPERIENCE LAYER                                                       │
│      Web chat widget · Agency console (React) · Client dashboards ·         │
│      PSTN/SIP callers · WhatsApp/webhook channels                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  L6  CHANNEL ADAPTERS                                                       │
│      ChatChannelAdapter · VoiceSessionAdapter (LiveKit) ·                   │
│      WebhookAdapter · EmailAdapter        → normalize to InboundEvent       │
├─────────────────────────────────────────────────────────────────────────────┤
│  L5  COMPLIANCE INTERCEPTOR CHAIN  (cannot be bypassed — P6)                │
│      ConsentGate → PIIMaskingInterceptor → PolicyGuard (OPA) →              │
│      AuditRecorder → RateLimiter                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  L4  ORCHESTRATION LAYER  — LANGFLOW (sole engine)                          │
│      Langflow visual designer + runtime · flows-as-versioned-JSON ·         │
│      SAAP custom component library · FlowScheduler triggers ·               │
│      HITL pause/resume queue · Flow Linter (sealed compliance path)         │
├─────────────────────────────────────────────────────────────────────────────┤
│  L3  CAPABILITY SERVICES                                                    │
│      RAG Service (retrieve→rerank→ground) · Voice Pipeline (VAD→STT→        │
│      Dialog→TTS) · Translation Service (IndicTrans2) · Skill/Tool Service   │
├─────────────────────────────────────────────────────────────────────────────┤
│  L2  MCP TOOL BUS                                                           │
│      MCPClientPool · per-tenant MCP servers (CRM, calendar, tickets,        │
│      inventory, custom SQL) · OAuth2.1 via Keycloak · tool allow-lists     │
├─────────────────────────────────────────────────────────────────────────────┤
│  L1  MODEL RUNTIME                                                          │
│      vLLM cluster (70B reasoning) · Ollama nodes (7B fast path) ·           │
│      faster-whisper · Piper · IndicTrans2 · BGE-M3 embeddings               │
├─────────────────────────────────────────────────────────────────────────────┤
│  L0  STATE & INFRA                                                          │
│      PostgreSQL (records, consent, audit) · Qdrant (vectors) ·              │
│      Valkey/Redis (sessions) · MinIO (blobs) · Keycloak · OpenBao ·         │
│      Prometheus/Grafana/Langfuse                                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Golden rule of data flow:** nothing crosses from L6 to L4 without traversing L5, and no agent in L4 touches an external system except through L2. These two chokepoints are what make DPDP/GDPR compliance and NSA-style MCP hardening enforceable in code rather than in policy documents.

---
## 4. Core Abstractions (the Plugin Contract Layer)

Everything below lives in package `saap.core`. These interfaces are the *only* things the orchestration layer is allowed to import; concrete engines live in `saap.plugins.*` and are bound via the registry (§4.6). Python 3.11+, `typing.Protocol` for structural typing, Pydantic v2 for all data crossing a boundary.

### 4.1 Foundational Types

```python
# saap/core/types.py
"""
Foundational value objects shared by every layer.

Design notes
------------
* `TenantContext` is mandatory on every request-scoped object (P7).
  There is deliberately no way to construct a pipeline call without one.
* All models are immutable (frozen=True) so interceptors can never
  mutate a message in place without producing an auditable new object.
"""
from __future__ import annotations
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class Locale(StrEnum):
    """BCP-47 subset the platform ships voices/NMT models for."""
    EN_IN = "en-IN"; EN_US = "en-US"
    TA_IN = "ta-IN"; HI_IN = "hi-IN"; MR_IN = "mr-IN"; GU_IN = "gu-IN"
    # extended by plugins via LocaleRegistry


class DataClass(StrEnum):
    """DPDP/GDPR-aligned sensitivity classes, attached to every payload."""
    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"           # PII — requires consent + masking
    SENSITIVE_PERSONAL = "spii"     # health, financial, Aadhaar/KYC
    

class TenantContext(BaseModel, frozen=True):
    """
    Identity + isolation envelope for a single client (sub-account).

    Every service method takes this as its first argument. Storage
    adapters MUST scope reads/writes with it; the compliance chain
    MUST log it; the MCP pool MUST resolve credentials with it.
    """
    tenant_id: UUID
    vertical: str                        # "dental", "realestate", "legal", ...
    locale: Locale = Locale.EN_IN
    data_residency: str = "in"           # ISO country for residency policy
    consent_scope: frozenset[str] = frozenset()   # granted purposes
    trace_id: UUID = Field(default_factory=uuid4)


class Message(BaseModel, frozen=True):
    """A single conversational turn, channel-agnostic."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None              # tool name for role="tool"
    data_class: DataClass = DataClass.PERSONAL
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel, frozen=True):
    """LLM-proposed invocation. *Proposed* — PolicyGuard decides (P5)."""
    call_id: str
    tool_name: str                       # namespaced: "mcp.crm.create_contact"
    arguments: dict[str, Any]
    risk_tier: Literal["read", "write", "high_risk"] = "read"


class ToolResult(BaseModel, frozen=True):
    call_id: str
    ok: bool
    content: Any
    error: str | None = None
```

### 4.2 LLM Provider Interface (Local Only)

```python
# saap/core/llm.py
"""
Local LLM provider abstraction.

The orchestration layer NEVER imports vllm/ollama/llama_cpp directly.
It talks to `LLMProvider`; the registry binds the concrete engine per
deployment profile (edge → Ollama, datacenter → vLLM).

There is intentionally no provider for hosted APIs — the type system
is the enforcement mechanism for the open-source/local mandate (P1/P2).
"""
from __future__ import annotations
from typing import AsyncIterator, Protocol, Sequence, runtime_checkable
from pydantic import BaseModel
from .types import Message, ToolCall


class GenerationConfig(BaseModel, frozen=True):
    model: str                       # local model tag, e.g. "qwen2.5:72b-instruct-q4"
    temperature: float = 0.2
    max_tokens: int = 1024
    stop: tuple[str, ...] = ()
    json_schema: dict | None = None  # constrained decoding (outlines/xgrammar)


class ToolSpec(BaseModel, frozen=True):
    """JSON-Schema tool description handed to the model (MCP-derived)."""
    name: str
    description: str
    input_schema: dict


class Completion(BaseModel, frozen=True):
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0


@runtime_checkable
class LLMProvider(Protocol):
    """
    Contract for any local inference backend.

    Implementations
    ---------------
    * ``VLLMProvider``    — OpenAI-compatible HTTP to a self-hosted vLLM
                            cluster; continuous batching; tensor parallel.
    * ``OllamaProvider``  — /api/chat on a local Ollama daemon; GGUF quant.
    * ``LlamaCppProvider``— in-process llama.cpp bindings for edge boxes.

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
        (caller cancels on barge-in — see VoicePipeline §7)."""
        ...

    async def health(self) -> bool: ...


class ModelRouter:
    """
    Cost/latency-aware routing across local models (P3, P5).

    Routes by task profile rather than hardcoding model names in agents:

    * ``fast``    → 3–8B model on Ollama   (intent routing, voice turns)
    * ``reason``  → 32–72B on vLLM         (multi-step tool planning)
    * ``extract`` → small model + JSON grammar (structured extraction)

    Tenants may pin overrides (e.g., a legal tenant pins `reason` to a
    LoRA-adapted Qwen 72B) via `TenantModelPolicy` in Postgres.
    """

    def __init__(self, providers: dict[str, LLMProvider],
                 policy_store: "TenantModelPolicyStore") -> None: ...

    async def route(self, tenant, task: str) -> tuple[LLMProvider, GenerationConfig]: ...
```

### 4.3 Embeddings, Vector Store, and RAG Contracts

```python
# saap/core/memory.py
"""
Retrieval subsystem contracts (replaces Pinecone + Airtable roles).

Tenant isolation strategy (P7):
  * Qdrant: one collection per tenant OR shared collection with a
    mandatory `tenant_id` payload filter — chosen per data_residency.
  * The interface makes it impossible to query without a TenantContext.
"""
from __future__ import annotations
from typing import Protocol, Sequence
from uuid import UUID
from pydantic import BaseModel
from .types import TenantContext, DataClass


class EmbeddingProvider(Protocol):
    """BGE-M3 / nomic-embed via local inference. Dim advertised so
    stores can validate collections at bind time."""
    dimension: int
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class DocumentChunk(BaseModel, frozen=True):
    chunk_id: UUID
    source_uri: str                   # minio://tenant/{id}/handbook.pdf#p12
    text: str
    data_class: DataClass
    metadata: dict = {}


class RetrievedChunk(BaseModel, frozen=True):
    chunk: DocumentChunk
    score: float


class VectorStore(Protocol):
    """
    Implementations: ``QdrantStore`` (default), ``ChromaStore``,
    ``PgVectorStore``, ``MilvusStore`` — all Apache/MIT licensed.
    """
    async def upsert(self, tenant: TenantContext,
                     chunks: Sequence[DocumentChunk],
                     vectors: Sequence[list[float]]) -> None: ...

    async def search(self, tenant: TenantContext, query_vector: list[float],
                     *, k: int = 8, filters: dict | None = None
                     ) -> list[RetrievedChunk]: ...

    async def delete_by_source(self, tenant: TenantContext, source_uri: str) -> int:
        """Required by DPDP purpose-fulfillment erasure jobs (§9.4)."""
        ...


class Reranker(Protocol):
    """bge-reranker-v2-m3 cross-encoder precision pass."""
    async def rerank(self, query: str, chunks: Sequence[RetrievedChunk],
                     top_n: int) -> list[RetrievedChunk]: ...


class RAGService:
    """
    Grounded retrieval façade used by agents (never raw VectorStore).

    Pipeline: hybrid search (dense + BM25 sparse from BGE-M3)
              → rerank → citation packing → grounding contract.

    The grounding contract: the returned context block carries chunk IDs;
    the generation prompt requires inline citations; `verify_grounding`
    runs an NLI-style check with a small local model and flags
    unsupported claims before the answer leaves L3 (anti-hallucination, P5).
    """
    def __init__(self, embedder: EmbeddingProvider, store: VectorStore,
                 reranker: Reranker, verifier_llm: "LLMProvider") -> None: ...

    async def retrieve(self, tenant: TenantContext, query: str,
                       *, k: int = 6) -> list[RetrievedChunk]: ...

    async def answer(self, tenant: TenantContext, question: str) -> "GroundedAnswer": ...
```

### 4.4 MCP Tool Bus (L2)

```python
# saap/core/mcp.py
"""
Model Context Protocol integration — the universal tool bus (P4).

Threat model (NSA MCP guidance, §Cybersecurity in the source analysis):
  * Dynamic tool invocation  → mitigated by static per-tenant allow-lists;
    tools discovered at runtime are quarantined until an operator approves.
  * Implicit trust of agent output → every ToolCall passes PolicyGuard
    (OPA) and risk-tier gating before dispatch (P5).
  * Payload injection → arguments are re-validated against the server's
    JSON Schema *client-side* before send; free-form strings destined for
    SQL/shell-like tools pass a Presidio + injection-pattern screen.
  * Credential blast radius → per-tenant OAuth 2.1 tokens from Keycloak,
    secrets resolved from OpenBao at call time, never stored in agent state.
"""
from __future__ import annotations
from typing import Protocol, Sequence
from pydantic import BaseModel
from .types import TenantContext, ToolCall, ToolResult
from .llm import ToolSpec


class MCPServerConfig(BaseModel, frozen=True):
    server_id: str                    # "crm", "calendar", "inventory"
    transport: str                    # "stdio" | "streamable-http"
    endpoint: str                     # command or URL
    allowed_tools: frozenset[str]     # explicit allow-list (never "*")
    risk_overrides: dict[str, str] = {}   # tool → "high_risk" escalation
    oauth_audience: str | None = None     # Keycloak client for remote servers


class MCPConnection(Protocol):
    """One live session to one MCP server (official MIT Python SDK under
    the hood). Reconnects transparently; surfaces server-pushed
    capability changes as `ToolCatalogChanged` events (quarantined)."""
    async def list_tools(self) -> Sequence[ToolSpec]: ...
    async def call_tool(self, name: str, arguments: dict) -> ToolResult: ...
    async def close(self) -> None: ...


class MCPClientPool:
    """
    Tenant-scoped connection manager.

    * `catalog(tenant)`  → merged, allow-listed ToolSpecs handed to the LLM.
      Names are namespaced `mcp.<server_id>.<tool>` to prevent cross-server
      tool-name collisions (a known MCP spoofing vector).
    * `dispatch(tenant, call)` → resolves the connection, re-validates the
      schema, injects tenant credentials, executes, wraps ToolResult.

    The pool is the ONLY code path in the platform allowed to perform
    outbound side effects. Agents receive it pre-wrapped in the
    compliance chain (§6) so a bypass is not expressible in code.
    """
    def __init__(self, config_store: "TenantMCPConfigStore",
                 auth: "OAuthTokenBroker", vault: "SecretResolver") -> None: ...

    async def catalog(self, tenant: TenantContext) -> list[ToolSpec]: ...
    async def dispatch(self, tenant: TenantContext, call: ToolCall) -> ToolResult: ...
```

### 4.5 Flow and Orchestrator Contracts (L4 — Langflow)

```python
# saap/core/flow.py
"""
Orchestration contracts, Langflow edition.

The unit of behavior is no longer a code-defined graph but a **flow**:
a JSON document authored on the Langflow canvas. These contracts govern
how the platform references, executes, and governs flows — they are the
seam that keeps everything outside the canvas testable and typed.
"""
from __future__ import annotations
from typing import Any, AsyncIterator, Protocol
from pydantic import BaseModel
from .types import TenantContext, Message


class FlowRef(BaseModel, frozen=True):
    """
    Immutable pointer to one *version* of a flow.

    Flows are exported from Langflow as JSON, committed to Git under
    `flows/<vertical>/<name>/<semver>.json`, and registered with a
    content checksum. Tenants bind to FlowRefs via blueprints (§9.2) —
    never to "whatever is currently on the canvas", which is how a
    visual tool stays production-safe.
    """
    flow_id: str                 # Langflow flow UUID in the runtime
    name: str                    # "dental.intake"
    version: str                 # "2.3.0"
    checksum: str                # sha256 of the exported JSON
    lint_report_id: str          # proof it passed the Flow Linter (§5.3)


class FlowRunEvent(BaseModel, frozen=True):
    """Uniform stream envelope mapped from Langflow's streaming events:
    token deltas, component start/finish, HITL pauses, final output."""
    kind: str    # "token" | "component_started" | "component_finished"
                 # | "awaiting_approval" | "final" | "error"
    payload: dict[str, Any]


class LangflowRuntime(Protocol):
    """
    Client for the self-hosted Langflow runtime.

    Implementations:
      * ``LangflowHTTPRuntime`` — REST/streaming API of the Langflow
        server (default for chat, webhooks, scheduled campaigns).
      * ``LangflowEmbeddedRuntime`` — executes the exported flow JSON
        in-process via `lfx` (voice workers, §7 — removes the HTTP hop).

    Guarantees:
      1. `run` always injects tenant **global variables** (Langflow's
         per-request tweaks) resolved from the tenant blueprint — model
         endpoints, MCP allow-lists, locale, branding. Flows are
         tenant-agnostic templates; tenancy is data.
      2. `session_id` = the channel session (§12.1), giving Langflow's
         built-in chat memory correct conversation scoping per caller.
      3. Streaming supports early cancel (voice barge-in).
    """

    async def run(self, tenant: TenantContext, flow: FlowRef,
                  message: Message, *, session_id: str,
                  tweaks: dict[str, Any] | None = None
                  ) -> AsyncIterator[FlowRunEvent]: ...

    async def upsert_flow(self, flow_json: dict) -> FlowRef:
        """Deploy pipeline only — humans design in a dev workspace;
        promotion to the prod runtime goes through Git + linter."""
        ...

    async def health(self) -> bool: ...


class ApprovalRequest(BaseModel, frozen=True):
    """Human-in-the-loop payload emitted by the HITLCheckpoint component
    (§5.4). Resolution re-invokes the flow with the approval token —
    the pause/resume pattern that replaces engine-level interrupts."""
    request_id: str
    tenant_id: str
    flow: FlowRef
    session_id: str
    tool_call: dict
    rationale: str
    expires_at: str              # auto-deny on expiry


class Orchestrator(Protocol):
    """Thin façade the gateway and voice workers use; binds runtime +
    compliance chain + approval queue. One implementation:
    ``LangflowOrchestrator``. The Protocol exists so tests can inject
    a fake, not to hedge on the engine choice."""
    async def start(self, tenant: TenantContext, flow: FlowRef,
                    message: Message, session_id: str) -> str: ...   # run_id
    def events(self, run_id: str) -> AsyncIterator[FlowRunEvent]: ...
    async def resume(self, request_id: str,
                     decision: "ApprovalDecision") -> None: ...
    async def cancel(self, run_id: str) -> None: ...
```
### 4.6 Plugin Registry — How Extensibility Actually Works

```python
# saap/core/registry.py
"""
Runtime plugin binding via Python entry points (setuptools group
`saap.plugins`). Adding a new vector store, TTS engine, or vertical
agent = shipping a pip-installable package; zero core changes (P3).

deployment.yaml chooses bindings per environment:

    bindings:
      llm.fast:    ollama        # edge profile
      llm.reason:  vllm
      vectorstore: qdrant
      stt:         faster_whisper
      tts:         piper
      orchestrator: langflow    # sole engine — see §2.2/§5
    license_gate:
      allow: [MIT, Apache-2.0, BSD-3-Clause, MPL-2.0, PostgreSQL, AGPL-3.0]
      review: [SUL-1.0]          # n8n — internal-use review
      deny:  ["*proprietary*", BUSL-1.1, RSALv2]
"""
from typing import Protocol, TypeVar

T = TypeVar("T")


class PluginRegistry:
    def register(self, interface: type[T], key: str, factory: "Factory[T]",
                 *, license: str) -> None:
        """`license` is mandatory; the LicenseGate refuses to register
        factories whose license is not on the allow list — the P1 rule
        is enforced at import time, not in a wiki page."""
        ...

    def resolve(self, interface: type[T], key: str) -> T: ...
```

---
## 5. Orchestration Layer in Depth (Langflow)

### 5.1 The Canonical Flow Topology

Every vertical agent is a Langflow flow assembled from the SAAP custom component library. The canonical canvas — the visual equivalent of the pipeline the strategic analysis describes — looks like this:

```
 Langflow canvas: "vertical_agent_canonical" (exported → flows/…/x.y.z.json)

 [Chat Input]                                             [Chat Output]
      │                                                        ▲
      ▼                                                        │
 ┌───────────────────┐    ┌──────────────────┐    ┌────────────────────┐
 │ ComplianceIngress │───▶│ IntentRouter     │───▶│ GroundedResponder  │
 │ (SAAP, sealed)    │    │ (ModelRouterLLM, │    │ (verify citations, │
 │ consent✓ + PII    │    │  profile="fast") │    │  stream tokens)    │
 │ masking + audit   │    └───┬──────────┬───┘    └─────────▲──────────┘
 └───────────────────┘  smalltalk    business             │
                            │            ▼                    │
                            │      ┌──────────────┐    ┌──────┴───────┐
                            │      │ RAGRetriever │───▶│ AgentCore    │
                            │      │ (SAAP)       │    │ (Langflow    │
                            │      └──────────────┘    │  Agent comp, │
                            │                          │  "reason")   │
                            ▼                          └──────┬───────┘
                     [deflection reply]                       │ proposed ToolCalls
                                                              ▼
                                                   ┌────────────────────┐
                                                   │ MCPToolkit (SAAP)  │
                                                   │ PolicyGuard(OPA) → │
                                                   │  allow: dispatch   │
                                                   │  high_risk: ───────┼──▶ HITLCheckpoint
                                                   └────────────────────┘    (pause + queue)
                                                              │
                                                   ┌──────────▼─────────┐
                                                   │ AuditClose (SAAP,  │
                                                   │ sealed)            │
                                                   └────────────────────┘
```

The agency's engineers build and maintain this template; vertical designers **clone it on the canvas** and edit only the middle: prompts, intents, extra enrichment components, tool selections. That is the visual-designer workflow you get from Langflow — without surrendering the compliance guarantees, because of §5.3.

### 5.2 The SAAP Custom Component Library

Platform services enter the canvas exclusively as Langflow **custom components** — Python classes extending Langflow's `Component` base, pip-installed into the runtime image and appearing in the sidebar under a "SAAP" category.

```python
# saap/langflow_components/compliance_ingress.py
"""
Sealed ingress component. First node of every production flow.

Wraps the L5 interceptor chain (§6): ConsentGate → PIIMasking →
RateLimiter → AuditRecorder. Downstream components receive only the
masked Message and the TenantContext handle — the raw payload never
enters the canvas graph, so no flow wiring mistake can leak PII to a
model component.
"""
from langflow.custom import Component
from langflow.io import MessageInput, Output
from langflow.schema.message import Message as LFMessage


class ComplianceIngress(Component):
    display_name = "SAAP · Compliance Ingress"
    description = "Consent check, PII masking, audit. Mandatory first node."
    icon = "shield"
    sealed = True                      # Flow Linter metadata (§5.3)

    inputs = [MessageInput(name="raw_input", display_name="Inbound")]
    outputs = [Output(name="masked", display_name="Masked Message",
                      method="process")]

    async def process(self) -> LFMessage:
        tenant = self._tenant_from_globals()      # injected tweaks, §4.5
        envelope = await self.chain.before(tenant, self.raw_input)
        return envelope.to_langflow_message()
```

```python
# saap/langflow_components/mcp_toolkit.py
"""
Hardened MCP tool provider for Langflow Agent components.

Langflow ships a native MCP client; this component deliberately wraps
it rather than exposing it raw, because the NSA-guidance mitigations
(§4.4) must be non-optional:

  * emits ONLY the tenant's allow-listed, namespaced ToolSpecs to the
    connected Agent component;
  * every proposed call passes PolicyGuard (OPA) — `allow`, `deny`, or
    `require_human`;
  * `require_human` short-circuits execution and emits an
    ApprovalRequest via the HITLCheckpoint output port;
  * arguments re-validated against server JSON Schema client-side;
  * credentials resolved per-tenant from OpenBao at call time.

On the canvas this looks like any other toolkit the designer drags
onto an Agent — the security engineering is invisible and unremovable.
"""
class MCPToolkit(Component):
    display_name = "SAAP · MCP Toolkit (governed)"
    sealed = True
    inputs = [...]                                 # server selection (from blueprint)
    outputs = [Output(name="tools", method="build_tools"),
               Output(name="approval", method="pending_approval")]
```

The full library, each one a thin canvas adapter over the §4 interfaces:

| Component | Wraps | Sealed | Purpose on canvas |
|-----------|-------|:------:|-------------------|
| `ComplianceIngress` | ComplianceChain (§6) | ✅ | Mandatory first node |
| `ModelRouterLLM` | ModelRouter → vLLM/Ollama (§4.2) | — | Drop-in LLM component; designer picks a *profile* ("fast"/"reason"/"extract"), never a raw endpoint |
| `RAGRetriever` | RAGService (§4.3) | — | Tenant-scoped hybrid retrieve + rerank, outputs cited context |
| `GroundedResponder` | grounding verifier | ✅ | Blocks uncited claims before Chat Output |
| `MCPToolkit` | MCPClientPool + OPA (§4.4) | ✅ | Governed tools for Agent components |
| `HITLCheckpoint` | Approval queue (§5.4) | ✅ | Pause + human approval |
| `AuditClose` | AuditRecorder | ✅ | Terminal hash-chained audit span |
| `Translate` | IndicTrans2 (§8) | — | Locale pivot at flow edges |
| `LeadScoreExtractor`, `ROICalculator`, … | vertical helpers | — | Grammar-constrained structured extraction |

### 5.3 Flows-as-Code: Versioning, Linting, Promotion

A visual tool becomes production-grade through governance of its artifacts:

1. **Design** happens in a *dev* Langflow workspace against synthetic data.
2. **Export** — the flow JSON is committed to `flows/<vertical>/<name>/` and opens a PR like any code change.
3. **Flow Linter** (CI) parses the JSON and fails the build unless: `ComplianceIngress` is the unique entry node; every path from any Agent/LLM component to Chat Output passes `GroundedResponder`; every tool-bearing path terminates in `AuditClose`; no raw HTTP/Python REPL components appear in tenant-facing flows; all `sealed=True` components are the pinned library versions (checksum match). This is how the "sealed edges" guarantee survives the move from code-defined graphs to a freeform canvas.
4. **Eval gate** — golden transcripts (§15) replay against the candidate flow in a staging runtime.
5. **Promote** — `upsert_flow` deploys to prod; the resulting `FlowRef` (with checksum + lint report id) becomes bindable in tenant blueprints. Rollback = rebind the previous FlowRef.

### 5.4 Human-in-the-Loop and Long-Running Campaigns Without a Workflow Engine

Langflow executes request-scoped runs; it does not natively suspend a run for three days or six months. Rather than smuggling another engine back in, SAAP treats **Postgres as the durable state and Langflow as the only logic**, using two patterns:

**HITL pause/resume.** When `MCPToolkit` yields `require_human`, `HITLCheckpoint` (a) persists an `ApprovalRequest` row + the flow's `session_id`, (b) ends the run with a holding reply ("I've sent that for confirmation…"). The agency console approval fans a webhook that re-invokes the *same flow* with the approval token as input; Langflow's session-scoped memory restores conversational context, and the flow's approval branch executes the held ToolCall. Expiry auto-denies via the scheduler.

**Campaign state machines.** Multi-week sequences (patient recall, lease renewal, cart recovery) are modeled as a `campaign_enrollments` table — `(tenant, principal, campaign, state, next_action_at)` — plus **one Langflow flow per campaign** whose input is an enrollment record and whose terminal component writes the next `(state, next_action_at)`:

```python
# saap/scheduler/flow_scheduler.py
"""
The ONLY non-Langflow moving part in orchestration, kept deliberately
logic-free (≈100 lines): an APScheduler loop that

    SELECT * FROM campaign_enrollments WHERE next_action_at <= now()
      AND consent_valid(tenant, principal, campaign.purpose)   -- fail closed

and POSTs each row to its campaign FlowRef. All branching — "no answer
→ wait 3 days → SMS follow-up" — lives on the canvas as visible
components writing the next state. Crash-safe because state transitions
are transactional row updates; a redeploy loses nothing but an
in-flight turn, which retries idempotently (enrollment version key).
`consent.revoked` events (§12.3) delete enrollments in the same
transaction as the erasure enqueue.
"""
```

Example — the 6-month dental recall from the niche analysis becomes the flow `campaigns/dental_recall/1.x.json`: `[Enrollment Input] → ComplianceIngress → state Switch → (due: VoiceCallLauncher → outcome Switch → BookingWriter | ScheduleSMSFollowup) → CampaignStateWriter → AuditClose` — every step inspectable by the visual designer.

### 5.5 The AI Audit as a Multi-Agent Flow

The client-acquisition audit (§Acquisition analysis) is one Langflow flow chaining three Agent components — *Acquisition-Engine Analyst* (web-scrape + speed-to-lead probe MCP tools), *Automation Economist* (`ROICalculator`), *Report Writer* — passing structured state forward, ending in an `OpportunityMatrix` JSON + rendered PDF. Because it runs on the same governed components, even this internal sales tooling inherits audit trails and local-model routing; and because Langflow can expose a flow **as an MCP server**, the audit flow itself becomes a callable tool for the agency's internal assistant.

---
## 6. Compliance Interceptor Chain (L5) — DPDP/GDPR by Construction

### 6.1 Chain Contract

```python
# saap/compliance/chain.py
"""
Ordered, non-bypassable interceptor chain (P6). The channel adapters
receive an `InterceptedRuntime` — a wrapper around Orchestrator + 
MCPClientPool whose raw forms are not exported from the package
(`__all__` discipline + import-linter contract in CI).

Order matters:
  1. ConsentGate        — fail closed if purpose not in consent_scope
  2. PIIMasking         — Presidio detect → reversible tokenization
  3. PolicyGuard        — OPA/Rego per-tenant action policy
  4. RateLimiter        — per-tenant, per-tool budgets (Valkey)
  5. AuditRecorder      — append-only, hash-chained event log
"""
from typing import Protocol, Sequence
from saap.core.types import TenantContext


class Interceptor(Protocol):
    async def before(self, tenant: TenantContext, payload: "Envelope") -> "Envelope": ...
    async def after(self, tenant: TenantContext, payload: "Envelope") -> "Envelope": ...


class ComplianceChain:
    def __init__(self, interceptors: Sequence[Interceptor]) -> None: ...
    async def wrap(self, tenant, envelope, inner) -> "Envelope":
        """before* → inner() → after* (reverse order). Any interceptor
        may raise ComplianceViolation, which short-circuits to a safe,
        audited refusal — never a stack trace to the caller."""
```

### 6.2 PII Masking (Presidio, MIT) — the "Protecto pattern", self-hosted

```python
# saap/compliance/pii.py
"""
Reversible PII vault. The LLM only ever sees placeholders; the real
values are re-injected AFTER PolicyGuard approves the outbound action.

  inbound : "Book Ramesh, Aadhaar 1234-5678-9012, phone +91-98..."
  to LLM  : "Book <PERSON_a1>, Aadhaar <IN_AADHAAR_b7>, phone <PHONE_c2>"
  to MCP  : placeholders resolved from the tenant-keyed vault (AES-GCM,
            key from OpenBao) only for tools whose schema declares the
            field as required-PII AND consent covers the purpose.

Custom recognizers registered for the Indian market: Aadhaar, PAN,
UPI VPA, IFSC, Indian phone formats — plus vertical packs (ICD codes
for healthcare tenants). This is the DPDP cross-border firewall: even
if a future misconfiguration pointed at a remote model, raw SPII could
not leave the boundary because masking sits *below* the model client.
"""
class PIIMaskingInterceptor(Interceptor):
    def __init__(self, analyzer: "PresidioAnalyzer",
                 vault: "TokenVault", policy: "MaskingPolicyStore") -> None: ...
```

### 6.3 PolicyGuard (OPA) and Risk Tiers

```rego
# policies/tenant/dental_clinic.rego  — example per-tenant Rego
package saap.actions

default allow := false

allow { input.tool.risk_tier == "read" }

allow {                                # writes: business hours + scope
  input.tool.risk_tier == "write"
  input.tool.name in data.tenant.allowed_write_tools
  time.clock(input.now)[0] >= 8; time.clock(input.now)[0] < 20
}

require_human {                        # refunds, record deletion, >₹ limits
  input.tool.risk_tier == "high_risk"
}
```

`require_human` outcomes are surfaced by the `MCPToolkit` component into `HITLCheckpoint` (§5.4) → agency console approval queue → webhook re-invocation of the flow. Approvals themselves are audit events.

### 6.4 Audit Trail and Erasure

```python
# saap/compliance/audit.py
class AuditRecorder(Interceptor):
    """
    Append-only Postgres table; each row carries
    sha256(prev_row_hash || row_payload) — a hash chain making silent
    tampering detectable (the "immutable audit trail" the analysis says
    boards demand). Nightly anchor hash exported to MinIO WORM bucket.
    """

# saap/compliance/erasure.py
class ErasureService:
    """
    DPDP 'deletion on purpose fulfillment' (Phase-3 hard deadline in the
    analysis). Dagster job walks: consent registry → expired purposes →
    VectorStore.delete_by_source + Postgres row purge + MinIO object
    delete + TokenVault key destruction (crypto-shredding). Emits a
    signed erasure certificate per tenant per run.
    """
```

**72-hour breach protocol** is likewise code: a Grafana/Prometheus alert rule on anomalous vault access triggers (via FlowScheduler's event webhook) an incident-response Langflow flow that assembles the notification dossier template automatically — the 72-hour clock starts with the alert row.

---

## 7. Voice Pipeline (L3/L6) — Open-Source Full-Duplex Telephony

Replaces Vapi/Retell/Bland with **FreeSWITCH → LiveKit SIP → LiveKit Agents** running local models. Target: the same ~400–500 ms median voice-to-voice latency the analysis cites as the adoption threshold.

### 7.1 Component Interfaces

```python
# saap/voice/contracts.py
from typing import AsyncIterator, Protocol
from saap.core.types import TenantContext, Locale


class VAD(Protocol):
    """Silero VAD (MIT). Emits speech-start/-end; speech-start during
    agent playback == barge-in → pipeline cancels TTS + LLM stream."""
    def process(self, pcm_frames: AsyncIterator[bytes]) -> AsyncIterator["VADEvent"]: ...


class StreamingSTT(Protocol):
    """faster-whisper (MIT, CTranslate2 int8) with partial hypotheses.
    Locale-routed: ta-IN → IndicConformer/IndicWhisper checkpoint."""
    def transcribe(self, pcm: AsyncIterator[bytes], *, locale: Locale
                   ) -> AsyncIterator["TranscriptSegment"]: ...


class StreamingTTS(Protocol):
    """Piper (MIT) default — first-audio-chunk target < 100 ms.
    Sentence-level chunking: synthesis of sentence N overlaps LLM
    generation of sentence N+1."""
    def synthesize(self, text: AsyncIterator[str], *, locale: Locale,
                   voice: str) -> AsyncIterator[bytes]: ...


class VoiceSession(Protocol):
    """One live call. Owns the latency budget ledger:
       VAD endpoint 60ms + STT partial 120ms + fast-LLM first-token
       150ms + TTS first-chunk 90ms ≈ 420ms voice-to-voice."""
    async def run(self) -> "CallOutcome": ...
    async def barge_in(self) -> None: ...
    async def transfer_to_human(self, reason: str) -> None: ...
```

### 7.2 Pipeline Assembly

```python
# saap/voice/pipeline.py
"""
LiveKit Agents worker. Media path:

 PSTN/carrier ──SIP──▶ FreeSWITCH ──SIP──▶ LiveKit SIP bridge
     ──WebRTC──▶ VoicePipelineAgent(VAD→STT→DialogEngine→TTS) ──▶ caller

DialogEngine = the SAME Langflow flow as chat (§5.1), executed via
LangflowEmbeddedRuntime (`lfx`, in-process) so no HTTP hop is added to
the latency budget; the flow's ModelRouterLLM profile is "fast" for
turn latency. Tool calls that exceed ~700 ms
trigger a natural filler utterance ("one moment, checking that for
you…") generated locally, and long tools run as background tasks whose
results are woven into the next turn — the "executes background tasks
simultaneously" behavior the analysis describes.
Recordings → MinIO with tenant retention policy; transcripts pass the
same PII interceptor before storage.
"""
class VoicePipelineFactory:
    def create(self, tenant: TenantContext, agent_name: str,
               call_meta: "SIPCallMeta") -> VoiceSession: ...
```

### 7.3 Cost Model (why open source wins economically)

Self-hosted per-minute cost ≈ amortized GPU + telephony trunk only. A single RTX 4090-class card running Whisper-small int8 + Piper + a 7B Q4 model sustains multiple concurrent calls; with SIP trunk termination at fractions of a cent per minute, all-in marginal cost lands at roughly **$0.01–0.03/min** versus the $0.10–0.30/min all-in stack costs tabulated in the analysis — a 5–10× gross-margin advantage that also eliminates per-task middleware fees entirely (the same logic the analysis applies to self-hosted n8n, extended to the whole stack).

---

## 8. Multilingual Layer — Open Indic Pipeline

```python
# saap/i18n/translate.py
"""
Self-hosted replacement for hosted multilingual APIs, using the open
AI4Bharat lineage (IndicTrans2, MIT code + open weights; IndicXlit).

Pattern: "pivot at the edges" — the reasoning model converses in its
strongest language internally; TranslationService translates at the
channel boundary, preserving named-entity placeholders from the PII
masker so entities are never mangled or exposed in transit.

  caller (Tamil speech) → Indic STT → [ta text]
      → IndicTrans2 ta→en → DialogEngine (en)
      → IndicTrans2 en→ta → Piper ta-IN voice → caller
End-to-end budget stays under the 2 s bar cited for multilingual
pipelines because both NMT directions run as small local seq2seq
models (<50 ms each on GPU).
"""
class TranslationProvider(Protocol):
    async def translate(self, text: str, *, src: Locale, tgt: Locale,
                        protected_spans: list[tuple[int, int]] = []) -> str: ...


class LocaleRouter:
    """Detects locale (fast model / fasttext-lid), binds the correct
    STT checkpoint, NMT pair, and TTS voice per session; falls back to
    human transfer for unsupported locales rather than degrading."""
```

---

## 9. Multi-Tenancy, Snapshots, and the Open-Source CRM Layer

### 9.1 Tenant Model

```python
# saap/tenancy/models.py
class Tenant(BaseModel):
    """One client business. Maps 1:1 to: a Keycloak realm client, a
    Qdrant isolation unit, a Postgres schema, an OPA data document,
    a set of MCP server configs, and a CRM (Twenty/EspoCRM) workspace."""
    tenant_id: UUID
    vertical: str
    plan: str                       # agency's own pricing tiers
    residency: str
    branding: "WhiteLabelTheme"     # replaces GHL white-labeling
```

### 9.2 Snapshots as Code

GoHighLevel's "Snapshots" become **declarative tenant blueprints** — a Git-versioned YAML bundle that the provisioner applies idempotently. Deploying a new dental clinic = `saap tenant create --blueprint verticals/dental/v4`:

```yaml
# blueprints/verticals/dental/v4/blueprint.yaml
vertical: dental
flows:         [dental.intake@2.3.0, dental.patient_education_rag@1.9.0,
                campaigns/dental_recall@1.4.0,
                dental.clinical_governance@1.1.0]   # the 4-bot lifecycle, as FlowRefs
mcp_servers:
  crm:       {template: twenty-crm,      allowed_tools: [create_contact, book_slot]}
  pms:       {template: openemr-bridge,  allowed_tools: [read_schedule]}
rag_sources: [handbook.pdf, procedures/, faq.csv]
campaigns:   [dental_recall: {cadence_days: 180, purpose: recall_outreach}]
policies:    [dental_clinic.rego]
locales:     [en-IN, ta-IN]
consent_purposes: [appointment_mgmt, recall_outreach]
```

### 9.3 CRM Strategy

**Twenty** (modern, GraphQL) or **EspoCRM/SuiteCRM** replaces the GHL sub-account CRM. Each is wrapped by a thin **CRM MCP server** the agency maintains once (`mcp-server-twenty`), so agents are CRM-agnostic — swapping CRMs for a client is a blueprint edit, not an agent rewrite. Agency billing/entitlements (the SaaS-Pro-style rebilling) is handled by **Lago** or **Kill Bill** (both AGPL/Apache open-source billing engines) metering per-tenant usage events emitted by Langfuse/Prometheus exporters.

---

## 10. Deployment Topology

```yaml
# deploy/docker-compose.profile-agency.yaml (excerpt; K8s Helm chart mirrors it)
services:
  vllm-reason:      {image: vllm/vllm-openai, gpus: all,
                     command: --model Qwen/Qwen2.5-72B-Instruct-AWQ --tensor-parallel-size 2}
  ollama-fast:      {image: ollama/ollama}           # 7B fast path
  qdrant:           {image: qdrant/qdrant}
  postgres:         {image: postgres:16}
  valkey:           {image: valkey/valkey}
  minio:            {image: minio/minio}
  keycloak:         {image: keycloak/keycloak}
  openbao:          {image: openbao/openbao}
  langflow:         {image: langflowai/langflow, env: [LANGFLOW_DATABASE_URL=postgres://…,
                     LANGFLOW_AUTO_LOGIN=false]}   # designer UI + runtime
  saap-scheduler:   {build: ./scheduler}           # FlowScheduler (logic-free triggers)
  livekit:          {image: livekit/livekit-server}
  livekit-sip:      {image: livekit/sip}
  freeswitch:       {image: safarov/freeswitch}
  langfuse:         {image: langfuse/langfuse}
  prometheus/grafana/loki: {...}
  saap-gateway:     {build: ./gateway}       # channel adapters + compliance chain
  saap-orchestrator:{build: ./orchestrator}  # LangflowOrchestrator façade + approval queue
  saap-voice:       {build: ./voice}         # LiveKit workers embedding lfx flows
  saap-mcp-*:       {build: ./mcp-servers/*} # per-integration MCP servers
```

**Sizing profiles:** `edge` (one CPU/consumer-GPU box per client site: Ollama 7B + Whisper-small + Piper — data never leaves premises, the strongest DPDP posture), `agency` (single GPU server, all tenants), `scale` (K8s, vLLM pool with tensor parallelism, LiveKit distributed).

---

## 11. Repository Layout and Extension Recipes

```
saap/
├── core/            # interfaces only — types, llm, memory, mcp, agent, registry
├── plugins/
│   ├── llm/         # vllm/, ollama/, llamacpp/
│   ├── memory/      # qdrant/, chroma/, pgvector/
│   ├── voice/       # faster_whisper/, piper/, silero/, livekit/
│   └── i18n/        # indictrans2/, indicxlit/
├── compliance/      # chain, pii, policy(OPA), audit, erasure
├── langflow_components/  # SAAP component library (sealed + open components)
├── flows/           # exported flow JSON, Git-versioned:
│   └── verticals/{dental,realestate,legal,ecom,finserv}/ · campaigns/ · internal/ai_audit/
├── scheduler/       # FlowScheduler (logic-free triggers)
├── mcp-servers/     # twenty-crm/, calendar/, openemr-bridge/, sql-readonly/
├── gateway/         # channel adapters, FastAPI, WebSocket chat
├── tenancy/         # blueprints engine, provisioner, billing exporters
├── deploy/          # compose profiles, helm/, terraform/
└── tools/           # license_gate/, flow_linter/, eval_harness/
```

**Recipe — add a new vertical (e.g., logistics):** clone the canonical canvas in the dev Langflow workspace, edit prompts/intents/enrichment components visually, write the Rego policy, author/reuse MCP servers for the client's TMS, export the flow JSON, pass linter + evals, define a blueprint YAML. No core file changes — and no code at all beyond policy, if existing components suffice.

**Recipe — swap a model engine:** implement `LLMProvider` in a new plugin package, declare its license, register the entry point, change one line in `deployment.yaml`.

**Recipe — new channel (WhatsApp via open-source bridge):** implement `ChannelAdapter` producing `InboundEvent`s; the compliance chain and flows are untouched.

**Recipe — new canvas capability:** implement a Langflow custom component wrapping a §4 interface, declare its license and `sealed` status, ship it in the component package; it appears in every designer's sidebar on the next runtime deploy.

---

## 12. Channel Adapters and the Ingestion Pipeline (Expanded Blueprints)

### 12.1 Channel Adapter Contract (L6)

```python
# saap/gateway/channels.py
"""
Channel adapters normalize every entry point (web chat, SIP call,
webhook, email, WhatsApp bridge) into a single `InboundEvent` and
render `FlowRunEvent` streams back out. Adding a channel never touches
agents or compliance code (P3).
"""
from typing import AsyncIterator, Protocol
from pydantic import BaseModel
from saap.core.types import TenantContext, Message


class InboundEvent(BaseModel, frozen=True):
    """Channel-agnostic envelope entering the compliance chain (L5)."""
    tenant: TenantContext
    channel: str                        # "webchat" | "sip" | "webhook" | ...
    session_id: str                     # channel-scoped conversation key
    message: Message
    raw_ref: str | None = None          # minio:// pointer to original payload


class ChannelAdapter(Protocol):
    """
    Implementations: ``WebChatAdapter`` (FastAPI WebSocket),
    ``VoiceSessionAdapter`` (LiveKit, §7), ``WebhookAdapter`` (signed
    HMAC ingress for client systems), ``EmailAdapter`` (IMAP/JMAP poll),
    ``MatrixWhatsAppAdapter`` (open-source mautrix bridge).

    Contract:
      * `listen` yields InboundEvents; the adapter is responsible for
        channel auth (widget JWT, SIP trunk ACL, HMAC verification)
        BEFORE constructing a TenantContext — an unauthenticated payload
        must never obtain one.
      * `render` maps FlowRunEvents to channel semantics: tokens → SSE
        deltas for web, sentences → TTS for voice, final → templated
        reply for email.
    """
    channel: str
    def listen(self) -> AsyncIterator[InboundEvent]: ...
    async def render(self, session_id: str,
                     events: AsyncIterator["FlowRunEvent"]) -> None: ...


class Gateway:
    """
    Binds adapters to the InterceptedRuntime (§6.1):

        for event in adapter.listen():
            envelope = await compliance.wrap(event.tenant, event, run_agent)
            await adapter.render(event.session_id, envelope.events)

    Also owns session affinity (Valkey), backpressure, and per-channel
    rate limits so a flooding webhook cannot starve voice sessions.
    """
```

### 12.2 Document Ingestion Pipeline (feeds §4.3 RAG)

```python
# saap/ingest/pipeline.py
"""
Blueprint-driven ingestion for `rag_sources` (§9.2), run as Dagster
assets so re-indexing is incremental and observable.

Stages (each an interface, each swappable):

  Loader (MinIO/local/URL) → Parser (Docling: PDF/DOCX/PPTX → structured
  blocks) → PIIClassifier (Presidio pass tags each block's DataClass —
  SPII blocks can be excluded per tenant policy BEFORE they ever reach
  the vector store) → Chunker (structure-aware: headings/tables kept
  intact, 512-token target, 15% overlap) → Embedder (BGE-M3 dense +
  sparse) → VectorStore.upsert + lineage row in Postgres.

Lineage is what makes DPDP erasure (§6.4) exact: every chunk row keys
back to (tenant, source_uri, content_hash), so `delete_by_source`
is a lookup, not a scan.
"""
from typing import Protocol, Sequence
from saap.core.memory import DocumentChunk


class DocumentParser(Protocol):
    """Docling (MIT) default; `unstructured` adapter available."""
    async def parse(self, blob_uri: str) -> "ParsedDocument": ...


class Chunker(Protocol):
    def chunk(self, doc: "ParsedDocument") -> Sequence[DocumentChunk]: ...


class IngestionPipeline:
    async def sync_source(self, tenant, source_uri: str) -> "IngestReport":
        """Idempotent: unchanged content hashes are skipped; removed
        pages trigger targeted deletes. Emits Langfuse spans + a
        per-source freshness metric Grafana alerts on."""
```

### 12.3 Event Bus and Domain Events

```python
# saap/core/events.py
"""
Lightweight internal event bus (Valkey streams; NATS adapter optional)
decoupling side-concerns from the hot path: audit fan-out, usage
metering for billing (§9.3), CRM activity logging, and analytics all
subscribe — the agent loop never blocks on them.
"""
class DomainEvent(BaseModel, frozen=True):
    kind: str            # "call.completed" | "tool.executed" | "consent.revoked" ...
    tenant_id: str
    payload: dict
    occurred_at: datetime


class EventBus(Protocol):
    async def publish(self, event: DomainEvent) -> None: ...
    def subscribe(self, kinds: Sequence[str]) -> AsyncIterator[DomainEvent]: ...
```

`consent.revoked` deserves note: its subscriber deletes the principal's `campaign_enrollments` rows (halting all future scheduled flow runs), cancels any pending ApprovalRequests, and enqueues an erasure job — revocation propagates through the whole system from one event.

---

## 13. Worked Example: A Complete Vertical Agent (Canvas + Code)

The real-estate lead qualifier — attacking the speed-to-lead failure mode (48% of agents never respond) — now splits cleanly between what a **visual designer** does and what (little) an **engineer** does.

**On the canvas** (`flows/verticals/realestate/lead_qualifier/2.1.0.json`), cloned from the canonical template of §5.1, the designer edits:

```
 ComplianceIngress ▶ IntentRouter(fast)
    ├─ "viewing"/"new_inquiry" ▶ RAGRetriever(listings kb)
    │        ▶ ListingsMatcher ▶ LeadScoreExtractor
    │        ▶ AgentCore(reason) ⇄ MCPToolkit[crm, calendar, listings-sql]
    │        ▶ GroundedResponder ▶ AuditClose
    ├─ "maintenance" ▶ Handoff(flow: realestate.maintenance_triage@1.x)
    └─ "other"       ▶ HumanTransfer
```

Prompts, intent labels, the listings knowledge-base binding, and tool selection are all canvas edits. Booking a viewing is `risk_tier="write"` (auto-allowed in business hours by the tenant Rego); offering rent discounts is `"high_risk"` → `HITLCheckpoint` by policy, not by prompt.

**In code**, only one vertical-specific component was new:

```python
# saap/langflow_components/verticals/realestate/lead_score.py
"""
LeadScoreExtractor — grammar-constrained structured extraction.

Uses the "extract" model route (small local model + JSON schema
decoding, §4.2) to pull {budget, timeline, preapproved, bedrooms}
from the conversation into a typed LeadScore the downstream CRM
write persists. Deterministic output shape means the CRM MCP tool's
schema validation can never fail on model creativity (P5).
"""
class LeadScoreExtractor(Component):
    display_name = "RE · Lead Score Extractor"
    inputs = [MessageInput(name="conversation")]
    outputs = [Output(name="lead_score", method="extract")]

    async def extract(self) -> Data:
        provider, cfg = await self.router.route(self.tenant, task="extract")
        cfg = cfg.model_copy(update={"json_schema": LeadScore.model_json_schema()})
        completion = await provider.generate(self._messages(), config=cfg)
        return Data(data=LeadScore.model_validate_json(completion.text).model_dump())
```

Total cost of the vertical: one ~60-line component, a Rego file, a blueprint YAML, five golden-transcript evals — everything else was drawn, not written.

---
## 14. End-to-End Sequence: One Voice Call

```
Caller(PSTN) FreeSWITCH LiveKit  VoiceSession  Compliance  LangflowFlow MCPPool  CRM-MCP
    │ dial      │          │          │             │           │          │        │
    ├──────────▶│──SIP────▶│──WebRTC─▶│ VAD+STT     │           │          │        │
    │           │          │          ├─InboundEvt─▶│ consent✓  │          │        │
    │           │          │          │             ├─masked───▶│ route    │        │
    │           │          │          │             │           ├─ RAG ────┤        │
    │           │          │          │             │           ├─ToolCall▶│ OPA✓   │
    │           │          │          │             │           │          ├──call─▶│
    │           │          │          │             │           │          │◀─slot──┤
    │           │          │          │◀── token stream (sentence chunks) ─┤        │
    │◀── Piper audio ◀─────┤◀─────────┤ (barge-in cancels here)  │          │        │
    │           │          │          │             │  audit row per hop   │        │
```

Latency ledger per turn (targets, Grafana SLOs): VAD endpoint ≤60 ms · STT partial ≤120 ms · fast-LLM first token ≤150 ms · TTS first chunk ≤90 ms → **≈420 ms voice-to-voice**, inside the 395–470 ms benchmark band the strategic analysis cites.

---

## 15. Quality Engineering: Eval Harness and Testing Strategy

```python
# saap/tools/eval_harness/harness.py
"""
Nothing about a probabilistic system ships on vibes (P5). Three gates:

1. Golden transcripts — per vertical, YAML conversations with expected
   tool calls and forbidden behaviors; replayed against the real
   exported flow (staging Langflow runtime) with recorded MCP responses
   (VCR-style cassettes). A judge model
   (local Qwen 72B) scores semantic match; hard assertions check tool
   names/args exactly.
2. Grounding evals — RAGService answers scored for citation coverage
   and faithfulness (open RAGAS-style metrics run locally).
3. Safety probes — jailbreak/injection corpus (incl. MCP tool-poisoning
   payloads embedded in retrieved documents) must yield refusal or
   quarantine, never execution.

CI wiring: any change to a flow JSON, component version, model tag, or
adapter weight re-runs the affected suites; Langfuse stores baselines so
regressions are diffs, not surprises. The Flow Linter (§5.3) and
LicenseGate (§4.6) run in the same pipeline — a flow that skips a sealed
component cannot merge, let alone deploy.
"""
class EvalSuite(Protocol):
    async def run(self, target: "Agent", dataset: "GoldenSet") -> "EvalReport": ...
```

Unit tests mock at the Protocol seams (a `FakeLLMProvider` returning scripted completions, a `FakeLangflowRuntime` yielding scripted FlowRunEvents), which the interface-first design makes trivial; custom components get direct unit tests since they are ordinary Python classes; integration tests run docker-compose profile `test` with a 3B model so the full path — gateway → compliance → Langflow flow → MCP → Postgres — executes in CI on CPU.

---

## 16. Risks and Mitigations

| Risk | Mitigation in this architecture |
|------|--------------------------------|
| Local models trail frontier quality | Vertical LoRA adapters + tight RAG grounding + constrained decoding close most of the gap for narrow workflows; eval harness gates every model/prompt change against golden transcripts |
| MCP dynamic-tool attacks | Static allow-lists, quarantine of runtime catalog changes, client-side schema re-validation, OPA gating, namespaced tool IDs |
| GPU capacity spikes (voice) | Fast-path 7B models, per-tenant concurrency budgets, FreeSWITCH IVR + human-transfer graceful degradation |
| License drift in dependencies (Redis→RSAL pattern) | CI LicenseGate with allow/review/deny lists; pinned OSI forks (Valkey, OpenBao) |
| DPDP Phase-2/3 deadlines | Consent Manager API is an MCP server behind `ConsentGate`; erasure + breach workflows are code with tests, not runbooks |
| Hallucinated actions | P5 everywhere: models propose, OPA/HITL dispose; grounding verifier before responses ship |
| Canvas sprawl / "shadow flows" | Flows-as-code: only Git-committed, linter-passed FlowRefs are bindable to tenants; dev workspace has no tenant data or prod MCP credentials |
| No native durable/suspended runs in Langflow | Postgres-backed campaign state machines + logic-free FlowScheduler (§5.4); HITL via pause/resume with session memory — durability lives in the database, logic stays on the canvas |
| Langflow runtime as single point of failure | Stateless runtime replicas behind the gateway (flows + sessions persist in Postgres); voice path bypasses HTTP entirely via embedded lfx |

---

## 17. Summary

This architecture takes every commercial pillar of the AI Automation Agency model — MCP-driven "AI Operating Systems," sub-second voice agents, vertical RAG, multilingual reach, DPDP-grade compliance, and multi-tenant snapshot economics — and rebuilds it on an exclusively open-source, locally-hosted foundation: **vLLM/Ollama + open-weight models** for reasoning, **Langflow** — and only Langflow — for orchestration, giving non-engineers a true visual design surface governed by sealed components, a flow linter, and flows-as-code promotion, **MCP** as the sole tool bus, **Qdrant/Postgres/MinIO** for state, **LiveKit/FreeSWITCH + faster-whisper/Piper/Silero** for voice, **IndicTrans2** for languages, and **Presidio/OPA/Keycloak/Langfuse** for trust. The interface-first plugin design means every one of those choices is a binding, not a dependency — which is precisely what makes the platform durable as the open-source ecosystem it stands on continues to move.
