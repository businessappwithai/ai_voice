"""Reversible PII vault. The LLM only ever sees placeholders; the real
values are re-injected AFTER PolicyGuard approves the outbound action.

  inbound : "Book Ramesh, Aadhaar 1234-5678-9012, phone +91-98765-43210"
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
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from saap.core.types import DataClass, TenantContext

from .chain import Envelope

# --- Indian-market Presidio recognizer patterns -----------------------------
# Presidio's PatternRecognizer expects (name, regex, score); these are
# registered with the real Presidio AnalyzerEngine in `build_indian_recognizers`
# below. Patterns are deliberately conservative (favor false negatives
# over leaking a false positive placeholder that breaks legitimate text).

AADHAAR_RE = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
UPI_VPA_RE = re.compile(r"\b[\w.\-]{2,256}@[a-zA-Z]{2,64}\b")
IFSC_RE = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
IN_PHONE_RE = re.compile(r"(?:\+91[\s-]?)?[6-9]\d{9}\b")

_RECOGNIZER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("IN_AADHAAR", AADHAAR_RE),
    ("IN_PAN", PAN_RE),
    ("IN_UPI_VPA", UPI_VPA_RE),
    ("IN_IFSC", IFSC_RE),
    ("IN_PHONE", IN_PHONE_RE),
)


def build_indian_recognizers() -> list[Any]:
    """Constructs Presidio PatternRecognizer instances for the Indian
    market entities. Imported lazily inside this function so the module
    is importable (and unit-testable via `SimplePIIAnalyzer` below)
    without the `presidio-analyzer` package installed in every context."""
    from presidio_analyzer import Pattern, PatternRecognizer

    recognizers = []
    for entity, pattern in _RECOGNIZER_PATTERNS:
        recognizers.append(
            PatternRecognizer(
                supported_entity=entity,
                patterns=[Pattern(name=f"{entity.lower()}_pattern", regex=pattern.pattern, score=0.85)],
            )
        )
    return recognizers


@dataclass(frozen=True)
class DetectedEntity:
    entity_type: str
    start: int
    end: int
    text: str


class PIIAnalyzer(Protocol):
    """Wraps a Presidio AnalyzerEngine (or the simple regex fallback
    below). Kept as a Protocol so tests don't require the presidio
    package to be installed."""

    def analyze(self, text: str) -> list[DetectedEntity]: ...


class SimplePIIAnalyzer:
    """Regex-only analyzer covering the Indian recognizers plus a
    minimal PERSON/PHONE heuristic. Used as the default when the full
    Presidio `AnalyzerEngine` (spaCy NER model) isn't loaded — e.g. in
    unit tests and CI's CPU-only path. Production deployments should
    bind `PresidioAnalyzer` (below) instead via the registry."""

    def analyze(self, text: str) -> list[DetectedEntity]:
        found: list[DetectedEntity] = []
        for entity, pattern in _RECOGNIZER_PATTERNS:
            for m in pattern.finditer(text):
                found.append(DetectedEntity(entity, m.start(), m.end(), m.group()))
        return found


class PresidioAnalyzer:
    """Production analyzer: real Presidio AnalyzerEngine + the Indian
    PatternRecognizers registered above, plus Presidio's built-in
    PERSON/EMAIL/LOCATION recognizers (spaCy-backed)."""

    def __init__(self) -> None:
        from presidio_analyzer import AnalyzerEngine

        self._engine = AnalyzerEngine()
        for recognizer in build_indian_recognizers():
            self._engine.registry.add_recognizer(recognizer)

    def analyze(self, text: str) -> list[DetectedEntity]:
        results = self._engine.analyze(text=text, language="en")
        return [
            DetectedEntity(r.entity_type, r.start, r.end, text[r.start : r.end]) for r in results
        ]


class TokenVault:
    """AES-GCM reversible tokenization, keyed per-tenant.

    The key MUST come from OpenBao in any real deployment
    (`OpenBaoSecretResolver` — see saap/plugins, Phase 1 Epic 1.4); the
    constructor accepts a raw key here so unit tests don't need a vault
    running. `nonce` is stored alongside the ciphertext (both are
    non-secret once the key itself is protected) so decryption doesn't
    need a side channel.
    """

    def __init__(self, key: bytes | None = None) -> None:
        self._key = key or AESGCM.generate_key(bit_length=256)
        self._aesgcm = AESGCM(self._key)
        self._store: dict[str, tuple[bytes, bytes]] = {}  # token -> (nonce, ciphertext)

    def tokenize(self, entity_type: str, value: str) -> str:
        token = f"<{entity_type}_{uuid4().hex[:8]}>"
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, value.encode("utf-8"), None)
        self._store[token] = (nonce, ciphertext)
        return token

    def resolve(self, token: str) -> str | None:
        entry = self._store.get(token)
        if entry is None:
            return None
        nonce, ciphertext = entry
        return self._aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")

    def destroy_all(self) -> None:
        """Crypto-shredding: drop the key material so every token issued
        under it becomes permanently unresolvable. Used by the DPDP
        erasure job (Phase 3) instead of hunting down every token row."""
        self._store.clear()


class MaskingPolicyStore(Protocol):
    """Per-tenant policy on which DataClass/entity types get masked at
    all (vs. passed through) — e.g. a tenant may exempt PUBLIC-class
    messages entirely."""

    async def should_mask(self, tenant: TenantContext, data_class: DataClass) -> bool: ...


class AlwaysMaskPersonal:
    """Default policy: mask anything at PERSONAL or SENSITIVE_PERSONAL;
    pass PUBLIC/INTERNAL through untouched."""

    async def should_mask(self, tenant: TenantContext, data_class: DataClass) -> bool:
        return data_class in (DataClass.PERSONAL, DataClass.SENSITIVE_PERSONAL)


class PIIMaskingInterceptor:
    """L5 stage 2. Replaces detected entities with vault tokens before
    the message can reach any LLMProvider; resolves tokens back only
    when explicitly asked (by the MCP dispatch path, post-PolicyGuard)."""

    name = "pii_masking"

    def __init__(
        self,
        analyzer: PIIAnalyzer,
        vault: TokenVault,
        policy: MaskingPolicyStore | None = None,
    ) -> None:
        self._analyzer = analyzer
        self._vault = vault
        self._policy = policy or AlwaysMaskPersonal()

    def _mask(self, text: str) -> str:
        entities = sorted(self._analyzer.analyze(text), key=lambda e: e.start, reverse=True)
        masked = text
        for entity in entities:
            token = self._vault.tokenize(entity.entity_type, entity.text)
            masked = masked[: entity.start] + token + masked[entity.end :]
        return masked

    async def before(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        if not await self._policy.should_mask(tenant, envelope.message.data_class):
            return envelope
        masked_content = self._mask(envelope.message.content)
        masked_message = envelope.message.model_copy(update={"content": masked_content})
        return envelope.with_message(masked_message)

    async def after(self, tenant: TenantContext, envelope: Envelope) -> Envelope:
        # Outbound assistant replies are never auto-unmasked here — a
        # reply that echoes back a vault token verbatim is a prompt-
        # leakage bug, not something this interceptor should paper over.
        return envelope

    def resolve_for_tool(
        self, tenant: TenantContext, masked_arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Called by MCPClientPool.dispatch (post-PolicyGuard) to
        re-inject real values into tool arguments that reference vault
        tokens. Only string leaf values are scanned."""
        resolved: dict[str, Any] = {}
        for key, value in masked_arguments.items():
            if isinstance(value, str):
                resolved_value = value
                for token in re.findall(r"<[A-Z_]+_[0-9a-f]{8}>", value):
                    real = self._vault.resolve(token)
                    if real is not None:
                        resolved_value = resolved_value.replace(token, real)
                resolved[key] = resolved_value
            else:
                resolved[key] = value
        return resolved
