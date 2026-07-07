from dataclasses import dataclass

import numpy as np
from saap.core.types import Locale
from saap.plugins.voice.faster_whisper import FasterWhisperSTT


@dataclass
class FakeSegment:
    text: str


class FakeWhisperModel:
    """Scripted stand-in for faster_whisper.WhisperModel — this
    package's own tests inject a fake model rather than loading real
    ctranslate2 weights (unreachable in this sandbox); the model
    protocol itself (transcribe(audio, language=...) -> (segments, info))
    matches the installed faster-whisper package's real signature."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._i = 0
        self.calls: list[tuple[np.ndarray, str]] = []

    def transcribe(self, audio: np.ndarray, language: str = "en"):
        self.calls.append((audio, language))
        text = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return ([FakeSegment(text=text)] if text else [], object())


async def _frames(n: int, size_bytes: int = 320):
    for _ in range(n):
        yield b"\x00" * size_bytes


async def test_stream_yields_partial_then_final() -> None:
    model = FakeWhisperModel(["hello world"])
    stt = FasterWhisperSTT(model, partial_interval_frames=3)
    partials = [p async for p in stt.stream(_frames(3))]
    # 3 frames with interval=3 -> exactly one partial at frame 3, then
    # the stream-end final re-transcribes the same accumulated buffer.
    assert [p.is_final for p in partials] == [False, True]
    assert all(p.text == "hello world" for p in partials)


async def test_stream_respects_partial_interval() -> None:
    model = FakeWhisperModel(["a", "b", "c"])
    stt = FasterWhisperSTT(model, partial_interval_frames=2)
    partials = [p async for p in stt.stream(_frames(5))]
    # frames 1-2 -> partial "a"; frames 3-4 -> partial "b"; frame 5 left
    # over -> final re-transcribe "c"
    assert [p.text for p in partials] == ["a", "b", "c"]
    assert [p.is_final for p in partials] == [False, False, True]


async def test_stream_skips_empty_transcriptions() -> None:
    # Both the mid-stream partial call and the stream-end final call
    # return empty text — neither should ever be yielded.
    model = FakeWhisperModel(["", ""])
    stt = FasterWhisperSTT(model, partial_interval_frames=1)
    partials = [p async for p in stt.stream(_frames(1))]
    assert partials == []
    assert len(model.calls) == 2  # one partial call, one final call — both empty


async def test_stream_with_no_frames_yields_nothing() -> None:
    model = FakeWhisperModel(["should never be called"])
    stt = FasterWhisperSTT(model, partial_interval_frames=5)
    partials = [p async for p in stt.stream(_frames(0))]
    assert partials == []
    assert model.calls == []


async def test_whisper_lang_strips_region_subtag() -> None:
    model = FakeWhisperModel(["x"])
    stt = FasterWhisperSTT(model, locale=Locale.EN_IN, partial_interval_frames=1)
    async for _ in stt.stream(_frames(1)):
        pass
    assert model.calls[0][1] == "en"


async def test_pcm_to_float32_normalizes_int16_range() -> None:
    model = FakeWhisperModel(["x"])
    stt = FasterWhisperSTT(model)
    pcm = np.array([0, 16384, -16384, 32767, -32768], dtype=np.int16).tobytes()
    floats = stt._pcm_to_float32(pcm)
    assert floats[0] == 0.0
    assert abs(floats[1] - 0.5) < 1e-3
    assert abs(floats[2] - (-0.5)) < 1e-3
    assert floats.max() <= 1.0
    assert floats.min() >= -1.0
