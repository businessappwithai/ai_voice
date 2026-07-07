from pathlib import Path

from tools.eval_harness.harness import (
    ActualOutcome,
    ExpectedToolCall,
    GoldenTranscript,
    evaluate,
    format_report,
    run_suite,
)

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "tools" / "eval_harness" / "examples"


def test_from_dict_parses_turns_and_expectations() -> None:
    transcript = GoldenTranscript.from_dict(
        {
            "id": "t1",
            "description": "desc",
            "turns": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ignored"}],
            "expected": {"contains": ["hello"], "grounded": True},
        }
    )
    assert transcript.user_turns == ("hi",)
    assert transcript.expected_contains == ("hello",)
    assert transcript.expected_grounded is True


def test_from_yaml_loads_example_file() -> None:
    transcript = GoldenTranscript.from_yaml(EXAMPLES_DIR / "dental_hours.yaml")
    assert transcript.id == "dental_hours_basic"
    assert transcript.user_turns == ("What are your office hours?",)
    assert transcript.expected_contains == ("9", "5")
    assert transcript.expected_grounded is True


def test_contains_assertion_passes() -> None:
    transcript = GoldenTranscript(id="t1", description="", user_turns=(), expected_contains=("hours",))
    result = evaluate(transcript, ActualOutcome(final_text="Our hours are 9-5."))
    assert result.passed


def test_contains_assertion_fails() -> None:
    transcript = GoldenTranscript(id="t1", description="", user_turns=(), expected_contains=("phone number",))
    result = evaluate(transcript, ActualOutcome(final_text="Our hours are 9-5."))
    assert not result.passed
    assert result.failures[0].rule == "contains"


def test_not_contains_assertion_fails_when_present() -> None:
    transcript = GoldenTranscript(
        id="t1", description="", user_turns=(), expected_not_contains=("i don't know",)
    )
    result = evaluate(transcript, ActualOutcome(final_text="I don't know the answer."))
    assert not result.passed
    assert result.failures[0].rule == "not_contains"


def test_tool_call_name_and_args_match_passes() -> None:
    transcript = GoldenTranscript(
        id="t1",
        description="",
        user_turns=(),
        expected_tool_calls=(ExpectedToolCall(name="mcp.calendar.book_slot", arguments={"slot_id": "s1"}),),
    )
    actual = ActualOutcome(final_text="booked", tool_calls=(("mcp.calendar.book_slot", {"slot_id": "s1"}),))
    result = evaluate(transcript, actual)
    assert result.passed


def test_tool_call_wrong_name_fails() -> None:
    transcript = GoldenTranscript(
        id="t1", description="", user_turns=(), expected_tool_calls=(ExpectedToolCall(name="mcp.calendar.book_slot"),)
    )
    actual = ActualOutcome(final_text="x", tool_calls=(("mcp.crm.delete_all", {}),))
    result = evaluate(transcript, actual)
    assert not result.passed
    assert result.failures[0].rule == "tool_call_name"


def test_tool_call_wrong_args_fails() -> None:
    transcript = GoldenTranscript(
        id="t1",
        description="",
        user_turns=(),
        expected_tool_calls=(ExpectedToolCall(name="mcp.calendar.book_slot", arguments={"slot_id": "s1"}),),
    )
    actual = ActualOutcome(final_text="x", tool_calls=(("mcp.calendar.book_slot", {"slot_id": "WRONG"}),))
    result = evaluate(transcript, actual)
    assert not result.passed
    assert result.failures[0].rule == "tool_call_args"


def test_tool_call_arguments_none_only_checks_name() -> None:
    transcript = GoldenTranscript(
        id="t1", description="", user_turns=(), expected_tool_calls=(ExpectedToolCall(name="mcp.calendar.book_slot"),)
    )
    actual = ActualOutcome(final_text="x", tool_calls=(("mcp.calendar.book_slot", {"anything": "goes"}),))
    result = evaluate(transcript, actual)
    assert result.passed


def test_tool_call_count_mismatch_fails() -> None:
    transcript = GoldenTranscript(
        id="t1", description="", user_turns=(), expected_tool_calls=(ExpectedToolCall(name="a"), ExpectedToolCall(name="b"))
    )
    actual = ActualOutcome(final_text="x", tool_calls=(("a", {}),))
    result = evaluate(transcript, actual)
    assert not result.passed
    assert result.failures[0].rule == "tool_call_count"


def test_grounded_mismatch_fails() -> None:
    transcript = GoldenTranscript(id="t1", description="", user_turns=(), expected_grounded=True)
    result = evaluate(transcript, ActualOutcome(final_text="x", grounded=False))
    assert not result.passed
    assert result.failures[0].rule == "grounded"


def test_grounded_not_checked_when_transcript_omits_it() -> None:
    transcript = GoldenTranscript(id="t1", description="", user_turns=())
    result = evaluate(transcript, ActualOutcome(final_text="x", grounded=False))
    assert result.passed


async def test_run_suite_loads_all_yaml_files_and_evaluates(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(
        "id: a\ndescription: d\nturns:\n  - role: user\n    content: hi\nexpected:\n  contains: [hello]\n"
    )
    (tmp_path / "b.yaml").write_text(
        "id: b\ndescription: d\nturns:\n  - role: user\n    content: hi\nexpected:\n  contains: [nope]\n"
    )

    async def run_fn(transcript: GoldenTranscript) -> ActualOutcome:
        return ActualOutcome(final_text="hello there")

    results = await run_suite(tmp_path, run_fn)
    assert {r.transcript_id: r.passed for r in results} == {"a": True, "b": False}


def test_format_report_all_passed() -> None:
    from tools.eval_harness.harness import TranscriptResult

    report = format_report([TranscriptResult(transcript_id="a", passed=True)])
    assert "All 1 golden transcripts passed" in report


def test_format_report_with_failures() -> None:
    from tools.eval_harness.harness import AssertionFailure, TranscriptResult

    report = format_report(
        [TranscriptResult(transcript_id="a", passed=False, failures=[AssertionFailure("contains", "missing x")])]
    )
    assert "FAIL a" in report
    assert "missing x" in report
    assert "1/1 golden transcripts failed" in report
