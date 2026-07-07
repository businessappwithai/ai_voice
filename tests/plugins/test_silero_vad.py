import numpy as np
import pytest
from saap.core.voice import VADEvent
from saap.plugins.voice.silero import FRAME_SAMPLES, SAMPLE_RATE_HZ, SileroVAD

# --- pure state-machine tests (no model, no I/O) ----------------------------


def test_transition_emits_speech_start_on_first_crossing() -> None:
    is_speaking, event = SileroVAD._transition(False, 0.9, 0.5, 32.0)
    assert is_speaking is True
    assert event == VADEvent(kind="speech_start", timestamp_ms=32.0)


def test_transition_emits_speech_end_on_falling_below_threshold() -> None:
    is_speaking, event = SileroVAD._transition(True, 0.1, 0.5, 64.0)
    assert is_speaking is False
    assert event == VADEvent(kind="speech_end", timestamp_ms=64.0)


def test_transition_emits_nothing_while_steady_speaking() -> None:
    is_speaking, event = SileroVAD._transition(True, 0.9, 0.5, 96.0)
    assert is_speaking is True
    assert event is None


def test_transition_emits_nothing_while_steady_silence() -> None:
    is_speaking, event = SileroVAD._transition(False, 0.1, 0.5, 96.0)
    assert is_speaking is False
    assert event is None


def test_transition_respects_custom_threshold() -> None:
    is_speaking, event = SileroVAD._transition(False, 0.6, 0.7, 32.0)
    assert is_speaking is False
    assert event is None


# --- real ONNX model smoke tests (genuine inference, no mocking) -----------


@pytest.fixture(scope="module")
def vad() -> SileroVAD:
    return SileroVAD()


def _silence_frame() -> bytes:
    return np.zeros(FRAME_SAMPLES, dtype=np.int16).tobytes()


async def test_real_model_loads_and_runs_on_silence(vad: SileroVAD) -> None:
    event = await vad.process_frame(_silence_frame())
    # Silence must never trigger speech_start; a fresh VAD starts in the
    # non-speaking state, so silence should produce no event at all.
    assert event is None


async def test_real_model_state_persists_across_frames(vad: SileroVAD) -> None:
    vad.reset()
    for _ in range(5):
        event = await vad.process_frame(_silence_frame())
        assert event is None  # silence throughout stays silent


async def test_real_model_rejects_wrong_frame_size(vad: SileroVAD) -> None:
    bad_frame = np.zeros(FRAME_SAMPLES // 2, dtype=np.int16).tobytes()
    with pytest.raises(ValueError, match="expected 512-sample frames"):
        await vad.process_frame(bad_frame)


async def test_real_model_output_is_valid_probability(vad: SileroVAD) -> None:
    vad.reset()
    # A synthetic tone isn't guaranteed to classify as speech, but the
    # model must still return a well-formed probability in [0, 1] and
    # not raise — this is a genuine inference call, not a mock.
    t = np.linspace(0, FRAME_SAMPLES / SAMPLE_RATE_HZ, FRAME_SAMPLES, endpoint=False)
    tone = (np.sin(2 * np.pi * 200 * t) * 0.5 * 32767).astype(np.int16)
    prob = vad._infer(tone.astype(np.float32) / 32768.0)
    assert 0.0 <= prob <= 1.0
