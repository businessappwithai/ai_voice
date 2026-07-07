from dataclasses import dataclass

import pytest
from saap.core.registry import PluginRegistry
from saap.plugins.voice.piper import PiperTTS, register


@dataclass
class FakeAudioChunk:
    audio_int16_bytes: bytes


class FakeVoice:
    """Scripted stand-in for piper.PiperVoice — real voice models
    (.onnx) aren't downloadable in this sandbox (Hugging Face is
    unreachable), so this test injects a fake rather than loading real
    weights. The protocol (synthesize(text) -> Iterable[chunk with
    .audio_int16_bytes]) matches the installed piper-tts package's
    real API."""

    def __init__(self, chunks_per_call: list[bytes]) -> None:
        self._chunks_per_call = chunks_per_call
        self.calls: list[str] = []

    def synthesize(self, text: str):
        self.calls.append(text)
        for chunk_bytes in self._chunks_per_call:
            yield FakeAudioChunk(audio_int16_bytes=chunk_bytes)


async def _text_stream(*sentences: str):
    for s in sentences:
        yield s


async def test_synthesize_yields_audio_bytes_per_sentence() -> None:
    voice = FakeVoice([b"chunk1", b"chunk2"])
    tts = PiperTTS(voice)
    audio_chunks = [c async for c in tts.synthesize(_text_stream("Hello there."))]
    assert audio_chunks == [b"chunk1", b"chunk2"]
    assert voice.calls == ["Hello there."]


async def test_synthesize_processes_multiple_sentences_in_order() -> None:
    voice = FakeVoice([b"x"])
    tts = PiperTTS(voice)
    audio_chunks = [c async for c in tts.synthesize(_text_stream("First.", "Second."))]
    assert audio_chunks == [b"x", b"x"]
    assert voice.calls == ["First.", "Second."]


async def test_synthesize_skips_blank_sentences() -> None:
    voice = FakeVoice([b"x"])
    tts = PiperTTS(voice)
    audio_chunks = [c async for c in tts.synthesize(_text_stream("", "   ", "Real text."))]
    assert audio_chunks == [b"x"]
    assert voice.calls == ["Real text."]


async def test_synthesize_with_empty_stream_yields_nothing() -> None:
    voice = FakeVoice([b"x"])
    tts = PiperTTS(voice)
    audio_chunks = [c async for c in tts.synthesize(_text_stream())]
    assert audio_chunks == []
    assert voice.calls == []


async def test_synthesize_handles_voice_yielding_no_chunks() -> None:
    voice = FakeVoice([])
    tts = PiperTTS(voice)
    audio_chunks = [c async for c in tts.synthesize(_text_stream("Silence test."))]
    assert audio_chunks == []
    assert voice.calls == ["Silence test."]


def test_register_refuses_to_bind_a_license_unclean_factory() -> None:
    # register() must not silently pull in the GPL-entangled piper-tts
    # package under a false "MIT" license declaration (see module
    # docstring) — it should fail loudly instead.
    registry = PluginRegistry()
    with pytest.raises(NotImplementedError, match="license-clean"):
        register(registry)
