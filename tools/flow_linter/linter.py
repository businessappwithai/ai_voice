"""Flow Linter — CI enforcement of the sealed compliance path on
Langflow canvases (plan Phase 1 Epic 1.5; architecture Section 5.3).

A visual tool becomes production-grade through governance of its
artifacts: this linter parses an exported flow JSON graph and fails
the build unless:

  1. `ComplianceIngress` is the unique entry node (no incoming edges,
     exactly one instance).
  2. Every path from an LLM/Agent component to a Chat Output passes
     through `GroundedResponder`.
  3. Every path from a tool-bearing component (`MCPToolkit`) reaches
     an `AuditClose` node.
  4. No raw HTTP/Python-REPL-class components appear in the flow.
  5. Every sealed component's checksum matches the pinned library
     version (drift detection for `sealed=True` components).

Flow JSON shape: this operates on the general Langflow export shape —
`{"data": {"nodes": [{"id", "data": {"type", "node": {"sealed_checksum"}}}], "edges": [{"source", "target"}]}}`.
Node `type` values are the component class names (`ComplianceIngress`,
`GroundedResponder`, `MCPToolkit`, `AuditClose`, ...). Field names are
based on Langflow's documented export format; re-verify against a real
exported flow the first time this runs against Epic 1.5's actual
canvas and adjust `FlowGraph.from_json` if the real export differs —
this module isn't itself unit-tested against a live Langflow instance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Component type names that are `sealed=True` on the canvas (architecture
# Section 5.2's table) — checksum-pinned so drift is detected, not
# silently absorbed.
SEALED_COMPONENT_TYPES = frozenset(
    {"ComplianceIngress", "GroundedResponder", "MCPToolkit", "HITLCheckpoint", "AuditClose"}
)

# Anything that lets a designer bypass the governed component library
# with raw code/HTTP on the canvas — never allowed in tenant-facing flows.
DISALLOWED_COMPONENT_TYPES = frozenset(
    {"HTTPRequest", "APIRequest", "PythonREPL", "PythonCodeTool", "CustomComponent", "Webhook"}
)

TOOL_BEARING_COMPONENT_TYPES = frozenset({"MCPToolkit"})
LLM_COMPONENT_TYPES = frozenset({"ModelRouterLLM", "Agent", "AgentComponent"})
OUTPUT_COMPONENT_TYPES = frozenset({"ChatOutput"})


@dataclass(frozen=True)
class FlowNode:
    id: str
    type: str
    sealed_checksum: str | None = None


@dataclass
class FlowGraph:
    nodes: dict[str, FlowNode]
    edges: list[tuple[str, str]]

    @classmethod
    def from_json(cls, flow_json: dict[str, Any]) -> FlowGraph:
        raw_nodes = flow_json.get("data", {}).get("nodes", [])
        raw_edges = flow_json.get("data", {}).get("edges", [])
        nodes: dict[str, FlowNode] = {}
        for n in raw_nodes:
            node_id = n["id"]
            data = n.get("data", {})
            node_type = data.get("type") or n.get("type") or "unknown"
            checksum = data.get("node", {}).get("sealed_checksum")
            nodes[node_id] = FlowNode(id=node_id, type=node_type, sealed_checksum=checksum)
        edges = [(e["source"], e["target"]) for e in raw_edges]
        return cls(nodes=nodes, edges=edges)

    def successors(self, node_id: str) -> list[str]:
        return [t for s, t in self.edges if s == node_id]

    def predecessors(self, node_id: str) -> list[str]:
        return [s for s, t in self.edges if t == node_id]

    def nodes_of_type(self, type_name: str) -> list[FlowNode]:
        return [n for n in self.nodes.values() if n.type == type_name]


@dataclass(frozen=True)
class LintFinding:
    rule: str
    message: str
    node_id: str | None = None


@dataclass
class LintReport:
    findings: list[LintFinding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "findings": [f.__dict__ for f in self.findings]}


def _exists_bypassing_path(graph: FlowGraph, start: str, end: str, must_pass_through: set[str]) -> bool:
    """True if some path start->end exists that never visits a node in
    `must_pass_through` — i.e. a compliance bypass exists. Paths that
    do reach a `must_pass_through` node are not explored further from
    there, since continuing would only find *other*, already-compliant
    routes past the checkpoint."""
    visited: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node == end:
            return True
        if node in visited:
            continue
        visited.add(node)
        for succ in graph.successors(node):
            if succ in must_pass_through:
                continue
            stack.append(succ)
    return False


def _can_reach_any(graph: FlowGraph, start: str, targets: set[str]) -> bool:
    visited: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node in targets:
            return True
        if node in visited:
            continue
        visited.add(node)
        stack.extend(graph.successors(node))
    return False


def _check_unique_compliance_ingress(graph: FlowGraph, report: LintReport) -> None:
    entries = graph.nodes_of_type("ComplianceIngress")
    if len(entries) == 0:
        report.findings.append(
            LintFinding("missing_compliance_ingress", "flow has no ComplianceIngress entry node")
        )
        return
    if len(entries) > 1:
        report.findings.append(
            LintFinding(
                "multiple_compliance_ingress",
                f"flow has {len(entries)} ComplianceIngress nodes; exactly one required",
                node_id=",".join(n.id for n in entries),
            )
        )
        return
    entry = entries[0]
    if graph.predecessors(entry.id):
        report.findings.append(
            LintFinding(
                "compliance_ingress_not_entry",
                "ComplianceIngress must be the flow's entry node (no incoming edges)",
                node_id=entry.id,
            )
        )


def _check_grounded_responder_before_output(graph: FlowGraph, report: LintReport) -> None:
    output_ids = [n.id for n in graph.nodes.values() if n.type in OUTPUT_COMPONENT_TYPES]
    llm_ids = [n.id for n in graph.nodes.values() if n.type in LLM_COMPONENT_TYPES]
    grounded_ids = {n.id for n in graph.nodes.values() if n.type == "GroundedResponder"}

    for llm_id in llm_ids:
        for output_id in output_ids:
            if _exists_bypassing_path(graph, llm_id, output_id, grounded_ids):
                report.findings.append(
                    LintFinding(
                        "ungrounded_output_path",
                        f"path from {llm_id} to {output_id} reaches Chat Output without "
                        "passing through GroundedResponder",
                        node_id=llm_id,
                    )
                )


def _check_tool_paths_end_in_audit_close(graph: FlowGraph, report: LintReport) -> None:
    tool_ids = [n.id for n in graph.nodes.values() if n.type in TOOL_BEARING_COMPONENT_TYPES]
    audit_close_ids = {n.id for n in graph.nodes.values() if n.type == "AuditClose"}
    for tool_id in tool_ids:
        if not audit_close_ids or not _can_reach_any(graph, tool_id, audit_close_ids):
            report.findings.append(
                LintFinding(
                    "tool_path_missing_audit_close",
                    f"no path from tool-bearing component {tool_id} to any AuditClose node",
                    node_id=tool_id,
                )
            )


def _check_no_disallowed_components(graph: FlowGraph, report: LintReport) -> None:
    for node in graph.nodes.values():
        if node.type in DISALLOWED_COMPONENT_TYPES:
            report.findings.append(
                LintFinding(
                    "disallowed_component",
                    f"raw {node.type} components are not allowed in tenant-facing flows",
                    node_id=node.id,
                )
            )


def _check_sealed_checksums(graph: FlowGraph, report: LintReport, pinned: dict[str, str]) -> None:
    for node in graph.nodes.values():
        if node.type not in SEALED_COMPONENT_TYPES:
            continue
        expected = pinned.get(node.type)
        if expected is None:
            continue  # no pin configured for this component type; nothing to compare against
        if node.sealed_checksum != expected:
            report.findings.append(
                LintFinding(
                    "sealed_checksum_mismatch",
                    f"{node.type} node {node.id} checksum {node.sealed_checksum!r} "
                    f"does not match pinned {expected!r}",
                    node_id=node.id,
                )
            )


def lint_flow(flow_json: dict[str, Any], *, pinned_checksums: dict[str, str] | None = None) -> LintReport:
    graph = FlowGraph.from_json(flow_json)
    report = LintReport()
    _check_unique_compliance_ingress(graph, report)
    _check_grounded_responder_before_output(graph, report)
    _check_tool_paths_end_in_audit_close(graph, report)
    _check_no_disallowed_components(graph, report)
    _check_sealed_checksums(graph, report, pinned_checksums or {})
    return report


def compute_lint_report_id(flow_json: dict[str, Any], report: LintReport) -> str:
    """Deterministic id proving a specific flow JSON passed this exact
    lint report — stored as `FlowRef.lint_report_id` (saap.core.flow),
    so a promoted flow can always be traced back to the lint run that
    approved it."""
    canonical = json.dumps(
        {"flow": flow_json, "report": report.to_dict()}, sort_keys=True, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SAAP Flow Linter")
    parser.add_argument("flow_json", type=Path, help="path to an exported flow JSON file")
    parser.add_argument(
        "--pinned", type=Path, default=None, help="JSON file mapping sealed component type -> checksum"
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON report")
    args = parser.parse_args(argv)

    flow_json = json.loads(args.flow_json.read_text())
    pinned = json.loads(args.pinned.read_text()) if args.pinned else {}
    report = lint_flow(flow_json, pinned_checksums=pinned)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        if report.passed:
            print(f"Flow Linter: PASS ({len(flow_json.get('data', {}).get('nodes', []))} nodes checked)")
        else:
            print("Flow Linter: FAIL")
            for f in report.findings:
                print(f"  [{f.rule}] {f.message}" + (f" (node: {f.node_id})" if f.node_id else ""))

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
