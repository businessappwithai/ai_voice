from collections.abc import AsyncIterator

from saap.core.types import Locale
from saap.core.voice import STTPartial, VADEvent
from saap.voice.session_runtime import VoiceSessionRuntime


class ScriptedVAD:
    def __init__(self, events: list[VADEvent | None]) -> None:
        self._events = events
        self._i = 0

    async def process_frame(self, pcm_frame: bytes) -> VADEvent | None:
        event = self._events[self._i] if self._i < len(self._events) else None
        self._i += 1
        return event


class ScriptedSTT:
    locale = Locale.EN_IN

    def __init__(self, partials: list[STTPartial]) -> None:
        self._partials = partials
        self.frames_seen = 0

    async def stream(self, pcm_frames: AsyncIterator[bytes]) -> AsyncIterator[STTPartial]:
        async for _ in pcm_frames:
            self.frames_seen += 1
        for partial in self._partials:
            yield partial


class ScriptedDialogEngine:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self.calls: list[str] = []

    async def respond(self, utterance: str) -> AsyncIterator[str]:
        self.calls.append(utterance)
        for token in self._tokens:
            yield token


class EchoTTS:
    locale = Locale.EN_IN

    async def synthesize(self, text_stream: AsyncIterator[str]) -> AsyncIterator[bytes]:
        async for token in text_stream:
            yield token.encode()


async def _frames(n: int) -> AsyncIterator[bytes]:
    for _ in range(n):
        yield b"\x00" * 32


async def test_run_turn_produces_audio_and_records_ledger() -> None:
    vad = ScriptedVAD([VADEvent(kind="speech_start", timestamp_ms=0.0), None, None])
    stt = ScriptedSTT([STTPartial(text="Hel", is_final=False), STTPartial(text="Hello", is_final=True)])
    dialog = ScriptedDialogEngine(["Hi ", "there "])
    tts = EchoTTS()
    runtime = VoiceSessionRuntime(vad, stt, tts, dialog)

    chunks = [c async for c in runtime.run_turn(_frames(3))]

    assert chunks == [b"Hi ", b"there "]
    assert dialog.calls == ["Hello"]
    assert runtime.is_speaking is False
    assert runtime.last_ledger.total_ms >= 0.0
    assert runtime.last_ledger.within_slo(budget_ms=5000.0)


async def test_run_turn_yields_nothing_when_stt_never_finalizes() -> None:
    vad = ScriptedVAD([None, None])
    stt = ScriptedSTT([STTPartial(text="uh", is_final=False)])
    dialog = ScriptedDialogEngine(["should not be called"])
    tts = EchoTTS()
    runtime = VoiceSessionRuntime(vad, stt, tts, dialog)

    chunks = [c async for c in runtime.run_turn(_frames(2))]

    assert chunks == []
    assert dialog.calls == []
    assert runtime.is_speaking is False


async def test_run_turn_yields_nothing_for_blank_final_transcript() -> None:
    vad = ScriptedVAD([None])
    stt = ScriptedSTT([STTPartial(text="   ", is_final=True)])
    dialog = ScriptedDialogEngine(["should not be called"])
    tts = EchoTTS()
    runtime = VoiceSessionRuntime(vad, stt, tts, dialog)

    chunks = [c async for c in runtime.run_turn(_frames(1))]

    assert chunks == []
    assert dialog.calls == []


async def test_barge_in_stops_audio_mid_stream() -> None:
    vad = ScriptedVAD([None])
    stt = ScriptedSTT([STTPartial(text="Book a table", is_final=True)])
    dialog = ScriptedDialogEngine(["Sure, ", "what ", "time ", "works?"])
    tts = EchoTTS()
    runtime = VoiceSessionRuntime(vad, stt, tts, dialog)

    chunks: list[bytes] = []
    agen = runtime.run_turn(_frames(1))
    async for chunk in agen:
        chunks.append(chunk)
        assert runtime.is_speaking is True
        if len(chunks) == 1:
            runtime.notify_barge_in()

    assert chunks == [b"Sure, "]
    assert runtime.is_speaking is False


async def test_notify_barge_in_is_a_no_op_when_not_speaking() -> None:
    vad = ScriptedVAD([None])
    stt = ScriptedSTT([STTPartial(text="hello", is_final=True)])
    dialog = ScriptedDialogEngine(["Hi ", "there "])
    tts = EchoTTS()
    runtime = VoiceSessionRuntime(vad, stt, tts, dialog)

    runtime.notify_barge_in()  # before any turn has started speaking

    chunks = [c async for c in runtime.run_turn(_frames(1))]

    assert chunks == [b"Hi ", b"there "]
