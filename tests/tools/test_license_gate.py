from tools.license_gate.gate import (
    DEFAULT_POLICY,
    GateReport,
    PackageVerdict,
    _classify,
    format_text_report,
)

POLICY = {
    "allow": ["MIT", "Apache-2.0"],
    "review": ["LGPL"],
    "deny": ["BUSL-1.1", "RSALv2"],
    "known_overrides": {"weird-pkg": "verified upstream MIT, PyPI metadata missing"},
}


def test_classify_allow() -> None:
    verdict, reason = _classify("foo", "MIT License", POLICY)
    assert verdict == "allow"


def test_classify_deny() -> None:
    verdict, reason = _classify("redis", "RSALv2", POLICY)
    assert verdict == "deny"


def test_classify_review() -> None:
    verdict, reason = _classify("foo", "GNU Lesser General Public License v3 (LGPLv3)", POLICY)
    assert verdict == "review"


def test_classify_unknown() -> None:
    verdict, reason = _classify("foo", "SomeWeirdLicense", POLICY)
    assert verdict == "unknown"


def test_classify_unknown_license_metadata() -> None:
    verdict, reason = _classify("foo", "UNKNOWN", POLICY)
    assert verdict == "unknown"


def test_known_override_forces_allow() -> None:
    verdict, reason = _classify("weird-pkg", "UNKNOWN", POLICY)
    assert verdict == "allow"
    assert "known_override" in reason


def test_deny_takes_precedence_over_allow_substring_collision() -> None:
    # A license string containing both an allow and deny substring must
    # deny — P1 is fail-closed, not "first match wins by list order
    # coincidence." (deny is checked before allow in _classify)
    policy = {"allow": ["Public License"], "review": [], "deny": ["Business Source"], "known_overrides": {}}
    verdict, _ = _classify("foo", "Business Source Public License", policy)
    assert verdict == "deny"


def test_gate_report_passed_false_when_denied() -> None:
    report = GateReport(
        verdicts=[PackageVerdict(name="redis", version="7.4", license="RSALv2", verdict="deny")]
    )
    assert report.passed is False
    assert len(report.denied) == 1


def test_gate_report_passed_true_with_only_review() -> None:
    report = GateReport(
        verdicts=[PackageVerdict(name="foo", version="1.0", license="LGPL", verdict="review")]
    )
    assert report.passed is True


def test_format_text_report_lists_denials() -> None:
    report = GateReport(
        verdicts=[PackageVerdict(name="redis", version="7.4", license="RSALv2", verdict="deny", reason="x")]
    )
    text = format_text_report(report, strict=False)
    assert "DENIED" in text
    assert "redis" in text


def test_format_text_report_all_clear() -> None:
    report = GateReport(
        verdicts=[PackageVerdict(name="foo", version="1.0", license="MIT", verdict="allow")]
    )
    text = format_text_report(report, strict=False)
    assert "passed LicenseGate" in text


def test_default_policy_denies_gpl3_piper_style_license() -> None:
    # Regression test for the piper-tts>=1.3.0 finding (GPL-3.0-or-later,
    # github.com/OHF-voice/piper1-gpl) — see
    # saap/plugins/voice/piper/__init__.py's module docstring. A future
    # re-add of that dependency must fail the build, not land in the
    # non-blocking "unknown" bucket.
    verdict, reason = _classify("piper-tts", "GPL-3.0-or-later", DEFAULT_POLICY)
    assert verdict == "deny"


def test_default_policy_still_reviews_lgpl_not_caught_by_new_gpl_denial() -> None:
    # "GNU Lesser General Public License" must not collide with the
    # "GNU General Public License" deny-list substring added alongside
    # the piper-tts finding.
    verdict, reason = _classify(
        "foo", "GNU Lesser General Public License v3 (LGPLv3)", DEFAULT_POLICY
    )
    assert verdict == "review"


def test_default_policy_allows_apache_license_2_0_license_field_variant() -> None:
    # Regression test for a real finding: `multidict`'s License field
    # is literally "Apache License 2.0" — not a substring of any of
    # "Apache-2.0" / "Apache 2.0" / "Apache Software License", so it
    # landed in the non-blocking "unknown" bucket until this entry was
    # added, despite being genuinely Apache-2.0 (verified via the
    # wheel's bundled LICENSE file).
    verdict, reason = _classify("multidict", "Apache License 2.0", DEFAULT_POLICY)
    assert verdict == "allow"


def test_default_policy_allows_matrix_nio_style_isc_license_field() -> None:
    # matrix-nio's License field is the full LICENSE file text, which
    # starts with "Internet Systems Consortium license" rather than
    # the bare acronym "ISC" — not a substring match against the
    # existing "ISC" entry, so this needed its own allow-list entry.
    verdict, reason = _classify(
        "matrix-nio", "Internet Systems Consortium license\n===...", DEFAULT_POLICY
    )
    assert verdict == "allow"
