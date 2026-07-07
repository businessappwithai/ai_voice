"""Foundational value objects shared by every layer.

Design notes
------------
* `TenantContext` is mandatory on every request-scoped object (P7).
  There is deliberately no way to construct a pipeline call without one.
* All models are immutable (frozen=True) so interceptors can never
  mutate a message in place without producing an auditable new object.
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Locale(StrEnum):
    """BCP-47 subset the platform ships voices/NMT models for."""

    EN_IN = "en-IN"
    EN_US = "en-US"
    TA_IN = "ta-IN"
    HI_IN = "hi-IN"
    MR_IN = "mr-IN"
    GU_IN = "gu-IN"
    # extended by plugins via a LocaleRegistry as Indic voices land (Phase 3)


class DataClass(StrEnum):
    """DPDP/GDPR-aligned sensitivity classes, attached to every payload."""

    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"  # PII — requires consent + masking
    SENSITIVE_PERSONAL = "spii"  # health, financial, Aadhaar/KYC


class TenantContext(BaseModel, frozen=True):
    """Identity + isolation envelope for a single client (sub-account).

    Every service method takes this as its first argument. Storage
    adapters MUST scope reads/writes with it; the compliance chain
    MUST log it; the MCP pool MUST resolve credentials with it.
    """

    tenant_id: UUID
    vertical: str  # "dental", "realestate", "legal", ...
    locale: Locale = Locale.EN_IN
    data_residency: str = "in"  # ISO country for residency policy
    consent_scope: frozenset[str] = frozenset()  # granted purposes
    trace_id: UUID = Field(default_factory=uuid4)

    def has_consent(self, purpose: str) -> bool:
        return purpose in self.consent_scope


class Message(BaseModel, frozen=True):
    """A single conversational turn, channel-agnostic."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None  # tool name for role="tool"
    data_class: DataClass = DataClass.PERSONAL
    created_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel, frozen=True):
    """LLM-proposed invocation. *Proposed* — PolicyGuard decides (P5)."""

    call_id: str
    tool_name: str  # namespaced: "mcp.crm.create_contact"
    arguments: dict[str, Any]
    risk_tier: Literal["read", "write", "high_risk"] = "read"


class ToolResult(BaseModel, frozen=True):
    call_id: str
    ok: bool
    content: Any = None
    error: str | None = None
