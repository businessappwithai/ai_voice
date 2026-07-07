"""Voice pipeline contracts (Phase 2; architecture Section 7).

VAD -> StreamingSTT -> DialogEngine -> StreamingTTS, each an interface,
each swappable (P3), instrumented with a per-stage latency budget
ledger so the ~500ms voice-to-voice SLO (plan Section 15) is
measurable, not just aspirational.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from .types import Locale


@dataclass(frozen=True)
class VADEvent:
    kind: str  # "speech_start" | "speech_end"
    timestamp_ms: float


class VAD(Protocol):
    """Silero VAD default (MIT, ONNX). Emits speech_start/speech_end
    events from a raw PCM frame stream; a speech_start event arriving
    during TTS playback is what triggers barge-in (early-cancel on the
    LLM token stream + TTS, both already built as cancellable in
    Phase 1's `LLMProvider.stream` contract)."""

    async def process_frame(self, pcm_frame: bytes) -> VADEvent | None: ...


@dataclass(frozen=True)
class STTPartial:
    text: str
    is_final: bool
    confidence: float = 1.0


class StreamingSTT(Protocol):
    """faster-whisper default (CTranslate2, int8). Streams partial
    hypotheses so the dialog engine can start reasoning before the
    speaker finishes; endpointing is VAD's job, not STT's."""

    locale: Locale

    def stream(self, pcm_frames: AsyncIterator[bytes]) -> AsyncIterator[STTPartial]: ...


class StreamingTTS(Protocol):
    """Piper default (MIT, sub-100ms first chunk target). Sentence-level
    chunking so playback can start before the whole reply is
    synthesized; must support cancellation mid-stream for barge-in."""

    locale: Locale

    def synthesize(self, text_stream: AsyncIterator[str]) -> AsyncIterator[bytes]: ...


class DialogEngine(Protocol):
    """Turns one finalized user utterance into a streamed text reply.

    Deliberately opaque to `VoiceSessionRuntime`: a real binding wraps
    whatever already produces chat replies (`ModelRouterLLM` + RAG +
    the L5 compliance chain, Phase 1's `InProcessOrchestrator`, pinned
    to the `fast` model profile per Epic 2.3) so the voice runtime
    doesn't duplicate that wiring or care whether it's in-process
    (`lfx`) or over HTTP.
    """

    def respond(self, utterance: str) -> AsyncIterator[str]: ...


@dataclass(frozen=True)
class LatencyLedger:
    """Per-turn latency budget instrumentation. Plan Section 15's SLO:
    VAD <=60ms, STT partial <=120ms, fast-LLM first token <=150ms, TTS
    first chunk <=90ms -> ~420ms median target, 500ms hard budget.
    Each stage records its own elapsed time; the voice worker publishes
    the total as a Langfuse span and to the Grafana latency-ledger
    dashboard (Phase 2 Epic 2.3's acceptance criterion)."""

    vad_ms: float = 0.0
    stt_partial_ms: float = 0.0
    llm_first_token_ms: float = 0.0
    tts_first_chunk_ms: float = 0.0

    @property
    def total_ms(self) -> float:
        return self.vad_ms + self.stt_partial_ms + self.llm_first_token_ms + self.tts_first_chunk_ms

    def within_slo(self, *, budget_ms: float = 500.0) -> bool:
        return self.total_ms <= budget_ms

    def breakdown(self) -> dict[str, float]:
        return {
            "vad_ms": self.vad_ms,
            "stt_partial_ms": self.stt_partial_ms,
            "llm_first_token_ms": self.llm_first_token_ms,
            "tts_first_chunk_ms": self.tts_first_chunk_ms,
            "total_ms": self.total_ms,
        }
