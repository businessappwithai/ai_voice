"""FasterWhisperSTT — StreamingSTT over faster-whisper (CTranslate2,
int8 quantized). License: MIT.

faster-whisper's `transcribe()` is a synchronous, batch call (not
natively streaming) — this adapter buffers incoming PCM frames and
re-transcribes the accumulated buffer every `partial_interval_frames`
frames, running the blocking call in a thread executor so it never
blocks the event loop. Partials are marked `is_final=False`; when the
caller's frame iterator ends (VAD has signaled utterance end), the
buffer is transcribed one last time and re-emitted with
`is_final=True`.

CAVEAT: no model weights are bundled or downloadable in this sandbox
(Hugging Face is unreachable through the egress proxy here), so this
adapter is implemented against faster-whisper's documented API
(verified via `inspect.signature` against the installed package) and
unit-tested with an injected fake model — it has NOT been exercised
against a real model/real audio in this environment. Wire a real
`model_size_or_path` in a deployment where model downloads are
reachable before relying on this in production.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from typing import Any, Protocol

import numpy as np
from saap.core.registry import PluginRegistry
from saap.core.types import Locale
from saap.core.voice import StreamingSTT, STTPartial


class TranscribedSegment(Protocol):
    text: str


class WhisperModelProtocol(Protocol):
    """Structural stand-in for `faster_whisper.WhisperModel`, narrowed
    to the one method this adapter calls, so tests can inject a fake
    without needing the real ctranslate2 model loaded."""

    def transcribe(
        self, audio: np.ndarray, **kwargs: Any
    ) -> tuple[Iterable[TranscribedSegment], Any]: ...


class FasterWhisperSTT:
    def __init__(
        self,
        model: WhisperModelProtocol,
        *,
        locale: Locale = Locale.EN_IN,
        sample_rate: int = 16000,
        partial_interval_frames: int = 10,
    ) -> None:
        self.locale = locale
        self._model = model
        self._sample_rate = sample_rate
        self._partial_interval_frames = partial_interval_frames

    def _pcm_to_float32(self, buffer: bytes) -> np.ndarray:
        return np.frombuffer(buffer, dtype=np.int16).astype(np.float32) / 32768.0

    def _whisper_lang(self) -> str:
        # Locale is BCP-47 (e.g. "en-IN"); faster-whisper wants a bare
        # ISO-639-1 code (e.g. "en").
        return self.locale.value.split("-")[0]

    async def _transcribe_buffer(self, buffer: bytes) -> str:
        audio = self._pcm_to_float32(buffer)
        loop = asyncio.get_event_loop()
        segments, _info = await loop.run_in_executor(
            None, lambda: self._model.transcribe(audio, language=self._whisper_lang())
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    async def stream(self, pcm_frames: AsyncIterator[bytes]) -> AsyncIterator[STTPartial]:
        buffer = bytearray()
        frames_since_partial = 0
        async for frame in pcm_frames:
            buffer.extend(frame)
            frames_since_partial += 1
            if frames_since_partial >= self._partial_interval_frames:
                text = await self._transcribe_buffer(bytes(buffer))
                frames_since_partial = 0
                if text:
                    yield STTPartial(text=text, is_final=False)
        if buffer:
            text = await self._transcribe_buffer(bytes(buffer))
            if text:
                yield STTPartial(text=text, is_final=True)


def register(registry: PluginRegistry) -> None:
    def _factory() -> FasterWhisperSTT:
        from faster_whisper import WhisperModel

        model = WhisperModel("small", device="cpu", compute_type="int8")
        return FasterWhisperSTT(model)

    registry.register(StreamingSTT, "faster_whisper", _factory, license="MIT")
