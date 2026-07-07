"""SileroVAD — VAD implementation over the Silero VAD ONNX model (MIT).

The model file (`models/silero_vad.onnx`) is extracted directly from
the official `silero-vad` PyPI package's wheel rather than depending
on that package itself, which pulls in torch as a hard dependency —
onnxruntime alone is enough to run inference and is a much lighter
production dependency for a voice worker (Phase 2 Epic 2.2).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort
from saap.core.registry import PluginRegistry
from saap.core.voice import VAD, VADEvent

MODEL_PATH = Path(__file__).parent / "models" / "silero_vad.onnx"
SAMPLE_RATE_HZ = 16000
FRAME_SAMPLES = 512  # Silero's required chunk size at 16kHz


class SileroVAD:
    def __init__(
        self,
        *,
        model_path: Path = MODEL_PATH,
        threshold: float = 0.5,
        sample_rate: int = SAMPLE_RATE_HZ,
    ) -> None:
        self._session = ort.InferenceSession(str(model_path))
        self._threshold = threshold
        self._sample_rate = sample_rate
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._is_speaking = False
        self._elapsed_ms = 0.0

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._is_speaking = False
        self._elapsed_ms = 0.0

    def _infer(self, samples: np.ndarray) -> float:
        outputs = self._session.run(
            None,
            {
                "input": samples.reshape(1, -1),
                "state": self._state,
                "sr": np.array(self._sample_rate, dtype=np.int64),
            },
        )
        prob, self._state = outputs
        return float(prob[0][0])

    @staticmethod
    def _transition(
        is_speaking: bool, speech_prob: float, threshold: float, elapsed_ms: float
    ) -> tuple[bool, VADEvent | None]:
        """Pure state-machine step, independent of the ONNX model —
        unit-testable with scripted probabilities rather than requiring
        a real speech sample to exercise the speech_start/speech_end
        transition logic."""
        currently_speaking = speech_prob >= threshold
        event: VADEvent | None = None
        if currently_speaking and not is_speaking:
            event = VADEvent(kind="speech_start", timestamp_ms=elapsed_ms)
        elif not currently_speaking and is_speaking:
            event = VADEvent(kind="speech_end", timestamp_ms=elapsed_ms)
        return currently_speaking, event

    async def process_frame(self, pcm_frame: bytes) -> VADEvent | None:
        samples = np.frombuffer(pcm_frame, dtype=np.int16).astype(np.float32) / 32768.0
        if samples.shape[0] != FRAME_SAMPLES:
            raise ValueError(
                f"expected {FRAME_SAMPLES}-sample frames at {self._sample_rate}Hz, got {samples.shape[0]}"
            )
        speech_prob = self._infer(samples)
        frame_duration_ms = (FRAME_SAMPLES / self._sample_rate) * 1000
        self._elapsed_ms += frame_duration_ms
        self._is_speaking, event = self._transition(
            self._is_speaking, speech_prob, self._threshold, self._elapsed_ms
        )
        return event


def register(registry: PluginRegistry) -> None:
    registry.register(VAD, "silero", lambda: SileroVAD(), license="MIT")
