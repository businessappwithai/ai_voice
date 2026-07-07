from saap.core.voice import LatencyLedger


def test_total_ms_sums_all_stages() -> None:
    ledger = LatencyLedger(vad_ms=50, stt_partial_ms=100, llm_first_token_ms=140, tts_first_chunk_ms=80)
    assert ledger.total_ms == 370


def test_within_slo_true_under_budget() -> None:
    ledger = LatencyLedger(vad_ms=50, stt_partial_ms=100, llm_first_token_ms=140, tts_first_chunk_ms=80)
    assert ledger.within_slo() is True


def test_within_slo_false_over_budget() -> None:
    ledger = LatencyLedger(vad_ms=100, stt_partial_ms=200, llm_first_token_ms=300, tts_first_chunk_ms=100)
    assert ledger.within_slo() is False


def test_within_slo_respects_custom_budget() -> None:
    ledger = LatencyLedger(vad_ms=50, stt_partial_ms=100, llm_first_token_ms=140, tts_first_chunk_ms=80)
    assert ledger.within_slo(budget_ms=300) is False
    assert ledger.within_slo(budget_ms=400) is True


def test_breakdown_reports_all_stages_and_total() -> None:
    ledger = LatencyLedger(vad_ms=10, stt_partial_ms=20, llm_first_token_ms=30, tts_first_chunk_ms=40)
    assert ledger.breakdown() == {
        "vad_ms": 10,
        "stt_partial_ms": 20,
        "llm_first_token_ms": 30,
        "tts_first_chunk_ms": 40,
        "total_ms": 100,
    }


def test_default_ledger_is_zero() -> None:
    ledger = LatencyLedger()
    assert ledger.total_ms == 0
    assert ledger.within_slo() is True
