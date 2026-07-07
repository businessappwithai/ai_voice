"""Tenant blueprint schema (Phase 4 Epic 4.1) — the Git-versioned YAML
that turns "onboard a new client" into `saap tenant create --blueprint
verticals/dental/v1`: everything a tenant needs (flows, MCP configs,
RAG sources, campaigns, policy packs, locales, consent purposes,
branding) declared once and applied idempotently.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel
from saap.core.flow import FlowRef
from saap.core.types import Locale


class MCPServerConfig(BaseModel, frozen=True):
    name: str  # "calendar", "sql-readonly", "twenty-crm", ...
    allow_list: tuple[str, ...] = ()  # tool names this tenant may call; empty = deny-all


class TenantBlueprint(BaseModel, frozen=True):
    name: str  # "acme-dental" — the tenant's slug
    vertical: str  # "dental", "realestate", "legal", ...
    locales: tuple[Locale, ...] = (Locale.EN_IN,)
    flows: tuple[FlowRef, ...] = ()
    mcp_servers: tuple[MCPServerConfig, ...] = ()
    rag_sources: tuple[str, ...] = ()  # source URIs the ingestion pipeline should sync
    campaigns: tuple[str, ...] = ()  # campaign flow names FlowScheduler may dispatch
    policy_packs: tuple[str, ...] = ()  # Rego pack names bound in OPA
    consent_purposes: tuple[str, ...] = ()  # purposes this tenant may request consent for
    branding: dict[str, str] = {}  # {"logo_url": ..., "primary_color": ...}


def load_blueprint(path: Path) -> TenantBlueprint:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return TenantBlueprint.model_validate(raw)
