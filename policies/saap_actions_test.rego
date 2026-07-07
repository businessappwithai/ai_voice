# Mirrors tests/compliance/test_policy.py's scenarios for
# InMemoryPolicyGuard so the Rego source of truth and its Python
# restatement stay behaviorally identical. Run with `opa test policies/`
# — NOT executed in this environment (no `opa` binary reachable here;
# see saap_actions.rego's module comment).
package saap.actions_test

import data.saap.actions

mock_tenant_data := {"business_hours_start": 8, "business_hours_end": 20, "allowed_write_tools": {"mcp.calendar.book_slot"}}

test_read_always_allowed if {
	actions.allow with input as {"tool": {"name": "mcp.crm.get_contact", "risk_tier": "read"}, "now": "2026-07-06T03:00:00Z", "tenant_id": "dental_clinic"}
		with data.tenant.dental_clinic as mock_tenant_data
	not actions.require_human with input as {"tool": {"name": "mcp.crm.get_contact", "risk_tier": "read"}, "now": "2026-07-06T03:00:00Z", "tenant_id": "dental_clinic"}
		with data.tenant.dental_clinic as mock_tenant_data
}

test_high_risk_always_requires_human if {
	actions.require_human with input as {"tool": {"name": "mcp.crm.delete_record", "risk_tier": "high_risk"}, "now": "2026-07-06T12:00:00Z", "tenant_id": "dental_clinic"}
		with data.tenant.dental_clinic as mock_tenant_data
	not actions.allow with input as {"tool": {"name": "mcp.crm.delete_record", "risk_tier": "high_risk"}, "now": "2026-07-06T12:00:00Z", "tenant_id": "dental_clinic"}
		with data.tenant.dental_clinic as mock_tenant_data
}

test_write_allowed_in_business_hours if {
	actions.allow with input as {"tool": {"name": "mcp.calendar.book_slot", "risk_tier": "write"}, "now": "2026-07-06T14:00:00Z", "tenant_id": "dental_clinic"}
		with data.tenant.dental_clinic as mock_tenant_data
}

test_write_denied_outside_business_hours if {
	not actions.allow with input as {"tool": {"name": "mcp.calendar.book_slot", "risk_tier": "write"}, "now": "2026-07-06T23:00:00Z", "tenant_id": "dental_clinic"}
		with data.tenant.dental_clinic as mock_tenant_data
}

test_write_denied_if_not_in_allowed_tools if {
	not actions.allow with input as {"tool": {"name": "mcp.calendar.cancel_slot", "risk_tier": "write"}, "now": "2026-07-06T14:00:00Z", "tenant_id": "dental_clinic"}
		with data.tenant.dental_clinic as mock_tenant_data
}
