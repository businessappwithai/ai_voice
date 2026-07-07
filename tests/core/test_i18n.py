from collections.abc import Callable

import pytest
from saap.core.i18n import ProtectedSpanLost, ProtectedSpanTranslator
from saap.core.types import Locale


class FakeTranslationProvider:
    def __init__(self, transform: Callable[[str], str]) -> None:
        self._transform = transform
        self.calls: list[str] = []

    async def translate(self, text: str, *, source: Locale, target: Locale) -> str:
        self.calls.append(text)
        return self._transform(text)


def _tamilize_words(text: str) -> str:
    # Stand-in for a real NMT call: translates the non-sentinel words,
    # leaves anything shaped like `⟦N⟧` untouched (the well-behaved case).
    return text.replace("Book", "பதிவு").replace("for", "க்கு")


async def test_translate_passes_through_text_with_no_protected_spans() -> None:
    provider = FakeTranslationProvider(_tamilize_words)
    translator = ProtectedSpanTranslator(provider)

    result = await translator.translate("Book a table", source=Locale.EN_IN, target=Locale.TA_IN)

    assert result == "பதிவு a table"
    assert provider.calls == ["Book a table"]


async def test_translate_restores_a_single_protected_span() -> None:
    provider = FakeTranslationProvider(_tamilize_words)
    translator = ProtectedSpanTranslator(provider)
    text = "Book <PERSON_a1b2c3d4> for 5pm"

    result = await translator.translate(text, source=Locale.EN_IN, target=Locale.TA_IN)

    assert result == "பதிவு <PERSON_a1b2c3d4> க்கு 5pm"
    # the provider itself must never see the raw placeholder text
    assert "<PERSON_a1b2c3d4>" not in provider.calls[0]
    assert "⟦0⟧" in provider.calls[0]


async def test_translate_restores_multiple_distinct_spans() -> None:
    provider = FakeTranslationProvider(lambda t: t)  # identity NMT
    translator = ProtectedSpanTranslator(provider)
    text = "Book <PERSON_a1b2c3d4>, Aadhaar <IN_AADHAAR_deadbeef>"

    result = await translator.translate(text, source=Locale.EN_IN, target=Locale.HI_IN)

    assert result == text
    assert "⟦0⟧" in provider.calls[0] and "⟦1⟧" in provider.calls[0]


async def test_translate_restores_repeated_occurrences_of_the_same_span() -> None:
    provider = FakeTranslationProvider(lambda t: t)
    translator = ProtectedSpanTranslator(provider)
    text = "<PERSON_a1b2c3d4> called <PERSON_a1b2c3d4> back"

    result = await translator.translate(text, source=Locale.EN_IN, target=Locale.HI_IN)

    assert result == text
    # only one sentinel minted for the repeated span, not two
    assert provider.calls[0].count("⟦0⟧") == 2
    assert "⟦1⟧" not in provider.calls[0]


async def test_translate_raises_protected_span_lost_when_sentinel_dropped() -> None:
    lossy_provider = FakeTranslationProvider(lambda t: t.replace("⟦0⟧", ""))
    translator = ProtectedSpanTranslator(lossy_provider)
    text = "Book <PERSON_a1b2c3d4> for 5pm"

    with pytest.raises(ProtectedSpanLost, match="did not survive"):
        await translator.translate(text, source=Locale.EN_IN, target=Locale.TA_IN)


async def test_translate_raises_protected_span_lost_when_sentinel_corrupted() -> None:
    # Simulates an NMT model mangling the sentinel itself (e.g.
    # transliterating the digit or dropping a bracket) rather than
    # dropping it outright — still must fail closed, not restore into
    # the wrong place or emit corrupted output silently.
    corrupting_provider = FakeTranslationProvider(lambda t: t.replace("⟦0⟧", "0"))
    translator = ProtectedSpanTranslator(corrupting_provider)
    text = "Book <PERSON_a1b2c3d4> for 5pm"

    with pytest.raises(ProtectedSpanLost):
        await translator.translate(text, source=Locale.EN_IN, target=Locale.TA_IN)
