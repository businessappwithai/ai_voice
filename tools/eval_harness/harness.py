"""Golden-transcript eval harness (plan Phase 1 Epic 1.6; architecture
Section 15). Replays a YAML golden transcript against whatever runs a
flow — a `FakeLangflowRuntime` in unit tests, or a real staging
runtime in CI's eval-gate job — and checks hard assertions on the
final response text, tool calls, and grounding.

The harness itself is runtime-agnostic: `evaluate()` only compares a
`GoldenTranscript`'s expectations against an `ActualOutcome` the
*caller* produced by actually driving a flow. This keeps the
assertion logic (and its tests) independent of whether a real
Langflow deployment is reachable.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ExpectedToolCall:
    name: str
    arguments: dict[str, Any] | None = None  # None = check name/order only, not args


@dataclass(frozen=True)
class GoldenTranscript:
    id: str
    description: str
    user_turns: tuple[str, ...]
    expected_contains: tuple[str, ...] = ()
    expected_not_contains: tuple[str, ...] = ()
    expected_tool_calls: tuple[ExpectedToolCall, ...] = ()
    expected_grounded: bool | None = None

    @classmethod
    def from_yaml(cls, path: Path) -> GoldenTranscript:
        data = yaml.safe_load(path.read_text())
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoldenTranscript:
        turns = tuple(t["content"] for t in data.get("turns", []) if t.get("role") == "user")
        expected = data.get("expected", {})
        tool_calls = tuple(
            ExpectedToolCall(name=tc["name"], arguments=tc.get("arguments"))
            for tc in expected.get("tool_calls", [])
        )
        return cls(
            id=data["id"],
            description=data.get("description", ""),
            user_turns=turns,
            expected_contains=tuple(expected.get("contains", [])),
            expected_not_contains=tuple(expected.get("not_contains", [])),
            expected_tool_calls=tool_calls,
            expected_grounded=expected.get("grounded"),
        )


@dataclass(frozen=True)
class AssertionFailure:
    rule: str
    message: str


@dataclass
class TranscriptResult:
    transcript_id: str
    passed: bool
    failures: list[AssertionFailure] = field(default_factory=list)


@dataclass(frozen=True)
class ActualOutcome:
    """What a replay run actually produced. Gathered by whatever drives
    the flow (fake or real); the harness only compares this against
    the transcript's expectations."""

    final_text: str
    tool_calls: tuple[tuple[str, dict[str, Any]], ...] = ()
    grounded: bool | None = None


def evaluate(transcript: GoldenTranscript, actual: ActualOutcome) -> TranscriptResult:
    failures: list[AssertionFailure] = []

    for substr in transcript.expected_contains:
        if substr.lower() not in actual.final_text.lower():
            failures.append(AssertionFailure("contains", f"expected response to contain {substr!r}"))

    for substr in transcript.expected_not_contains:
        if substr.lower() in actual.final_text.lower():
            failures.append(AssertionFailure("not_contains", f"response must not contain {substr!r}"))

    if transcript.expected_tool_calls:
        if len(actual.tool_calls) != len(transcript.expected_tool_calls):
            failures.append(
                AssertionFailure(
                    "tool_call_count",
                    f"expected {len(transcript.expected_tool_calls)} tool call(s), "
                    f"got {len(actual.tool_calls)}",
                )
            )
        else:
            for i, (expected_call, actual_call) in enumerate(
                zip(transcript.expected_tool_calls, actual.tool_calls, strict=True)
            ):
                actual_name, actual_args = actual_call
                if actual_name != expected_call.name:
                    failures.append(
                        AssertionFailure(
                            "tool_call_name",
                            f"call {i}: expected tool {expected_call.name!r}, got {actual_name!r}",
                        )
                    )
                elif expected_call.arguments is not None and actual_args != expected_call.arguments:
                    failures.append(
                        AssertionFailure(
                            "tool_call_args",
                            f"call {i}: expected args {expected_call.arguments}, got {actual_args}",
                        )
                    )

    if transcript.expected_grounded is not None and actual.grounded != transcript.expected_grounded:
        failures.append(
            AssertionFailure(
                "grounded", f"expected grounded={transcript.expected_grounded}, got {actual.grounded}"
            )
        )

    return TranscriptResult(transcript_id=transcript.id, passed=not failures, failures=failures)


RunFn = Callable[[GoldenTranscript], Awaitable[ActualOutcome]]


async def run_suite(transcripts_dir: Path, run_fn: RunFn) -> list[TranscriptResult]:
    """Loads every `*.yaml` transcript in `transcripts_dir`, drives it
    through `run_fn` (supplied by the caller — this is the seam a
    staging Langflow runtime plugs into), and evaluates the result.
    Sorted by filename so a suite's pass/fail order is deterministic."""
    results = []
    # Blocking glob is fine here: run_suite is a one-shot CI/CLI batch
    # job, not a request handler sharing an event loop with other work.
    for path in sorted(transcripts_dir.glob("*.yaml")):  # noqa: ASYNC240
        transcript = GoldenTranscript.from_yaml(path)
        actual = await run_fn(transcript)
        results.append(evaluate(transcript, actual))
    return results


def format_report(results: list[TranscriptResult]) -> str:
    lines = []
    failed = [r for r in results if not r.passed]
    for result in failed:
        lines.append(f"FAIL {result.transcript_id}")
        for failure in result.failures:
            lines.append(f"  [{failure.rule}] {failure.message}")
    if not failed:
        lines.append(f"All {len(results)} golden transcripts passed.")
    else:
        lines.append(f"{len(failed)}/{len(results)} golden transcripts failed.")
    return "\n".join(lines)
