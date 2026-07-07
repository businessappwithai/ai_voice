"""LicenseGate — CI enforcement of P1 (open source only).

Scans every installed distribution's declared license metadata against
an allow/review/deny policy and fails the build on anything not
explicitly allowed. This is the mechanical enforcement the plan calls
for landing *first*, before any other Phase-0 work: "P1 is an
architectural property, not a legal footnote."

Usage:
    python -m tools.license_gate.gate                 # scan installed env
    python -m tools.license_gate.gate --policy custom.yaml
    python -m tools.license_gate.gate --json           # machine-readable report

Exit codes: 0 = all packages allowed. 1 = one or more denials
(or unclassified packages under strict mode). Packages on the "review"
list are reported but do not fail the build — they require a human
sign-off tracked outside CI (see the plan's quarterly re-scan cadence).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from importlib.metadata import Distribution, distributions
from pathlib import Path

import yaml

DEFAULT_POLICY_PATH = Path(__file__).parent / "policy.yaml"

# Fallback policy if no YAML file is found (keeps the tool usable
# standalone, e.g. from a one-off shell). The registry's
# DEFAULT_ALLOWED_LICENSES should stay in sync with `allow` here.
DEFAULT_POLICY: dict = {
    "allow": ["MIT", "Apache-2.0", "Apache 2.0", "Apache License 2.0", "Apache Software License",
              "Internet Systems Consortium", "BSD", "MPL-2.0",
              "Mozilla Public License 2.0 (MPL 2.0)", "PostgreSQL", "AGPL-3.0",
              "GNU Affero General Public License v3", "ISC", "PSF", "Python Software Foundation",
              "The Unlicense (Unlicense)"],
    "review": ["LGPL", "GNU Lesser General Public License", "SUL-1.0"],
    "deny": ["BUSL-1.1", "Business Source License", "RSALv2", "Server Side Public License",
             "SSPL", "Commons Clause", "Proprietary", "GPL-2.0", "GPL-3.0",
             "GNU General Public License"],
    # Packages whose PyPI classifier is missing/ambiguous but whose real
    # license is verified out-of-band. Each entry documents WHY.
    "known_overrides": {
        "setuptools": "PSF/MIT-equivalent; PyPI metadata omits the classifier for this bootstrap package",
    },
}


@dataclass
class PackageVerdict:
    name: str
    version: str
    license: str
    verdict: str  # "allow" | "review" | "deny" | "unknown"
    reason: str = ""


@dataclass
class GateReport:
    verdicts: list[PackageVerdict] = field(default_factory=list)

    @property
    def denied(self) -> list[PackageVerdict]:
        return [v for v in self.verdicts if v.verdict == "deny"]

    @property
    def review(self) -> list[PackageVerdict]:
        return [v for v in self.verdicts if v.verdict == "review"]

    @property
    def unknown(self) -> list[PackageVerdict]:
        return [v for v in self.verdicts if v.verdict == "unknown"]

    @property
    def passed(self) -> bool:
        return not self.denied

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "denied": [v.__dict__ for v in self.denied],
            "review": [v.__dict__ for v in self.review],
            "unknown": [v.__dict__ for v in self.unknown],
            "total_scanned": len(self.verdicts),
        }


def load_policy(path: Path | None = None) -> dict:
    policy_path = path or DEFAULT_POLICY_PATH
    if policy_path.exists():
        with open(policy_path) as f:
            loaded = yaml.safe_load(f) or {}
        merged = {**DEFAULT_POLICY, **loaded}
        return merged
    return DEFAULT_POLICY


def _extract_license(dist: Distribution) -> str:
    meta = dist.metadata
    # Prefer the modern SPDX-ish `License-Expression`/`License` field;
    # fall back to the legacy `Classifier: License :: ...` trove entries,
    # which is how most PyPI packages actually declare license today.
    license_field = meta.get("License-Expression") or meta.get("License")
    if license_field and license_field.strip() and license_field.strip() != "UNKNOWN":
        return license_field.strip()
    classifiers = meta.get_all("Classifier") or []
    for classifier in classifiers:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip()
    return "UNKNOWN"


def _classify(name: str, license_str: str, policy: dict) -> tuple[str, str]:
    override = (policy.get("known_overrides") or {}).get(name)
    if override:
        return "allow", f"known_override: {override}"
    if license_str == "UNKNOWN":
        return "unknown", "no license metadata found"
    for denied in policy.get("deny") or []:
        if denied.lower() in license_str.lower():
            return "deny", f"matches deny-list entry {denied!r}"
    for allowed in policy.get("allow") or []:
        if allowed.lower() in license_str.lower():
            return "allow", f"matches allow-list entry {allowed!r}"
    for reviewed in policy.get("review") or []:
        if reviewed.lower() in license_str.lower():
            return "review", f"matches review-list entry {reviewed!r}"
    return "unknown", "license not recognized under any policy bucket"


def scan_environment(policy: dict) -> GateReport:
    report = GateReport()
    seen: set[str] = set()
    for dist in distributions():
        name = dist.metadata.get("Name") or dist.metadata.get("Summary") or "unknown"
        if name in seen:
            continue
        seen.add(name)
        version = dist.version or "0"
        license_str = _extract_license(dist)
        verdict, reason = _classify(name, license_str, policy)
        report.verdicts.append(
            PackageVerdict(name=name, version=version, license=license_str, verdict=verdict, reason=reason)
        )
    report.verdicts.sort(key=lambda v: v.name.lower())
    return report


def format_text_report(report: GateReport, *, strict: bool) -> str:
    lines: list[str] = []
    if report.denied:
        lines.append("DENIED (license not permitted — P1 violation):")
        for v in report.denied:
            lines.append(f"  - {v.name} {v.version}: {v.license!r} ({v.reason})")
    if report.review:
        lines.append("REVIEW (allowed to build, requires sign-off):")
        for v in report.review:
            lines.append(f"  - {v.name} {v.version}: {v.license!r} ({v.reason})")
    if report.unknown:
        label = "DENIED" if strict else "UNKNOWN (not failing build, but should be classified)"
        lines.append(f"{label}:")
        for v in report.unknown:
            lines.append(f"  - {v.name} {v.version}: {v.license!r}")
    if not lines:
        lines.append(f"All {len(report.verdicts)} packages passed LicenseGate.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SAAP LicenseGate — P1 enforcement")
    parser.add_argument("--policy", type=Path, default=None, help="path to policy YAML")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON report")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat packages with unclassified/unknown licenses as denials",
    )
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    report = scan_environment(policy)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_text_report(report, strict=args.strict))

    if report.denied:
        return 1
    if args.strict and report.unknown:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
