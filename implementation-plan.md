# SAAP Implementation Plan
## Sovereign AI Automation Platform — Detailed, Phased Implementation Roadmap

**Version:** 1.0 · **Date:** July 2026 · **Status:** Approved-for-planning draft

**Source documents:**
1. *Strategic Analysis of High-Yield AI Business Models: The AI Automation Agency Paradigm* (`AI Business Idea Analysis.pdf`) — the business case: what we sell, to whom, at what price, under which regulatory deadlines.
2. *Sovereign AI Automation Platform (SAAP) v2.0* (`open-source-aaa-architecture.md`) — the reference architecture: a fully open-source, local-first, Langflow-orchestrated platform. Section references below (e.g., §5.3) point into that document.

---

## 1. Executive Summary

The business analysis identifies the **Specialized AI Automation Agency (AAA)** as the highest-yield AI business model for 2026: low startup cost ($1k–3k), fast path to $10k–50k/month via vertical retainers (healthcare/dental $2k–5k, financial services $3k–7k, legal $2.5k–6k, real estate $1k–3.5k, e-commerce $1.5k–4k), with **Autonomous Voice AI** as the primary ROI driver and **MCP** as the integration backbone.

The architecture document rebuilds every commercial pillar of that model on an exclusively open-source, self-hosted foundation (SAAP), eliminating per-minute SaaS fees (target **$0.01–0.03/min** voice cost vs. $0.10–0.30/min for Vapi/Retell-class stacks — a 5–10× gross-margin advantage) and making DPDP/GDPR compliance a structural property rather than a policy document.

This plan turns that architecture into a delivery schedule: **six phases over ~9 months**, sequenced so that:

- A revenue-capable **chat agent MVP for one design-partner client exists by end of Phase 1 (~Week 12)**.
- **Voice AI** — the flagship offer — ships in Phase 2 (~Week 20) at the ≤500 ms latency bar.
- **DPDP Phase 2 (Consent Manager API integration) is met before its statutory deadline of 13 November 2026** (~Week 19 of this plan).
- Full **multi-tenant "snapshot" economics** (the open-source GoHighLevel replacement) is operational by Phase 4 (~Week 30), enabling the agency to onboard clients in minutes, not weeks.
- **DPDP Phase 3 (automated erasure, encryption, 72-hour breach protocol — hard deadline 13 May 2027)** is fully engineered with margin to spare (Phase 3 of this plan, ~Week 26).

---

## 2. What We Are Building (Product Pillars → Architecture → Plan Phase)

Traceability matrix from commercial capability (business analysis) to architectural mechanism to delivery phase:

| # | Commercial pillar (business analysis) | Architectural mechanism (SAAP doc) | Plan phase |
|---|--------------------------------------|-----------------------------------|-----------|
| 1 | "AI Operating Systems" — agents acting on client's real data | MCP tool bus (§2.2, §4.4), MCPClientPool + per-tenant allow-lists | Phase 1 |
| 2 | Autonomous Voice AI, sub-second latency, 24/7 | LiveKit + FreeSWITCH + faster-whisper + Piper + Silero VAD (§2.4, §7, §14) | Phase 2 |
| 3 | Vertical RAG knowledge systems (hallucination-grounded) | RAGService: hybrid retrieve → rerank → grounding verifier (§4.3, §12.2) | Phase 1 |
| 4 | Multilingual/Indic reach (Bhashini-class, self-hosted) | IndicTrans2 + IndicConformer/IndicWhisper + Piper Indic voices (§2.5, §8) | Phase 3 |
| 5 | DPDP/GDPR compliance as differentiator (Consent Managers, erasure, 72-hr breach, immutable audit) | L5 Compliance Interceptor Chain: ConsentGate → Presidio PII masking → OPA → hash-chained audit (§6) | Phases 1 (skeleton) & 3 (full) |
| 6 | Snapshot economics / white-labeled sub-accounts (GHL replacement) | Tenant blueprints-as-code, Twenty/EspoCRM MCP wrappers, Lago/Kill Bill billing (§9) | Phase 4 |
| 7 | Non-engineer operability ("no-code" stack) | Langflow sole orchestration engine + sealed SAAP component library + Flow Linter (§2.2, §5) | Phases 1–2 |
| 8 | AI Audit client-acquisition methodology (Opportunity Matrix, ROI summary) | Multi-agent audit flow, self-consumed via MCP (§5.5) | Phase 5 |
| 9 | Vertical niches (dental 4-bot lifecycle, RE lead qualifier, etc.) | Canonical flow template cloning + vertical blueprints (§5.1, §9.2, §13) | Phase 5 |
| 10 | HITL guardrails for high-risk actions (NSA MCP guidance) | PolicyGuard risk tiers + HITLCheckpoint pause/resume (§4.4, §5.4, §6.3) | Phase 1 |

---

## 3. Hard Constraints and Non-Negotiables

These come directly from the two documents and gate every phase:

1. **Open source only (P1).** Every runtime dependency carries an OSI-approved license. Enforced by the CI **LicenseGate** from Phase 0 onward — allow: MIT, Apache-2.0, BSD, MPL-2.0, PostgreSQL, AGPL-3.0; deny: BUSL, RSALv2, proprietary. Pinned forks where upstream drifted: **Valkey** (not Redis ≥7.4), **OpenBao** (not Vault). Coqui XTTS-v2 is flagged "restricted" (non-commercial weights); Piper is the commercial default.
2. **Local-first inference (P2).** No `OpenAIProvider`, no hosted LLM/STT/TTS anywhere in the runtime path. vLLM (datacenter), Ollama (edge/dev), llama.cpp (embedded).
3. **Langflow is the sole orchestration engine.** No LangGraph, CrewAI, AutoGen, Temporal, or n8n. Anything that looks like workflow logic must be expressible on the canvas; durability lives in Postgres (§5.4).
4. **Compliance chain is non-bypassable (P6).** Nothing crosses L6→L4 without traversing L5; no agent touches an external system except through L2 (MCP). Enforced by import-linter contracts and the Flow Linter, not convention.
5. **Voice latency ≤ ~500 ms median voice-to-voice** (adoption threshold cited: 395–470 ms band). Budget ledger: VAD ≤60 ms, STT partial ≤120 ms, fast-LLM first token ≤150 ms, TTS first chunk ≤90 ms ≈ 420 ms.
6. **Statutory deadlines:** DPDP Phase 2 — Consent Manager API integration by **13 Nov 2026**; DPDP Phase 3 — automated deletion on purpose fulfillment, encryption at rest/in transit, 72-hour breach notification by **13 May 2027**. Penalties up to INR 250 crore.
7. **Tenant ID on everything (P7).** Every message, memory record, tool call, and audit event carries `TenantContext`; it must be impossible to construct a pipeline call without one.
8. **Models propose, policy disposes (P5).** No high-risk action executes on model output alone: OPA gating, JSON-schema-constrained decoding, HITL checkpoints.

---

## 4. Delivery Approach and Phase Overview

Two-week sprints. Each phase ends with a demoable **milestone gate** with explicit acceptance criteria. Compliance and quality workstreams run continuously — the eval harness, Flow Linter, and LicenseGate are built early and gate every merge thereafter (§15).

| Phase | Weeks (approx. dates) | Theme | Milestone gate |
|-------|----------------------|-------|----------------|
| **0** | W1–W4 (Jul 2026) | Foundations: repo, CI, interfaces, infra skeleton | `docker compose up` brings up full dev stack; LicenseGate + CI green; core interfaces merged |
| **1** | W5–W12 (Aug–Sep 2026) | Core platform MVP: chat agent end-to-end (RAG + MCP + compliance skeleton + Langflow) | Design-partner demo: grounded, tool-using web-chat agent for 1 pilot tenant |
| **2** | W13–W20 (Oct–Nov 2026) | Voice pipeline: full-duplex telephony at ≤500 ms | Live PSTN call books a real appointment via MCP; latency SLO met on Grafana |
| **3** | W17–W26 (Oct–Dec 2026) | Compliance completion + multilingual (overlaps Phase 2) | **DPDP Phase-2 Consent Manager live before 13 Nov 2026**; Tamil/Hindi voice call demo; erasure + breach workflows tested |
| **4** | W21–W30 (Nov 2026–Jan 2027) | Multi-tenancy at scale: blueprints, CRM, billing, campaigns | New dental tenant provisioned from blueprint in <30 min incl. white-label CRM + recall campaign |
| **5** | W27–W36 (Jan–Mar 2027) | Verticals + AI Audit + go-to-market tooling | 3 vertical packs shipped; AI Audit flow produces Opportunity Matrix PDF; first 3 paying tenants onboarded |
| **6** | W33+ (Feb 2027 →) | Scale, hardening, edge profile, DPDP Phase-3 sign-off | K8s `scale` profile; chaos/pen tests passed; DPDP Phase-3 audit evidence pack complete (well before 13 May 2027) |

Phases 2/3 and 4/5 deliberately overlap: compliance and multilingual work does not block the voice-latency team, and vertical-pack authoring (mostly canvas + YAML work, §11) starts as soon as the blueprint engine exists.

---

## 5. Phase 0 — Foundations (Weeks 1–4)

**Objective:** an empty-but-correct skeleton where every architectural rule is already enforced by CI, so nothing built later has to be retrofitted.

### 5.1 Epic 0.1 — Repository and CI scaffolding
- Create the monorepo per §11 layout: `saap/core`, `saap/plugins/*`, `saap/compliance`, `saap/langflow_components`, `flows/`, `scheduler/`, `mcp-servers/`, `gateway/`, `tenancy/`, `deploy/`, `tools/`.
- Python 3.11+, `uv`/`hatch` workspace; Pydantic v2; ruff + mypy (strict on `saap.core`).
- CI pipeline (self-hosted runners): lint → typecheck → unit tests → **LicenseGate** → **import-linter contracts** (compliance chain non-bypassability: `Orchestrator`/`MCPClientPool` raw forms not importable outside the compliance package).
- **Deliverable:** `tools/license_gate/` — scans dependency tree + plugin registrations against allow/review/deny lists (§4.6); fails the build on violations. This lands *first* because P1 is an architectural property.

### 5.2 Epic 0.2 — Core contracts (`saap.core`)
Implement the §4 interfaces exactly as specified — these are the plugin contract layer and change-control on them is strict from day one:
- `types.py`: `TenantContext` (frozen, mandatory), `Message`, `ToolCall`, `ToolResult`, `DataClass`, `Locale`.
- `llm.py`: `LLMProvider` protocol, `GenerationConfig` (incl. `json_schema` constrained decoding), `Completion`, `ModelRouter` skeleton.
- `memory.py`: `EmbeddingProvider`, `VectorStore`, `Reranker`, `RAGService` façade signatures.
- `mcp.py`: `MCPServerConfig`, `MCPConnection`, `MCPClientPool` signatures.
- `flow.py`: `FlowRef`, `FlowRunEvent`, `LangflowRuntime`, `ApprovalRequest`, `Orchestrator`.
- `registry.py`: `PluginRegistry` with entry-point loading (`saap.plugins` group) and mandatory license declaration.
- `events.py`: `DomainEvent`, `EventBus` (Valkey streams).
- **Acceptance:** 100% typed, unit-tested with fakes (`FakeLLMProvider`, `FakeLangflowRuntime`); mutation of any frozen model raises.

### 5.3 Epic 0.3 — Dev infrastructure profile
- `deploy/docker-compose.profile-dev.yaml`: Postgres 16, Qdrant, Valkey, MinIO, Keycloak, OpenBao, Langflow (auth on), Langfuse, Prometheus/Grafana/Loki, Ollama (3B model for CPU CI).
- Database migrations (Alembic): tenants, consent registry, audit log (hash-chain columns), `campaign_enrollments`, approval requests, flow registry, chunk lineage.
- Secrets bootstrap: OpenBao dev mode, Keycloak realm-per-deployment with agency SSO realm.
- **Acceptance:** one-command bring-up on a laptop and on the shared GPU dev server; integration-test job runs the full compose profile in CI with the 3B model (per §15).

### 5.4 Epic 0.4 — Observability baseline
- Langfuse tracing SDK wired into core (every `LLMProvider` call reports tokens/latency); Prometheus exporters + Grafana dashboard stubs for the latency ledger and per-tenant usage (feeds billing later).

**Phase-0 exit criteria:** CI enforces P1/P6 mechanically; core interfaces merged and frozen behind change control; dev stack reproducible.

---

## 6. Phase 1 — Core Platform MVP: Chat Agent End-to-End (Weeks 5–12)

**Objective:** one pilot tenant converses with a grounded, tool-using agent over web chat, through the full L6→L5→L4→L2 path. This is the earliest revenue-capable artifact (chat-only pilots per the $500 "Paid Pilot" motion in the business analysis).

### 6.1 Epic 1.1 — Model runtime plugins (L1)
- `plugins/llm/ollama` and `plugins/llm/vllm` implementing `LLMProvider` (OpenAI-compatible local endpoints; streaming with early-cancel; grammar-constrained decoding via outlines/xgrammar for `json_schema`).
- `ModelRouter` with `fast` / `reason` / `extract` profiles + `TenantModelPolicy` store in Postgres (§4.2).
- Model zoo provisioning scripts: Qwen 2.5 72B-AWQ (vLLM, reason), Qwen 2.5 7B / Llama 3.2 3B (Ollama, fast), BGE-M3 + bge-reranker-v2-m3.
- **Acceptance:** router selects engine by task profile; constrained decoding validates 100% against schema in tests; Langfuse traces populated.

### 6.2 Epic 1.2 — RAG service + ingestion (L3)
- `plugins/memory/qdrant` (`QdrantStore`) with both isolation modes: collection-per-tenant and shared+payload-filter, selected by `data_residency` (§4.3). `PgVectorStore` as second adapter to prove the seam.
- Embedding plugin (BGE-M3 dense+sparse) and reranker plugin.
- `RAGService`: hybrid retrieve → rerank → citation packing → **grounding verifier** (NLI-style check with small local model; uncited claims blocked) (§4.3).
- Ingestion pipeline (§12.2) as Dagster assets: MinIO loader → Docling parser → Presidio PII classifier (SPII exclusion per tenant policy) → structure-aware chunker (512-token, 15% overlap) → embed → upsert + **lineage rows** (tenant, source_uri, content_hash) — lineage is a Phase-3 erasure prerequisite, built now.
- **Acceptance:** ingest a real client handbook PDF; grounding evals (RAGAS-style, local) meet baseline faithfulness/citation-coverage thresholds; `delete_by_source` verified against lineage.

### 6.3 Epic 1.3 — MCP tool bus (L2)
- `MCPClientPool` on the official MIT Python SDK: per-tenant configs, static allow-lists (never `*`), namespaced tool IDs (`mcp.<server>.<tool>`), client-side schema re-validation, runtime catalog-change quarantine, OpenBao credential resolution at call time, Keycloak OAuth 2.1 for remote servers (§4.4 threat model — all five NSA mitigations are in-scope now, not later).
- First-party MCP servers: `mcp-servers/sql-readonly` and `mcp-servers/calendar` (CalDAV) — enough for a booking demo.
- **Acceptance:** security unit suite covering tool-name spoofing, catalog mutation quarantine, schema-injection payloads; pool is the only code path with outbound side effects (import-linter verified).

### 6.4 Epic 1.4 — Compliance chain skeleton (L5)
Full chain wiring with production-grade order, initial-depth implementations (§6):
1. `ConsentGate` — fail-closed check against the consent registry (purposes seeded manually this phase; Consent Manager API integration is Phase 3).
2. `PIIMaskingInterceptor` — Presidio analyzer + reversible token vault (AES-GCM, keys from OpenBao); **Indian recognizers day one:** Aadhaar, PAN, UPI VPA, IFSC, Indian phone formats (§6.2).
3. `PolicyGuard` — OPA sidecar, base Rego policy pack with `read`/`write`/`high_risk` tiers (§6.3).
4. `RateLimiter` — per-tenant/per-tool budgets in Valkey.
5. `AuditRecorder` — append-only Postgres, `sha256(prev_hash || payload)` hash chain; nightly anchor export to MinIO WORM bucket (§6.4).
- **Acceptance:** chain cannot be bypassed (import-linter); `ComplianceViolation` short-circuits to audited refusal; hash-chain tamper test detects any row edit; LLM never receives an unmasked Aadhaar/PAN in any test transcript.

### 6.5 Epic 1.5 — Langflow orchestration layer (L4)
- Self-hosted Langflow deployment (dev + staging + prod workspaces; prod has no design UI access for tenant flows).
- **SAAP custom component library v1** (§5.2): `ComplianceIngress` (sealed), `ModelRouterLLM`, `RAGRetriever`, `GroundedResponder` (sealed), `MCPToolkit` (sealed, OPA-gated, HITL output port), `HITLCheckpoint` (sealed), `AuditClose` (sealed).
- `LangflowHTTPRuntime` client with tenant-global-variable injection (tenancy is data; flows are tenant-agnostic templates) and session-scoped memory (§4.5).
- **Flow Linter** (`tools/flow_linter/`) in CI (§5.3): unique `ComplianceIngress` entry; every LLM→output path passes `GroundedResponder`; tool paths terminate in `AuditClose`; no raw HTTP/REPL components in tenant flows; sealed-component checksum pinning.
- Flows-as-code pipeline: export → Git PR under `flows/` → lint → eval gate → `upsert_flow` promote → `FlowRef` with checksum + lint report id; rollback = rebind previous ref.
- **HITL pause/resume**: `ApprovalRequest` persistence, agency-console approval queue (minimal UI), webhook re-invocation with approval token, scheduler-driven expiry auto-deny (§5.4).
- **The canonical flow** `vertical_agent_canonical` built and committed as the template every vertical clones (§5.1).
- **Acceptance:** a flow missing a sealed component cannot merge; approve/deny/expiry round-trip works end-to-end with conversational context restored.

### 6.6 Epic 1.6 — Gateway + web chat channel (L6/L7)
- FastAPI gateway: `ChannelAdapter` contract, `WebChatAdapter` (WebSocket/SSE), channel auth (widget JWT) *before* `TenantContext` construction, session affinity in Valkey, per-channel rate limits (§12.1).
- Embeddable chat widget + minimal agency console (tenant list, approval queue, flow bindings, audit search).
- **Eval harness v1** (`tools/eval_harness/`): golden-transcript YAML replay against staging flows with VCR-style MCP cassettes; local judge model scoring; hard assertions on tool names/args (§15). Wired into CI as the eval gate for flow promotion.

**Phase-1 milestone gate (Week 12):** live demo — pilot tenant's web-chat agent answers policy questions with citations from their own documents, books a calendar slot through MCP (auto-allowed `write` in business hours), routes a refund-like request to HITL, and every hop appears in the audit chain and Langfuse. Golden-transcript suite green.

---

## 7. Phase 2 — Voice Pipeline (Weeks 13–20)

**Objective:** the flagship product — full-duplex phone agents on PSTN at ≤500 ms median voice-to-voice, marginal cost $0.01–0.03/min (§7).

### 7.1 Epic 2.1 — Telephony substrate
- FreeSWITCH deployment + SIP trunk procurement (carrier eval: at least 2 trunk providers for redundancy); LiveKit server + LiveKit SIP bridge; number provisioning/porting runbook per tenant.
- **Acceptance:** inbound PSTN call lands in a LiveKit room; DTMF/IVR fallback path works when no agent is available (graceful-degradation requirement, §16).

### 7.2 Epic 2.2 — Speech plugins (L1/L3)
- `plugins/voice/faster_whisper` (`StreamingSTT`, CTranslate2 int8, partial hypotheses), `plugins/voice/silero` (`VAD`, barge-in events), `plugins/voice/piper` (`StreamingTTS`, sentence-level chunking, first-chunk <100 ms) per §7.1 contracts.
- GPU capacity plan: single RTX-4090-class card target for Whisper-small int8 + Piper + 7B Q4 sustaining multiple concurrent calls; per-tenant concurrency budgets.

### 7.3 Epic 2.3 — Voice session runtime
- LiveKit Agents worker (`saap-voice`): `VoicePipelineFactory` assembling VAD → STT → DialogEngine → TTS with the **latency budget ledger** instrumented per stage (§7.2, §14).
- **`LangflowEmbeddedRuntime` via `lfx`** — the same exported flow JSON as chat runs in-process (no HTTP hop); `ModelRouterLLM` pinned to `fast` profile for turn latency.
- Barge-in: VAD speech-start during playback cancels TTS + LLM stream (early-cancel path built in Phase 1).
- Filler-utterance behavior for tools >~700 ms; long tools continue as background tasks woven into the next turn.
- Call recordings → MinIO under tenant retention policy; transcripts pass PII interceptor before storage.
- `transfer_to_human(reason)` with FreeSWITCH bridge to a configured human line.
- **Acceptance:** Grafana latency-ledger SLO dashboard shows median ≤500 ms voice-to-voice over a 100-call synthetic soak; barge-in interrupts within one audio frame budget; recording + masked transcript stored per policy.

### 7.4 Epic 2.4 — Voice quality and load hardening
- Golden voice-call transcripts added to the eval harness (replayed as audio via TTS injection).
- Concurrency load test: N simultaneous calls per GPU with degradation curve documented; overflow → IVR/human-transfer, never dead air.
- Cost model validation: measured per-minute cost report (GPU amortization + trunk) vs. the $0.01–0.03 target — this number goes straight into sales collateral (pillar of the pricing pitch).

**Phase-2 milestone gate (Week 20):** live PSTN demo call — caller books a dental appointment; agent handles an interruption mid-sentence; CRM row visible; latency SLO panel green; per-minute cost sheet published.

---

## 8. Phase 3 — Compliance Completion + Multilingual (Weeks 17–26, overlapping Phase 2)

**Objective:** meet DPDP Phase 2 **before 13 Nov 2026**, engineer everything DPDP Phase 3 requires, and open the Indic-language market (§2.5, §6, §8).

### 8.1 Epic 3.1 — Consent Manager integration (statutory: 13 Nov 2026)
- Consent Manager API client wrapped as an **MCP server behind `ConsentGate`** (§16): validate explicit purpose-specific consent before processing; consent registry sync; `consent.revoked` domain event → same-transaction enrollment deletion + pending-approval cancellation + erasure enqueue (§12.3).
- Consent capture UX in chat widget and voice greeting scripts (per-locale wording, legal review).
- **Deadline management:** feature-complete by **Week 17 (mid-Oct)**, two-week buffer for integration testing against the registered Consent Manager sandbox, production sign-off no later than **Week 19 (early Nov)**.

### 8.2 Epic 3.2 — Erasure and retention (DPDP Phase 3 engineering)
- `ErasureService` as a Dagster job (§6.4): consent registry → expired purposes → `VectorStore.delete_by_source` (lineage-exact) + Postgres purge + MinIO object delete + TokenVault key destruction (crypto-shredding) → **signed erasure certificate per tenant per run**.
- Retention policies per data class and tenant; encryption-at-rest verification across Postgres/MinIO/Qdrant; TLS everywhere in transit.

### 8.3 Epic 3.3 — 72-hour breach protocol
- Grafana/Prometheus alert rules on anomalous vault access and audit-chain anomalies → FlowScheduler event webhook → **incident-response Langflow flow** assembling the notification dossier; the 72-hour clock starts at the alert row (§6.4).
- Tabletop exercise + timed drill: alert → dossier draft in < 4 hours.

### 8.4 Epic 3.4 — Multilingual/Indic pipeline
- `plugins/i18n/indictrans2` (`TranslationProvider`, protected-span preservation so PII placeholders survive translation) and `indicxlit` transliteration (§8).
- Indic STT checkpoints (IndicConformer/IndicWhisper) routed by `LocaleRouter`; Piper Indic voices (ta-IN, hi-IN first; mr-IN, gu-IN next).
- "Pivot at the edges" wiring: `Translate` component at flow boundaries; dialog engine reasons in English internally.
- Unsupported-locale behavior: human transfer, never degraded output.
- **Acceptance:** Tamil voice call end-to-end under the 2 s multilingual bar (both NMT directions <50 ms on GPU); PII placeholders verified intact across translation in tests.

### 8.5 Epic 3.5 — Security hardening pass
- NeMo Guardrails/Guardrails-AI rails on tenant-facing flows; safety-probe corpus in the eval harness (jailbreaks, prompt injection, **MCP tool-poisoning payloads embedded in retrieved documents** — must refuse or quarantine, never execute) (§15).
- External penetration test scoped to gateway, MCP bus, Keycloak, and the approval webhook.

**Phase-3 milestone gate (Week 26):** Consent Manager live in production (statutory box checked); erasure job produces a signed certificate on a test tenant; breach drill inside 72-hour envelope; Tamil + Hindi demos pass evals; pen-test criticals closed.

---

## 9. Phase 4 — Multi-Tenancy at Scale: Blueprints, CRM, Billing, Campaigns (Weeks 21–30, overlapping Phase 3)

**Objective:** the "snapshot economics" that make agency margins work — onboarding a new client becomes `saap tenant create --blueprint verticals/dental/v1` (§9).

### 9.1 Epic 4.1 — Tenant blueprint engine
- Blueprint schema (YAML, Git-versioned): flows (as pinned `FlowRef`s), MCP server configs + allow-lists, RAG sources, campaigns, Rego policies, locales, consent purposes, branding (§9.2).
- Idempotent provisioner mapping one tenant to: Keycloak realm client, Qdrant isolation unit, Postgres schema, OPA data document, MCP configs, CRM workspace, ingestion sources.
- Tenant deprovisioning = erasure job + resource teardown (compliance-grade offboarding).
- **Acceptance:** create → converse → destroy a tenant entirely via CLI; re-applying a blueprint is a no-op; drift detection reports manual changes.

### 9.2 Epic 4.2 — CRM layer (GoHighLevel replacement)
- Deploy **Twenty** (primary; EspoCRM adapter later) white-labeled per tenant; build `mcp-servers/twenty-crm` (create_contact, book_slot, log_activity, pipelines) so agents stay CRM-agnostic (§9.3).
- White-label theming (`WhiteLabelTheme`) across CRM + chat widget + client dashboard.

### 9.3 Epic 4.3 — Campaign state machines + FlowScheduler
- `campaign_enrollments` table + **FlowScheduler** (logic-free APScheduler service, ≈100 lines: select due rows where consent valid — fail closed — POST to campaign FlowRef) (§5.4).
- Idempotent retries via enrollment version key; crash-safety by transactional state transitions.
- First campaign flow: `campaigns/dental_recall/1.x.json` (6-month recall: due → voice call → outcome switch → booking write or SMS follow-up → state write → audit close).
- **Acceptance:** kill the scheduler mid-run and verify zero lost/duplicated actions; consent revocation halts a mid-flight campaign.

### 9.4 Epic 4.4 — Billing and metering
- Usage events (per-tenant minutes, tokens, tool calls) from Langfuse/Prometheus exporters → **Lago** (or Kill Bill) for metered billing with agency markup — the SaaS-Pro rebilling motion from the business analysis (§9.3).
- Agency console: per-tenant P&L view (usage cost vs. retainer).

### 9.5 Epic 4.5 — Additional channels
- `WebhookAdapter` (HMAC-signed ingress) and `MatrixWhatsAppAdapter` (mautrix bridge) per the §12.1 contract; `EmailAdapter` if a design partner needs it.

**Phase-4 milestone gate (Week 30):** fresh dental tenant from blueprint in <30 minutes — white-labeled CRM, working voice + chat agents, recall campaign armed, billing meter running.

---

## 10. Phase 5 — Vertical Packs, AI Audit, Go-to-Market (Weeks 27–36, overlapping Phase 4)

**Objective:** productize the niches the business analysis prices, and build the acquisition engine that sells them.

### 10.1 Epic 5.1 — Vertical pack: Dental/Healthcare ($2k–5k retainers)
The "4-bot patient lifecycle" as flows + blueprint (§9.2): `dental.intake` (Lead Conversion, 60-second response), `dental.patient_education_rag`, `dental.clinical_governance`, patient-services deflection; `campaigns/dental_recall`; `mcp-servers/openemr-bridge` (read_schedule); dental Rego pack (business-hours writes, high-risk = record changes); ICD-code Presidio recognizers; golden-transcript suite (≥5 per flow, incl. no-show-reduction scenarios).

### 10.2 Epic 5.2 — Vertical pack: Real Estate ($1k–3.5k retainers)
Speed-to-lead qualifier per the worked example (§13): `realestate.lead_qualifier` cloned from canonical canvas; **`LeadScoreExtractor`** component (grammar-constrained {budget, timeline, preapproved, bedrooms}); `realestate.maintenance_triage` with urgency categorization and vendor work-order dispatch; listings-sql MCP server; viewing bookings auto-allowed `write`, rent discounts `high_risk` → HITL.

### 10.3 Epic 5.3 — Vertical pack #3: Legal intake or E-commerce (pick by design-partner demand)
- Legal: intake forms, case-status updates, document sorting (high hourly-value ROI story: 20 hrs × $400 = $8k/mo savings).
- E-commerce: abandoned-cart recovery campaign + inventory MCP server.

### 10.4 Epic 5.4 — AI Audit flow (client acquisition)
- One Langflow flow chaining three Agent components — Acquisition-Engine Analyst (web-scrape + speed-to-lead probe MCP tools), Automation Economist (`ROICalculator` component), Report Writer — emitting an **Opportunity Matrix JSON + rendered PDF** with ROI summary (§5.5).
- Published as an MCP server so the agency's internal assistant can invoke it.
- Two packagings per the business analysis: paid mid-market engagement ($5k–10k) and free SME lead-magnet variant (rapid digital-footprint scan + inputs for a personalized 3-minute demo video pitch).

### 10.5 Epic 5.5 — Onboarding playbook + docs
- "New vertical" recipe validated end-to-end by a non-core engineer following §11 docs (clone canvas → Rego → MCP config → blueprint → evals) with zero core changes.
- Designer documentation for the Langflow workspace (synthetic data only in dev; no prod MCP credentials — anti-"shadow flows" control, §16).

**Phase-5 milestone gate (Week 36):** 3 vertical packs pass eval suites; audit flow demo produces a client-ready PDF; ≥3 paying tenants live (target from the pilot pipeline); "paid pilot → retainer" collateral includes the measured cost-advantage numbers from Phase 2.

---

## 11. Phase 6 — Scale, Hardening, and DPDP Phase-3 Sign-off (Week 33 →, continuous)

- **`scale` profile:** Helm charts mirroring compose; vLLM pool with tensor parallelism; stateless Langflow runtime replicas behind the gateway (flows + sessions in Postgres — SPOF mitigation, §16); LiveKit distributed.
- **`edge` profile:** single-box client-site deployment (Ollama 7B + Whisper-small + Piper) — data never leaves premises; the strongest DPDP posture and a premium sales SKU (§10).
- Chaos testing (runtime replica kill, Postgres failover, GPU exhaustion → IVR degradation), backup/restore + DR runbooks with restore drills.
- Fine-tuning workstream (Unsloth/PEFT/Axolotl): vertical LoRA adapters (dental intake tone, legal style) gated by golden-transcript regression (§2.1, §16).
- **DPDP Phase-3 evidence pack** (target: complete by **March 2027**, two months ahead of the 13 May 2027 hard deadline): erasure certificates, encryption attestations, breach-drill reports, audit-chain verification, processor contracts.
- Quarterly license re-scan and upstream-drift review (the Redis→RSAL pattern, §16); pinned-fork upgrade policy.

---

## 12. Cross-Cutting Workstreams (run in every phase)

| Workstream | Cadence | Key artifacts |
|-----------|---------|---------------|
| **Quality/evals** | Every PR | Golden transcripts, grounding evals, safety probes; Langfuse baselines so regressions are diffs (§15) |
| **Flow governance** | Every flow change | Flow Linter, checksum-pinned sealed components, staged promotion, FlowRef rollback |
| **License compliance** | Every dependency change | LicenseGate CI, quarterly tree re-scan |
| **Security** | Phase gates + continuous | MCP threat-model suite, guardrail probes, pen tests (Phases 3, 6) |
| **Observability/SLOs** | Continuous | Latency ledger, per-tenant cost/usage, ingestion freshness alerts |
| **Documentation** | Continuous | Runbooks, designer guides, blueprint recipes, compliance evidence |

---

## 13. Team Plan

Minimum viable team (roles can be combined early; the architecture's whole point is that vertical delivery needs *no* core engineers, §11/§13):

| Role | Count | Primary phases |
|------|-------|----------------|
| Platform/backend engineer (Python, core + plugins + gateway) | 2 | 0–4 |
| Voice/media engineer (LiveKit, FreeSWITCH, latency) | 1 | 2, 6 |
| ML engineer (model serving, RAG quality, fine-tuning, evals) | 1 | 1–3, 6 |
| DevOps/SRE (compose→Helm, GPU fleet, observability) | 1 | 0, 2, 6 |
| Compliance/security engineer (can be fractional: OPA, Presidio, DPDP, pen-test liaison) | 1 | 1, 3 |
| Flow designer / solutions engineer (Langflow canvas, vertical packs, golden transcripts) | 1–2 | 4–5 |
| Legal counsel (DPDP, consent wording, processor contracts) | fractional | 3 |

**Sequencing rationale:** the two platform engineers + ML engineer carry Phases 0–1; the voice engineer starts ~Week 10 (prep) for Phase 2; the flow designer joins by Phase 4 so vertical authoring is proven to work without core-team involvement — that proof *is* the scalability claim of the business model.

---

## 14. Environments and Infrastructure Budget

| Environment | Profile | Hardware |
|-------------|---------|----------|
| Dev (per engineer) | compose `dev`, 3B models CPU-only | Laptop / small VM |
| Shared GPU dev/staging | `agency` profile | 1× server, 2× 24 GB-class GPUs (vLLM 72B-AWQ TP2) + 1× consumer GPU (voice fast path) |
| Production (initial) | `agency` profile | Same shape as staging, isolated; SIP trunks ×2 carriers |
| Production (Phase 6) | `scale` on K8s | GPU pool sized by tenant demand |
| Client edge (optional SKU) | `edge` | 1 consumer-GPU box per site |

CI needs a CPU-only path (3B model, per §15) so the full integration suite runs on ordinary runners; nightly GPU jobs run latency/soak suites on staging.

---

## 15. KPIs, SLOs, and Definition of Done

**Engineering SLOs (Grafana-alerting from the phase they land):**
- Voice: median voice-to-voice ≤500 ms; p95 ≤800 ms; barge-in cancel <150 ms; zero dead-air (fallback engaged instead).
- Chat: first token ≤1.5 s (fast profile).
- Multilingual: end-to-end ≤2 s per turn.
- RAG: citation coverage and faithfulness above the Phase-1 baseline on every promoted flow; grounding verifier blocks 100% of uncited claims in evals.
- Compliance: 0 unmasked PII instances reaching a model in tests; 100% of tool calls carry OPA decision + audit row; erasure job completes with certificate; breach dossier < 4 h in drills.
- Platform: tenant provisioning <30 min from blueprint; flow rollback <5 min.

**Business KPIs (from the analysis, tracked in the agency console):**
- Marginal voice cost/min in the $0.01–0.03 band (measured, not modeled).
- Pilot → retainer conversion; retainer bands by vertical vs. the analysis's benchmarks.
- Client speed-to-lead (e.g., 60-second inbound response for healthcare/RE tenants); no-show reduction for dental (analysis benchmark: 18–25% recovered revenue).

---

## 16. Risk Register (plan-level; architecture risks in §16 of the architecture doc)

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|-----------|
| R1 | DPDP Phase-2 Consent Manager ecosystem/sandbox not ready when we are | Med | High (statutory) | Start Epic 3.1 at Week 17 with buffer; interface isolated behind `ConsentGate` MCP server so a late-changing external API touches one module |
| R2 | Voice latency target missed on chosen hardware | Med | High (flagship offer) | Latency ledger instrumented per stage from first spike; fallback levers: smaller STT model, 3B fast-path LLM, sentence-chunked TTS overlap; embedded `lfx` already removes the HTTP hop |
| R3 | Langflow upstream API/JSON-format churn | Med | Med | Pin versions; `LangflowRuntime` protocol seam isolates the client; flow JSON checksummed so drift is detected, not silently absorbed |
| R4 | Local-model quality below client expectation in a vertical | Med | Med | Tight RAG grounding + constrained decoding first; vertical LoRA adapters (Phase 6); eval-gated model swaps; scope pilots to narrow workflows where the analysis shows local models suffice |
| R5 | GPU capacity spikes during concurrent calls | Med | Med | Per-tenant concurrency budgets; IVR + human-transfer degradation; capacity curve measured in Epic 2.4 before sales commits to volumes |
| R6 | Single design-partner dependency for requirements | Med | Med | Recruit 2–3 design partners across two verticals by Phase 1 gate |
| R7 | Team bandwidth: compliance work starving feature work | Med | Med | Phases 2 and 3 run on separate tracks with separate owners; compliance engineer role staffed by Phase 1 |
| R8 | License drift in a pinned dependency | Low | Med | LicenseGate on every dependency change + quarterly re-scan; forks pre-identified (Valkey, OpenBao) |
| R9 | Canvas sprawl / shadow flows once designers onboard | Med | Med | Only linter-passed, Git-committed FlowRefs bindable to tenants; dev workspace has no tenant data or prod credentials (§16) |
| R10 | Scope creep into building a general SaaS product | Med | High | Non-goals honored (§1.2); phase gates demand a *client-demoable* outcome, not platform generality |

---

## 17. Milestone Calendar (summary)

| Date (approx.) | Milestone |
|----------------|-----------|
| End Jul 2026 (W4) | Phase 0 gate: enforced skeleton, dev stack, core contracts |
| End Sep 2026 (W12) | Phase 1 gate: grounded, tool-using chat agent for pilot tenant; HITL + audit live |
| **Early Nov 2026 (W19)** | **DPDP Phase-2 Consent Manager integration in production (statutory: 13 Nov 2026)** |
| Mid Nov 2026 (W20) | Phase 2 gate: PSTN voice agent at ≤500 ms; cost sheet published |
| End Dec 2026 (W26) | Phase 3 gate: erasure + breach protocol tested; Tamil/Hindi live; pen-test clean |
| End Jan 2027 (W30) | Phase 4 gate: blueprint-provisioned tenant in <30 min; CRM + billing + campaigns |
| End Mar 2027 (W36) | Phase 5 gate: 3 vertical packs; AI Audit flow; ≥3 paying tenants |
| **Mar–Apr 2027** | **DPDP Phase-3 evidence pack complete (statutory hard deadline: 13 May 2027)** |
| From Feb 2027 | Phase 6: `scale`/`edge` profiles, chaos/DR, LoRA fine-tuning |

---

## 18. Immediate Next Steps (first two sprints)

1. Stand up the monorepo skeleton, CI, and **LicenseGate** (Epic 0.1) — nothing merges without it.
2. Land `saap.core` contracts with fakes and tests (Epic 0.2).
3. Bring up the dev compose profile incl. Langflow and a 3B Ollama model (Epic 0.3).
4. Recruit/confirm 2–3 design partners (one dental, one real estate) and collect their real documents + call scripts for Phase-1 RAG ingestion and golden transcripts.
5. Order/reserve GPU hardware for staging (2× 24 GB-class + 1 consumer card) and open SIP-trunk carrier conversations (long lead time; needed Week 13).
6. Book the Consent Manager sandbox access and legal review slots now — the 13 Nov 2026 date is the one deadline in this plan we cannot move.
