from tools.flow_linter.linter import compute_lint_report_id, lint_flow


def _node(node_id: str, node_type: str, checksum: str | None = None) -> dict:
    return {"id": node_id, "data": {"type": node_type, "node": {"sealed_checksum": checksum}}}


def _edge(source: str, target: str) -> dict:
    return {"source": source, "target": target}


def _flow(nodes: list[dict], edges: list[dict]) -> dict:
    return {"data": {"nodes": nodes, "edges": edges}}


def _valid_chat_flow() -> dict:
    """ComplianceIngress -> ModelRouterLLM -> GroundedResponder -> ChatOutput,
    a tool branch: ModelRouterLLM -> MCPToolkit -> AuditClose."""
    return _flow(
        nodes=[
            _node("ingress-1", "ComplianceIngress"),
            _node("llm-1", "ModelRouterLLM"),
            _node("responder-1", "GroundedResponder"),
            _node("output-1", "ChatOutput"),
            _node("mcp-1", "MCPToolkit"),
            _node("audit-1", "AuditClose"),
        ],
        edges=[
            _edge("ingress-1", "llm-1"),
            _edge("llm-1", "responder-1"),
            _edge("responder-1", "output-1"),
            _edge("llm-1", "mcp-1"),
            _edge("mcp-1", "audit-1"),
        ],
    )


def test_valid_flow_passes() -> None:
    report = lint_flow(_valid_chat_flow())
    assert report.passed, report.to_dict()


def test_missing_compliance_ingress_fails() -> None:
    flow = _valid_chat_flow()
    flow["data"]["nodes"] = [n for n in flow["data"]["nodes"] if n["id"] != "ingress-1"]
    report = lint_flow(flow)
    assert not report.passed
    assert any(f.rule == "missing_compliance_ingress" for f in report.findings)


def test_multiple_compliance_ingress_fails() -> None:
    flow = _valid_chat_flow()
    flow["data"]["nodes"].append(_node("ingress-2", "ComplianceIngress"))
    report = lint_flow(flow)
    assert not report.passed
    assert any(f.rule == "multiple_compliance_ingress" for f in report.findings)


def test_compliance_ingress_with_incoming_edge_fails() -> None:
    flow = _valid_chat_flow()
    flow["data"]["edges"].append(_edge("output-1", "ingress-1"))
    report = lint_flow(flow)
    assert not report.passed
    assert any(f.rule == "compliance_ingress_not_entry" for f in report.findings)


def test_llm_to_output_without_grounded_responder_fails() -> None:
    flow = _flow(
        nodes=[
            _node("ingress-1", "ComplianceIngress"),
            _node("llm-1", "ModelRouterLLM"),
            _node("output-1", "ChatOutput"),
        ],
        edges=[_edge("ingress-1", "llm-1"), _edge("llm-1", "output-1")],
    )
    report = lint_flow(flow)
    assert not report.passed
    assert any(f.rule == "ungrounded_output_path" for f in report.findings)


def test_llm_to_output_through_grounded_responder_passes() -> None:
    flow = _flow(
        nodes=[
            _node("ingress-1", "ComplianceIngress"),
            _node("llm-1", "ModelRouterLLM"),
            _node("responder-1", "GroundedResponder"),
            _node("output-1", "ChatOutput"),
        ],
        edges=[
            _edge("ingress-1", "llm-1"),
            _edge("llm-1", "responder-1"),
            _edge("responder-1", "output-1"),
        ],
    )
    report = lint_flow(flow)
    assert report.passed, report.to_dict()


def test_partial_bypass_of_grounded_responder_fails() -> None:
    """Even if ONE path is grounded, a second path that skips
    GroundedResponder must still fail — the guarantee is "every path",
    not "at least one path"."""
    flow = _flow(
        nodes=[
            _node("ingress-1", "ComplianceIngress"),
            _node("llm-1", "ModelRouterLLM"),
            _node("responder-1", "GroundedResponder"),
            _node("output-1", "ChatOutput"),
        ],
        edges=[
            _edge("ingress-1", "llm-1"),
            _edge("llm-1", "responder-1"),
            _edge("responder-1", "output-1"),
            _edge("llm-1", "output-1"),  # bypass edge straight to output
        ],
    )
    report = lint_flow(flow)
    assert not report.passed
    assert any(f.rule == "ungrounded_output_path" for f in report.findings)


def test_mcp_toolkit_without_audit_close_fails() -> None:
    flow = _flow(
        nodes=[
            _node("ingress-1", "ComplianceIngress"),
            _node("llm-1", "ModelRouterLLM"),
            _node("mcp-1", "MCPToolkit"),
        ],
        edges=[_edge("ingress-1", "llm-1"), _edge("llm-1", "mcp-1")],
    )
    report = lint_flow(flow)
    assert not report.passed
    assert any(f.rule == "tool_path_missing_audit_close" for f in report.findings)


def test_mcp_toolkit_with_unreachable_audit_close_fails() -> None:
    flow = _flow(
        nodes=[
            _node("ingress-1", "ComplianceIngress"),
            _node("mcp-1", "MCPToolkit"),
            _node("audit-1", "AuditClose"),  # present but disconnected from mcp-1
        ],
        edges=[_edge("ingress-1", "mcp-1")],
    )
    report = lint_flow(flow)
    assert not report.passed
    assert any(f.rule == "tool_path_missing_audit_close" for f in report.findings)


def test_disallowed_raw_http_component_fails() -> None:
    flow = _valid_chat_flow()
    flow["data"]["nodes"].append(_node("http-1", "HTTPRequest"))
    report = lint_flow(flow)
    assert not report.passed
    assert any(f.rule == "disallowed_component" for f in report.findings)


def test_sealed_checksum_mismatch_fails() -> None:
    flow = _valid_chat_flow()
    for n in flow["data"]["nodes"]:
        if n["id"] == "ingress-1":
            n["data"]["node"]["sealed_checksum"] = "wrong-checksum"
    report = lint_flow(flow, pinned_checksums={"ComplianceIngress": "correct-checksum"})
    assert not report.passed
    assert any(f.rule == "sealed_checksum_mismatch" for f in report.findings)


def test_sealed_checksum_match_passes() -> None:
    flow = _valid_chat_flow()
    for n in flow["data"]["nodes"]:
        if n["id"] == "ingress-1":
            n["data"]["node"]["sealed_checksum"] = "correct-checksum"
    report = lint_flow(flow, pinned_checksums={"ComplianceIngress": "correct-checksum"})
    assert report.passed, report.to_dict()


def test_no_pin_configured_skips_checksum_check() -> None:
    flow = _valid_chat_flow()  # sealed_checksum is None throughout
    report = lint_flow(flow, pinned_checksums={})
    assert report.passed, report.to_dict()


def test_compute_lint_report_id_is_deterministic() -> None:
    flow = _valid_chat_flow()
    report = lint_flow(flow)
    id1 = compute_lint_report_id(flow, report)
    id2 = compute_lint_report_id(flow, report)
    assert id1 == id2
    assert len(id1) == 64  # sha256 hex digest


def test_compute_lint_report_id_changes_with_flow_content() -> None:
    flow1 = _valid_chat_flow()
    flow2 = _valid_chat_flow()
    flow2["data"]["nodes"].append(_node("extra-1", "ComplianceIngress"))
    report1 = lint_flow(flow1)
    report2 = lint_flow(flow2)
    assert compute_lint_report_id(flow1, report1) != compute_lint_report_id(flow2, report2)
