"""VoiceSessionRuntime — Phase 2 Epic 2.3: assembles VAD -> StreamingSTT
-> DialogEngine -> StreamingTTS for one voice turn, instrumenting each
stage transition into a `LatencyLedger` and supporting barge-in.

This is the turn-taking and latency-ledger half of the plan's
"VoicePipelineFactory" — pure asyncio orchestration over the Phase 2
protocols, fully testable with fakes. It deliberately does NOT include
the LiveKit Agents worker or telephony transport itself: there is no
SIP trunk, LiveKit server, or GPU reachable in this environment to
verify that half against, so it is left for the deployment that has
them (see README's status table).

Barge-in model: `notify_barge_in()` is a cooperative signal, checked
between yields of the dialog-token stream and the TTS-chunk stream.
This works regardless of what backs `DialogEngine` (a raw
`LLMProvider.stream`, or an in-process Langflow run) without the
runtime needing a handle on its underlying task. A binding that wants
harder, mid-token-wait cancellation (e.g. wrapping
`InProcessOrchestrator`, whose `cancel(run_id)` calls `Task.cancel()`
directly) can additionally cancel its own task when `is_speaking` flips
back to `False` mid-flight.
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator

from saap.core.voice import VAD, DialogEngine, LatencyLedger, StreamingSTT, StreamingTTS


class VoiceSessionRuntime:
    def __init__(self, vad: VAD, stt: StreamingSTT, tts: StreamingTTS, dialog: DialogEngine) -> None:
        self._vad = vad
        self._stt = stt
        self._tts = tts
        self._dialog = dialog
        self._speaking = False
        self._barge_in = False
        self.last_ledger = LatencyLedger()

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def notify_barge_in(self) -> None:
        """Call when VAD on the caller's inbound stream reports
        speech_start while `is_speaking` is True. Takes effect at the
        next dialog token / TTS chunk boundary, not mid-frame."""
        if self._speaking:
            self._barge_in = True

    async def run_turn(self, pcm_frames: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        """One listen -> think -> speak turn. Yields synthesized audio
        chunks as they're produced; `self.last_ledger` holds the
        latency breakdown, updated as each stage completes (so a
        caller can publish partial ledgers to Grafana without waiting
        for the whole turn to finish)."""
        t0 = time.monotonic()
        vad_ms = 0.0
        stt_partial_ms = 0.0
        vad_seen = False
        stt_seen = False

        async def frames_with_vad() -> AsyncIterator[bytes]:
            nonlocal vad_ms, vad_seen
            async for frame in pcm_frames:
                event = await self._vad.process_frame(frame)
                if event is not None and event.kind == "speech_start" and not vad_seen:
                    vad_ms = (time.monotonic() - t0) * 1000
                    vad_seen = True
                yield frame

        utterance = ""
        async for partial in self._stt.stream(frames_with_vad()):
            if not stt_seen:
                stt_partial_ms = (time.monotonic() - t0) * 1000 - vad_ms
                stt_seen = True
            if partial.is_final:
                utterance = partial.text

        self.last_ledger = LatencyLedger(vad_ms=vad_ms, stt_partial_ms=stt_partial_ms)
        if not utterance.strip():
            return

        self._speaking = True
        self._barge_in = False
        t_stt_done = time.monotonic()
        llm_first_token_ms = 0.0
        llm_seen = False
        tts_first_chunk_ms = 0.0
        tts_seen = False

        try:
            async def dialog_tokens() -> AsyncIterator[str]:
                nonlocal llm_first_token_ms, llm_seen
                async for token in self._dialog.respond(utterance):
                    if self._barge_in:
                        return
                    if not llm_seen:
                        llm_first_token_ms = (time.monotonic() - t_stt_done) * 1000
                        llm_seen = True
                    yield token

            async for chunk in self._tts.synthesize(dialog_tokens()):
                if self._barge_in:
                    break
                if not tts_seen:
                    t_llm_first_token = t_stt_done + llm_first_token_ms / 1000
                    tts_first_chunk_ms = (time.monotonic() - t_llm_first_token) * 1000
                    tts_seen = True
                self.last_ledger = LatencyLedger(
                    vad_ms=vad_ms,
                    stt_partial_ms=stt_partial_ms,
                    llm_first_token_ms=llm_first_token_ms,
                    tts_first_chunk_ms=tts_first_chunk_ms,
                )
                yield chunk
        finally:
            self._speaking = False
            self.last_ledger = LatencyLedger(
                vad_ms=vad_ms,
                stt_partial_ms=stt_partial_ms,
                llm_first_token_ms=llm_first_token_ms,
                tts_first_chunk_ms=tts_first_chunk_ms,
            )
