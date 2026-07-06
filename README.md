# SAAP — Sovereign AI Automation Platform

An open-source, local-first platform for building AI Automation Agency
(AAA) products: chat and voice agents, vertical RAG knowledge systems,
and compliance-by-construction (DPDP/GDPR) multi-tenant operations.

- **Business case:** `AI Business Idea Analysis.pdf`
- **Reference architecture:** `open-source-aaa-architecture.md`
- **Delivery roadmap:** `implementation-plan.md`

This repository contains the Phase 0/1 implementation: the plugin
contract layer (`saap.core`), the non-bypassable compliance chain
(`saap.compliance`), first-party plugins (Ollama, Qdrant), and a
working chat gateway — the foundation every later phase builds on.

## Repository layout

```
saap/
├── core/                 interfaces only — types, llm, memory, mcp, flow, registry, events
├── compliance/            L5 interceptor chain: consent, PII masking, policy, rate limit, audit
├── plugins/
│   ├── llm/ollama/        LLMProvider over a local Ollama daemon
│   └── memory/qdrant/     VectorStore over Qdrant
├── gateway/                FastAPI app, WebChatAdapter, LangflowHTTPRuntime
├── langflow_components/   (Phase 1 Epic 1.5 — SAAP custom component library)
├── scheduler/             (Phase 4 — FlowScheduler)
├── tenancy/               (Phase 4 — blueprint engine)
└── ingest/                (Phase 1 Epic 1.2 — document ingestion pipeline)
flows/                     exported Langflow flow JSON (Git-versioned)
mcp-servers/                first-party MCP servers (calendar, sql-readonly, ...)
migrations/                Alembic schema: tenants, consent, audit, campaigns, approvals, flows, lineage
tools/
├── license_gate/          P1 enforcement — CI fails on non-OSI dependency licenses
├── flow_linter/           (Phase 1 Epic 1.5 — sealed-component / compliance-path linter)
└── eval_harness/          (Phase 1 Epic 1.6 — golden-transcript regression suite)
deploy/                     docker-compose dev profile, Dockerfiles
tests/                      mirrors saap/ + tools/
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
| L5 compliance chain (consent, PII masking, policy, rate limit, audit) | ✅ Implemented, in-memory + OPA/Presidio-backed variants |
| LicenseGate (P1 enforcement) | ✅ Implemented, verified clean against this repo's own dependencies |
| Ollama LLMProvider, Qdrant VectorStore | ✅ Implemented |
| Gateway + WebChatAdapter | ✅ Implemented (dev fallback + real `LangflowHTTPRuntime`) |
| Postgres schema (Alembic) | ✅ Implemented |
| CI (lint, typecheck, tests, LicenseGate, migration check) | ✅ Implemented |
| SAAP Langflow custom component library (`ComplianceIngress`, `MCPToolkit`, etc.) | ⬜ Phase 1 Epic 1.5 |
| Flow Linter | ⬜ Phase 1 Epic 1.5 |
| RAG ingestion pipeline (Docling, Dagster assets) | ⬜ Phase 1 Epic 1.2 |
| Voice pipeline (LiveKit, FreeSWITCH, faster-whisper, Piper) | ⬜ Phase 2 |
| Multilingual/Indic pipeline | ⬜ Phase 3 |
| Tenant blueprint engine, CRM, billing | ⬜ Phase 4 |
| Vertical packs, AI Audit flow | ⬜ Phase 5 |

See `implementation-plan.md` for the full phase-by-phase roadmap.
