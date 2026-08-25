"""Bind control records to OW-link generations and enforce lifecycle invariants."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260822_0002"
down_revision = "20260817_0001"
branch_labels = None
depends_on = None


_PROVE_EXISTING_BINDINGS = """
DO $control_plane$
BEGIN
    IF EXISTS (SELECT 1 FROM idempotency_record) THEN
        RAISE EXCEPTION
            'control-plane hardening migration cannot reconstruct '
            'idempotency claim nonces; aborting';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM verification_run AS record
        LEFT JOIN (
            SELECT app_user_id, count(*) AS link_count
            FROM ow_link
            GROUP BY app_user_id
        ) AS links ON links.app_user_id = record.owner_ref
        WHERE links.link_count IS DISTINCT FROM 1
    ) THEN
        RAISE EXCEPTION
            'control-plane hardening migration cannot prove '
            'OW-link generation bindings; aborting';
    END IF;
END
$control_plane$;
"""

_VERIFY_BACKFILL = """
DO $control_plane$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM verification_run
        WHERE ow_link_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'control-plane hardening migration could not backfill '
            'OW-link generation bindings; aborting';
    END IF;
END
$control_plane$;
"""

_DOWNGRADE_AUDIT_ACTIONS = (
    "'access.denied', 'auth.callback', 'auth.login', 'auth.logout', "
    "'identity.create', 'identity.update', 'ow_link.attach', 'ow_link.detach', "
    "'session.create', 'session.revoke', 'verification.run.create', "
    "'verification.run.read', 'verification.runs.list'"
)

_DOWNGRADE_SESSION_REVOCATION_REASONS = (
    "'account_blocked', 'admin_revoke', 'expired', 'logout', 'security_event'"
)

_DOWNGRADE_CONTROL_PLANE_PREFLIGHT = f"""
DO $control_plane$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM audit_event
        WHERE action NOT IN ({_DOWNGRADE_AUDIT_ACTIONS})
    ) OR EXISTS (
        SELECT 1
        FROM session
        WHERE revocation_reason IS NOT NULL
          AND revocation_reason NOT IN ({_DOWNGRADE_SESSION_REVOCATION_REASONS})
    ) THEN
        RAISE EXCEPTION
            'control-plane hardening downgrade cannot represent '
            'existing control-plane values; aborting';
    END IF;
END
$control_plane$;
"""


def upgrade() -> None:
    # This check runs before any schema mutation. Alembic is configured with
    # transactional DDL, so a failed proof also rolls back a partial upgrade.
    op.execute(_PROVE_EXISTING_BINDINGS)

    op.add_column(
        "idempotency_record",
        sa.Column("ow_link_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "idempotency_record",
        sa.Column("claim_nonce", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "verification_run",
        sa.Column("ow_link_id", sa.String(length=64), nullable=True),
    )
    op.execute("""
        UPDATE verification_run AS record
        SET ow_link_id = link.id
        FROM ow_link AS link
        WHERE link.app_user_id = record.owner_ref
          AND (
              SELECT count(*)
              FROM ow_link AS candidate
              WHERE candidate.app_user_id = record.owner_ref
          ) = 1
        """)
    op.execute(_VERIFY_BACKFILL)
    op.alter_column("idempotency_record", "ow_link_id", nullable=False)
    op.alter_column("idempotency_record", "claim_nonce", nullable=False)
    op.alter_column("verification_run", "ow_link_id", nullable=False)
    op.create_check_constraint(
        "ck_idempotency_claim_nonce_length",
        "idempotency_record",
        "length(claim_nonce) = 64 AND lower(claim_nonce) = claim_nonce",
    )
    op.create_check_constraint(
        "ck_idempotency_claim_nonce_hex",
        "idempotency_record",
        "claim_nonce ~ '^[0-9a-f]{64}$'",
    )
    op.create_foreign_key(
        "fk_idempotency_record_ow_link_id",
        "idempotency_record",
        "ow_link",
        ["ow_link_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_idempotency_owner_scope_key_digest",
        "idempotency_record",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_idempotency_owner_link_scope_key_digest",
        "idempotency_record",
        ["owner_ref", "ow_link_id", "scope", "key_digest"],
    )
    op.drop_index("ix_idempotency_owner_scope_expiry", table_name="idempotency_record")
    op.create_index(
        "ix_idempotency_owner_link_scope_expiry",
        "idempotency_record",
        ["owner_ref", "ow_link_id", "scope", "expires_at"],
    )
    op.create_check_constraint(
        "ck_idempotency_scope_allowlist",
        "idempotency_record",
        "scope IN ('verification-run-create')",
    )

    op.create_foreign_key(
        "fk_verification_run_ow_link_id",
        "verification_run",
        "ow_link",
        ["ow_link_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_verification_started_at_order",
        "verification_run",
        "started_at IS NULL OR started_at >= requested_at",
    )
    op.create_check_constraint(
        "ck_verification_finished_at_order",
        "verification_run",
        "finished_at IS NULL OR (started_at IS NOT NULL AND finished_at >= started_at)",
    )
    op.create_check_constraint(
        "ck_verification_terminal_timestamps",
        "verification_run",
        "state = 'pending' OR (started_at IS NOT NULL AND finished_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_verification_counter_relationship",
        "verification_run",
        "records_seen IS NULL OR (coalesce(records_accepted, 0) + "
        "coalesce(records_rejected, 0) + "
        "coalesce(records_duplicated, 0) <= records_seen)",
    )

    op.drop_constraint("ck_session_revocation_reason", "session", type_="check")
    op.create_check_constraint(
        "ck_session_revocation_reason",
        "session",
        "revocation_reason IS NULL OR revocation_reason IN "
        "('account_blocked', 'admin_revoke', 'expired', 'logout', "
        "'ow_unlink', 'security_event')",
    )
    op.drop_constraint("ck_audit_event_action", "audit_event", type_="check")
    op.create_check_constraint(
        "ck_audit_event_action",
        "audit_event",
        "action IN ('access.denied', 'auth.callback', 'auth.login', 'auth.logout', "
        "'identity.create', 'identity.update', 'ow_link.attach', 'ow_link.detach', "
        "'session.create', 'session.revoke', 'verification.run.create', "
        "'verification.run.read', 'verification.run.update', "
        "'verification.runs.list')",
    )


def downgrade() -> None:
    # Run before destructive DDL so transactional failure preserves the
    # current revision and audit rows.
    op.execute(_DOWNGRADE_CONTROL_PLANE_PREFLIGHT)
    op.drop_constraint("ck_audit_event_action", "audit_event", type_="check")
    op.create_check_constraint(
        "ck_audit_event_action",
        "audit_event",
        f"action IN ({_DOWNGRADE_AUDIT_ACTIONS})",
    )
    op.drop_constraint("ck_session_revocation_reason", "session", type_="check")
    op.create_check_constraint(
        "ck_session_revocation_reason",
        "session",
        f"revocation_reason IS NULL OR revocation_reason IN "
        f"({_DOWNGRADE_SESSION_REVOCATION_REASONS})",
    )

    op.drop_constraint(
        "ck_verification_counter_relationship", "verification_run", type_="check"
    )
    op.drop_constraint(
        "ck_verification_terminal_timestamps", "verification_run", type_="check"
    )
    op.drop_constraint(
        "ck_verification_finished_at_order", "verification_run", type_="check"
    )
    op.drop_constraint(
        "ck_verification_started_at_order", "verification_run", type_="check"
    )
    op.drop_constraint(
        "fk_verification_run_ow_link_id", "verification_run", type_="foreignkey"
    )
    op.drop_column("verification_run", "ow_link_id")

    op.drop_constraint(
        "ck_idempotency_scope_allowlist", "idempotency_record", type_="check"
    )
    op.drop_constraint(
        "ck_idempotency_claim_nonce_hex", "idempotency_record", type_="check"
    )
    op.drop_constraint(
        "ck_idempotency_claim_nonce_length", "idempotency_record", type_="check"
    )
    op.drop_index(
        "ix_idempotency_owner_link_scope_expiry", table_name="idempotency_record"
    )
    op.create_index(
        "ix_idempotency_owner_scope_expiry",
        "idempotency_record",
        ["owner_ref", "scope", "expires_at"],
    )
    op.drop_constraint(
        "uq_idempotency_owner_link_scope_key_digest",
        "idempotency_record",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_idempotency_owner_scope_key_digest",
        "idempotency_record",
        ["owner_ref", "scope", "key_digest"],
    )
    op.drop_constraint(
        "fk_idempotency_record_ow_link_id", "idempotency_record", type_="foreignkey"
    )
    op.drop_column("idempotency_record", "claim_nonce")
    op.drop_column("idempotency_record", "ow_link_id")
