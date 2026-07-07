"""Translation contracts and the protected-span guarantee (Phase 3
Epic 3.4: "pivot at the edges" — the dialog engine always reasons in
English internally; `TranslationProvider` is only invoked at flow
boundaries, inbound utterance -> en-IN and outbound reply -> the
caller's locale).
"""
from __future__ import annotations

import re
from typing import Protocol

from .types import Locale


class TranslationProvider(Protocol):
    """IndicTrans2 default (§8). A vendor adapter
    (`saap.plugins.i18n.indictrans2`) is not yet implemented here — the
    model weights aren't downloadable in this environment (Hugging Face
    egress is blocked) — but `ProtectedSpanTranslator` below wraps
    *any* implementation of this protocol, so it's tested against a
    fake and ready to wrap the real adapter once one lands."""

    async def translate(self, text: str, *, source: Locale, target: Locale) -> str: ...


# Matches the vault token format `PIIMaskingInterceptor` mints
# (saap/compliance/pii.py: f"<{entity_type}_{uuid4().hex[:8]}>"), the
# thing this module exists to protect across a language pivot.
DEFAULT_PROTECTED_SPAN_RE = re.compile(r"<[A-Z_]+_[0-9a-f]{8}>")


class ProtectedSpanLost(Exception):
    """A protected span present in the source text did not survive
    translation intact. The masking guarantee that holds pre-translation
    (raw PII never reaches an LLM) must keep holding post-translation;
    silently returning text with a mangled or dropped placeholder would
    quietly break that. Fail closed instead — callers should treat this
    as a translation failure (retry, or route to human transfer per
    Epic 3.4's unsupported-locale rule)."""


class ProtectedSpanTranslator:
    """Wraps a `TranslationProvider` so substrings matching `pattern`
    (PII vault tokens by default) survive translation verbatim.

    NMT models routinely mangle bracket-and-underscore tokens,
    especially translating into a non-Latin script — a vault token
    like `<IN_AADHAAR_a1b2c3d4>` can come back partially transliterated.
    The fix: swap each protected span for a bare numbered sentinel
    (`⟦0⟧`, `⟦1⟧`, ...) before translating — digit sequences tend to
    pass through NMT largely untouched across language pairs — then
    restore the original spans afterward.
    """

    def __init__(
        self,
        provider: TranslationProvider,
        *,
        pattern: re.Pattern[str] = DEFAULT_PROTECTED_SPAN_RE,
    ) -> None:
        self._provider = provider
        self._pattern = pattern

    async def translate(self, text: str, *, source: Locale, target: Locale) -> str:
        distinct_spans = list(dict.fromkeys(self._pattern.findall(text)))
        sentinel_of = {span: f"⟦{i}⟧" for i, span in enumerate(distinct_spans)}

        protected_text = text
        for span, sentinel in sentinel_of.items():
            protected_text = protected_text.replace(span, sentinel)

        translated = await self._provider.translate(protected_text, source=source, target=target)

        restored = translated
        for span, sentinel in sentinel_of.items():
            if sentinel not in restored:
                raise ProtectedSpanLost(
                    f"protected span {span!r} (sentinel {sentinel!r}) did not survive "
                    f"translation {source}->{target}: {translated!r}"
                )
            restored = restored.replace(sentinel, span)
        return restored
