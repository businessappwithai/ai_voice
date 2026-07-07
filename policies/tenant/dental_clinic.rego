# Per-tenant data document for the "dental_clinic" vertical blueprint —
# the worked example referenced by saap/compliance/policy.py's module
# docstring. Loaded into OPA under `data.tenant.dental_clinic`;
# `policies/saap_actions.rego` looks this up via
# `data.tenant[input.tenant_id]`.
#
# Business hours are UTC (OPA's `time.clock` in saap_actions.rego is
# fed a UTC nanosecond timestamp, matching how OPAPolicyGuard sends
# `datetime.now(UTC).isoformat()` as `input.now`) — a real deployment
# should convert the clinic's local business hours to UTC when writing
# this file, not assume UTC happens to equal India Standard Time.
package tenant.dental_clinic

business_hours_start := 8

business_hours_end := 20

allowed_write_tools := {
	"mcp.calendar.book_slot",
	"mcp.calendar.reschedule_slot",
	"mcp.calendar.cancel_slot",
	"mcp.crm.log_activity",
}
