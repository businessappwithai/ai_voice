from tools.license_gate.gate import GateReport, PackageVerdict, _classify, format_text_report

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
