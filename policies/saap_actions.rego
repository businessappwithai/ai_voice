# saap.actions — the shared decision policy `OPAPolicyGuard` evaluates
# via `POST /v1/data/saap/actions` (saap/compliance/policy.py). This is
# the Rego source of truth `InMemoryPolicyGuard` restates in Python for
# tests and the no-OPA dev path — the two must agree; see
# tests/compliance/test_policy.py for the Python-side scenarios this
# file's *_test.rego mirrors.
#
# Three-tier decision table:
#   read       -> always allow
#   write      -> allow only if the tool is on the tenant's
#                 allowed_write_tools list AND it's within the
#                 tenant's business hours (both come from that
#                 tenant's data document under policies/tenant/,
#                 e.g. dental_clinic.rego)
#   high_risk  -> always require_human (never auto-allow or auto-deny)
#
# `input.tenant_id` here is expected to carry the tenant's blueprint
# slug (TenantBlueprint.name, e.g. "dental_clinic") — the same name
# each policies/tenant/<slug>.rego data document is keyed by — not the
# raw tenant_id UUID; resolving UUID -> slug happens before this policy
# is invoked (the tenant provisioner/blueprint registry already holds
# that mapping).
#
# NOT executed against a real `opa` binary in this environment (no
# network path to download one here) — validate with
# `opa test policies/` before relying on this in production.
package saap.actions

import future.keywords.if

default allow := false

default require_human := false

tenant_data := data.tenant[input.tenant_id]

require_human if {
	input.tool.risk_tier == "high_risk"
}

allow if {
	input.tool.risk_tier == "read"
}

allow if {
	input.tool.risk_tier == "write"
	tenant_data.allowed_write_tools[input.tool.name]
	business_hours
}

business_hours if {
	now_ns := time.parse_rfc3339_ns(input.now)
	now_hour := time.clock(now_ns)[0]
	now_hour >= tenant_data.business_hours_start
	now_hour < tenant_data.business_hours_end
}
