# SAAP — Sovereign AI Automation Platform

An open-source, local-first platform for building AI Automation Agency
(AAA) products: chat and voice agents, vertical RAG knowledge systems,
and compliance-by-construction (DPDP/GDPR) multi-tenant operations.

- **Business case:** `AI Business Idea Analysis.pdf`
- **Reference architecture:** `open-source-aaa-architecture.md`
- **Delivery roadmap:** `implementation-plan.md`

This repository contains the Phase 0/1 implementation: the plugin
contract layer (`saap.core`), the non-bypassable compliance chain
(`saap.compliance`), the Langflow component governance logic, the RAG
ingestion pipeline, first-party plugins and MCP servers, and a working
chat gateway — the foundation every later phase builds on.

## Repository layout

```
saap/
├── core/                  interfaces only — types, llm, memory, mcp, flow, registry, events
├── compliance/             L5 interceptor chain: consent, PII masking, policy, rate limit, audit
├── plugins/
│   ├── llm/ollama/         LLMProvider over a local Ollama daemon
│   └── memory/qdrant/      VectorStore over Qdrant
├── gateway/                 FastAPI app, WebChatAdapter, LangflowHTTPRuntime
├── langflow_components/
│   └── logic/               framework-agnostic logic behind each sealed canvas component
├── ingest/                  document ingestion pipeline (parse -> classify -> chunk -> embed -> lineage)
├── scheduler/               (Phase 4 — FlowScheduler)
└── tenancy/                 (Phase 4 — blueprint engine)
flows/                       exported Langflow flow JSON (Git-versioned) — Phase 1 Epic 1.5, not yet authored
mcp-servers/
├── calendar/                 list_slots / book_slot / cancel_slot over a CalendarStore protocol
└── sql-readonly/             single `query` tool, sqlparse-gated to SELECT-only
migrations/                  Alembic schema: tenants, consent, audit, campaigns, approvals, flows, lineage
tools/
├── license_gate/            P1 enforcement — CI fails on non-OSI dependency licenses
├── flow_linter/              sealed-component / compliance-path linter over exported flow JSON
└── eval_harness/             golden-transcript regression suite (YAML assertions on tool calls + grounding)
deploy/                      docker-compose dev profile, Dockerfiles
tests/                       mirrors saap/ + tools/ + mcp-servers/
```

## Quickstart (dev)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Lint, typecheck, test, license-check — same checks CI runs
ruff check saap tools tests migrations
mypy saap/core                 # strict, saap.core only for now
pytest tests/ -v
python -m tools.license_gate.gate
```

### Bring up the full dev stack

```bash
docker compose -f deploy/docker-compose.profile-dev.yaml up -d
alembic upgrade head
```

This starts Postgres, Qdrant, Valkey, MinIO, Keycloak, OpenBao,
Langflow, Langfuse, Prometheus/Grafana/Loki, and Ollama (pulling a 3B
CPU-friendly model for dev/CI).

### Run the gateway without any infra

The gateway falls back to `DirectOllamaRuntime` (plain streaming
through Ollama, no Langflow, no RAG, no sealed components) whenever
`LANGFLOW_URL`/`LANGFLOW_FLOW_ID` aren't set — enough to smoke-test the
whole L6→L5→L4 path with just Ollama running:

```bash
export SAAP_WIDGET_JWT_SECRET=dev-only-change-me
uvicorn saap.gateway.app:app --reload
```

Set `LANGFLOW_URL` + `LANGFLOW_FLOW_ID` (and optionally
`LANGFLOW_API_KEY`) once a real flow is deployed — this is the only
change needed to move from the dev fallback to production.

## What's implemented vs. what's next

| Area | Status |
|------|--------|
| `saap.core` contracts (types, llm, memory, mcp, flow, registry, events) | ✅ Implemented, mypy `--strict`, 100% fakes-tested |
| L5 compliance chain (consent, PII masking, policy, rate limit, audit) | ✅ Implemented, in-memory + OPA/Presidio-backed variants, two-phase split for canvas use |
| LicenseGate (P1 enforcement) | ✅ Implemented, verified clean against this repo's own 107 dependencies |
| LLMProvider adapters (Ollama, vLLM) | ✅ Implemented — proves P3 swappability |
| VectorStore adapters (Qdrant, pgvector) | ✅ Implemented — `PgVectorStore` verified against a real local Postgres+pgvector instance |
| Gateway + WebChatAdapter | ✅ Implemented (dev fallback + real `LangflowHTTPRuntime`) |
| Postgres schema (Alembic) | ✅ Implemented |
| CI (lint, typecheck, tests, LicenseGate, migration check) | ✅ Implemented |
| SAAP Langflow component **logic** (ComplianceIngress, MCPToolkit, GroundedResponder, HITLCheckpoint, AuditClose, ModelRouterLLM, RAGRetriever) | ✅ Implemented, fully unit-tested; thin `langflow.custom.Component` adapters not yet built/verified (the `langflow` package is too heavy to install for this environment — see note below) |
| Flow Linter | ✅ Implemented — parses exported flow JSON, enforces sealed entry/grounding/audit-close/no-raw-HTTP/checksum-pinning rules |
| RAG ingestion pipeline (parse, PII-classify, chunk, embed, lineage) | ✅ Implemented (`PlainTextParser` dependency-free default; Docling slots in via the same protocol) |
| First-party MCP servers (calendar, sql-readonly) | ✅ Implemented on the real official `mcp` SDK, not a mock |
| Eval harness (golden transcripts) | ✅ Implemented — YAML assertions on response text, tool calls, grounding |
| Voice contracts (`VAD`/`StreamingSTT`/`StreamingTTS` protocols, `LatencyLedger`) | ✅ Implemented |
| `SileroVAD` adapter | ✅ Implemented — real ONNX model (extracted from the MIT-licensed `silero-vad` wheel) via `onnxruntime`, not the `silero-vad` package (avoids its `torch` dependency) |
| `FasterWhisperSTT` adapter | 🟡 Implemented against faster-whisper's real API, but only exercised with an injected fake model — real Whisper weights aren't downloadable in this environment (Hugging Face egress is blocked) |
| Piper TTS adapter | 🟡 `PiperTTS` streaming wrapper implemented and tested; `register()` deliberately raises — the `piper-tts` PyPI package is license-unclean under P1 (see `saap/plugins/voice/piper/__init__.py`: `>=1.3.0` is GPL-3.0-or-later, `<=1.2.0` bundles a compiled GPL-3.0 `libespeak-ng.so` under an MIT label). LicenseGate's deny list now covers GPL-2.0/3.0 so a future re-add fails the build. The license-clean path (raw ONNX inference + arms-length `espeak-ng` subprocess) is not yet built |
| `VoiceSessionRuntime` (VAD→STT→DialogEngine→TTS turn-taking, latency ledger, barge-in) | ✅ Implemented and fake-tested — the turn-taking/instrumentation half of Epic 2.3's `VoicePipelineFactory` |
| LiveKit Agents worker, SIP/FreeSWITCH transport, GPU load hardening | ⬜ Phase 2 (remaining) — no LiveKit server, SIP trunk, or GPU reachable in this environment |
| `TranslationProvider` contract + `ProtectedSpanTranslator` (PII vault tokens survive the "pivot at the edges" language translation) | ✅ Implemented and tested against a fake NMT provider (including a corrupted/dropped-sentinel fail-closed case) — real `IndicTrans2` adapter not yet built (model weights unreachable) |
| `ErasureService` (per-source vector deletion + token-vault crypto-shred, signed HMAC erasure certificate chained into the audit trail) | ✅ Implemented and tested — the two storage surfaces this codebase has real adapters for; Postgres/MinIO purge deferred (no first-party client for either yet) |
| Indic STT/TTS voices (IndicConformer/IndicWhisper, Piper ta-IN/hi-IN), Consent Manager integration, 72-hour breach protocol | ⬜ Phase 3 (remaining) |
| `FlowScheduler` (campaign_enrollments claim/consent-check/dispatch/settle, crash-safe via optimistic version compare-and-swap) | ✅ Implemented and tested against the real `campaign_enrollments` schema shape (migrations/versions/0001_initial_schema.py) — Postgres-backed `EnrollmentStore` not yet written, tested against `InMemoryEnrollmentStore`'s identical CAS semantics |
| `WebhookAdapter` (HMAC-signed ingress channel, `sha256=` signature verification before tenant resolution) | ✅ Implemented and tested — the `ChannelAdapter` contract's per-request one-shot channel for client-system POSTs (Epic 4.5) |
| `TenantBlueprint` schema (YAML) + `TenantProvisioner` (idempotent apply/plan/destroy across resource ports, Terraform-style dry-run drift detection) | ✅ Implemented and tested — concrete ports (Keycloak realm, Qdrant namespace, Postgres schema, OPA doc, MCP config, CRM workspace) not bound to real services; `ErasureService` composition into `destroy` left to the calling CLI (no per-tenant source registry yet to enumerate from) |
| `policies/saap_actions.rego` + `policies/tenant/dental_clinic.rego` (the Rego source of truth `InMemoryPolicyGuard` restates in Python, referenced but missing until now) | 🟡 Written to mirror `InMemoryPolicyGuard`'s exact three-tier table and `tests/compliance/test_policy.py`'s scenarios (see `saap_actions_test.rego`), but never run through a real `opa` binary in this sandbox (no network path to fetch one) — a new CI job (`opa-policy-test`, via `open-policy-agent/setup-opa`) runs `opa test policies/` for real on every PR |
| CRM (Twenty), billing (Lago) | ⬜ Phase 4 (remaining) |
| Vertical packs, AI Audit flow | ⬜ Phase 5 |

**Note on the Langflow canvas integration:** the real `langflow` PyPI
package pulls in `langflow-base[complete]`, a very large dependency
tree (full web app, many optional vector/embedding backends) that
wasn't practical to install in this environment. Rather than guess at
`langflow.custom.Component`'s exact API and risk shipping adapter code
that's subtly wrong, the governance logic behind each sealed component
was built and fully tested as plain, framework-agnostic Python
(`saap/langflow_components/logic/`). Wiring a thin `Component` subclass
per architecture Section 5.2's documented pattern is the remaining
step, verified against a real Langflow install.

See `implementation-plan.md` for the full phase-by-phase roadmap.
