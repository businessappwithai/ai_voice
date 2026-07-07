"""PiperTTS — StreamingTTS adapter shape for Piper, the architecture's
intended commercial-default TTS engine (Coqui XTTS-v2's weights are
non-commercial and flagged "restricted" by LicenseGate).

**License finding — the `piper-tts` PyPI package is NOT a safe direct
dependency under P1, and this module does not depend on it:**

  * `piper-tts>=1.3.0` ships from `OHF-voice/piper1-gpl` and is
    licensed **GPL-3.0-or-later** (confirmed via package metadata: `pip
    show piper-tts` reports `License: GPL-3.0-or-later`,
    `Home-page: http://github.com/OHF-voice/piper1-gpl`). LicenseGate
    correctly flags this as unclassified/denied — it is not on the
    allow list and should not be added to it.
  * `piper-tts<=1.2.0` (the older `rhasspy/piper` lineage) declares
    itself MIT, but its runtime dependency `piper-phonemize~=1.1.0`
    bundles a *compiled* `libespeak-ng.so` inside the wheel.
    `espeak-ng` itself is GPL-3.0 upstream — distributing a binary
    that links it is a GPL-covered work regardless of the wrapper
    package's own MIT label. This is almost certainly the actual
    reason for the 1.3.0 relicensing: the OHF-voice fork is being
    honest about a license entanglement the older package's metadata
    obscured. Pinning to the "MIT" 1.2.0 release would not actually
    fix the P1 violation, only hide it.

This is a real instance of the license-drift pattern the plan calls
out for Redis/Valkey (Section 16) — caught here by actually reading
`pip show`'s output and the bundled LICENSE files rather than trusting
a classifier string.

**The clean path**, not yet implemented, is the same "separate
process" boundary the architecture already accepts for FreeSWITCH/
Asterisk (both GPL-licensed telephony infra, invoked as external
services, never linked into SAAP's own Python packaging): run Piper's
VITS model directly via `onnxruntime` (genuinely fine — the model
weights and onnxruntime itself carry no such entanglement), and
phonemize text by shelling out to a separately-installed system
`espeak-ng` binary via subprocess — arms-length invocation of a GPL
program, not a linked dependency of this package. That phoneme-ID
mapping is specific to how Piper's training pipeline encodes espeak-ng
output and isn't documented outside Piper's own source; hand-rolling
it here without a way to verify against real audio (no model download
and no `espeak-ng` binary are available in this sandbox) risks
shipping something that looks plausible but is silently wrong, which
is worse than leaving it undone. `register()` below raises rather than
pretending this works.

`PiperTTS` and `_iter_in_thread` themselves have no license issue and
stay as-is: PiperTTS is a generic adapter over anything satisfying
`PiperVoiceProtocol` (`synthesize(text) -> Iterable[chunk w/
.audio_int16_bytes]`), and `_iter_in_thread` bridges a synchronous,
blocking generator onto the event loop by running it in a background
thread and forwarding each chunk through a queue as it's produced, so
the first audio chunk is yielded as soon as it's synthesized rather
than after the whole sentence finishes (the sub-100ms first-chunk
target depends on this, not on buffering the full utterance). Both
are exercised in tests against an injected fake voice.
"""
from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import AsyncIterator, Iterable
from typing import Protocol

from saap.core.registry import PluginRegistry
from saap.core.types import Locale

_SENTINEL = object()


class SynthesizedChunk(Protocol):
    audio_int16_bytes: bytes


class PiperVoiceProtocol(Protocol):
    """Structural stand-in for `piper.PiperVoice`, narrowed to the one
    method this adapter calls."""

    def synthesize(self, text: str) -> Iterable[SynthesizedChunk]: ...


async def _iter_in_thread(sync_iter: Iterable[SynthesizedChunk]) -> AsyncIterator[SynthesizedChunk]:
    q: queue.Queue = queue.Queue()

    def worker() -> None:
        try:
            for item in sync_iter:
                q.put(item)
        finally:
            q.put(_SENTINEL)

    loop = asyncio.get_event_loop()
    threading.Thread(target=worker, daemon=True).start()
    while True:
        item = await loop.run_in_executor(None, q.get)
        if item is _SENTINEL:
            break
        yield item


class PiperTTS:
    def __init__(self, voice: PiperVoiceProtocol, *, locale: Locale = Locale.EN_IN) -> None:
        self.locale = locale
        self._voice = voice

    async def synthesize(self, text_stream: AsyncIterator[str]) -> AsyncIterator[bytes]:
        async for sentence in text_stream:
            if not sentence.strip():
                continue
            async for chunk in _iter_in_thread(self._voice.synthesize(sentence)):
                yield chunk.audio_int16_bytes


def register(registry: PluginRegistry) -> None:
    """Deliberately does not bind a working factory — see the module
    docstring. Registering under license="MIT" would be a false
    LicenseGate declaration for a dependency chain that is actually
    GPL-3.0-or-later (or GPL-entangled); raising here instead of
    quietly reaching for the `piper` package makes that impossible to
    do by accident. A real binding requires the onnxruntime + arms-
    length espeak-ng subprocess bridge described above, supplied by
    the deployment, not by this module importing a PyPI package."""
    raise NotImplementedError(
        "no license-clean PiperTTS factory is wired yet — see "
        "saap/plugins/voice/piper/__init__.py's module docstring. "
        "Construct PiperTTS(your_voice) directly with a voice object "
        "you have separately verified the licensing/provenance of."
    )
