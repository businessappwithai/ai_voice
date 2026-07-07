"""initial SAAP schema: tenants, consent, audit, campaigns, approvals, flows, lineage

Revision ID: 0001
Revises:
Create Date: 2026-07-06
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # gen_random_uuid()

    op.create_table(
        "tenants",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vertical", sa.Text, nullable=False),
        sa.Column("locale", sa.Text, nullable=False, server_default="en-IN"),
        sa.Column("data_residency", sa.Text, nullable=False, server_default="in"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Source of truth ConsentGate checks (fail closed if no matching
    # granted row) — the "seeded manually" Phase-1 registry that Phase 3
    # replaces the write path of with a real Consent Manager API sync,
    # without changing this table's shape.
    op.create_table(
        "consent_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.tenant_id"), nullable=False),
        sa.Column("principal_id", sa.Text, nullable=False),
        sa.Column("purpose", sa.Text, nullable=False),
        sa.Column("granted", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("granted_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "principal_id", "purpose", name="uq_consent_grant"),
    )

    # Append-only hash chain (P6/DPDP audit trail). No UPDATE/DELETE
    # grants should ever be issued on this table in production — the
    # hash chain only detects tampering if the app can't correct itself.
    op.create_table(
        "audit_log",
        sa.Column("row_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("prev_hash", sa.Text, nullable=False),
        sa.Column("row_hash", sa.Text, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_log_tenant_created", "audit_log", ["tenant_id", "created_at"])

    # FlowScheduler's only table (plan Section 5.4): due rows are
    # selected and POSTed to their campaign FlowRef; `version` gives
    # idempotent retries after a crash mid-run.
    op.create_table(
        "campaign_enrollments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.tenant_id"), nullable=False),
        sa.Column("principal_id", sa.Text, nullable=False),
        sa.Column("campaign", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("next_action_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_campaign_enrollments_due", "campaign_enrollments", ["next_action_at", "tenant_id"]
    )

    # HITL pause/resume state (plan Section 5.4). `status` transitions:
    # pending -> approved|denied|expired. The scheduler auto-denies on
    # expiry; approvals themselves become audit_log rows.
    op.create_table(
        "approval_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.tenant_id"), nullable=False),
        sa.Column("flow_id", sa.Text, nullable=False),
        sa.Column("flow_name", sa.Text, nullable=False),
        sa.Column("flow_version", sa.Text, nullable=False),
        sa.Column("session_id", sa.Text, nullable=False),
        sa.Column("tool_call", postgresql.JSONB, nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("approver", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_approval_requests_pending", "approval_requests", ["status", "expires_at"]
    )

    # Git-versioned FlowRefs promoted via upsert_flow (plan Section 5.3);
    # tenants bind to a (name, version) pair here, never to "whatever is
    # on the canvas".
    op.create_table(
        "flow_registry",
        sa.Column("flow_id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column("checksum", sa.Text, nullable=False),
        sa.Column("lint_report_id", sa.Text, nullable=False),
        sa.Column("promoted_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", "version", name="uq_flow_name_version"),
    )

    # Exact chunk-level lineage so DPDP erasure's `delete_by_source` is a
    # lookup, not a scan (plan Section 12.2/6.4 — "lineage is what makes
    # erasure exact").
    op.create_table(
        "chunk_lineage",
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.tenant_id"), nullable=False),
        sa.Column("source_uri", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_chunk_lineage_tenant_source", "chunk_lineage", ["tenant_id", "source_uri"]
    )


def downgrade() -> None:
    op.drop_table("chunk_lineage")
    op.drop_table("flow_registry")
    op.drop_table("approval_requests")
    op.drop_table("campaign_enrollments")
    op.drop_table("audit_log")
    op.drop_table("consent_registry")
    op.drop_table("tenants")
