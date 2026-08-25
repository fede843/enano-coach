"""Create the BFF technical control plane."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260817_0001"
down_revision = None
branch_labels = None
depends_on = None


def _utc_timestamp() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("display_name_snapshot", sa.String(length=256), nullable=True),
        sa.Column("email_snapshot", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at",
            _utc_timestamp(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            _utc_timestamp(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_login_at", _utc_timestamp(), nullable=True),
        sa.Column("disabled_at", _utc_timestamp(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'blocked', 'disabled')",
            name="ck_app_user_status",
        ),
        sa.CheckConstraint(
            "role IN ('pending', 'viewer', 'operator', 'admin', 'root')",
            name="ck_app_user_role",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_app_user_status_created_at", "app_user", ["status", "created_at"]
    )

    op.create_table(
        "oidc_identity",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("app_user_id", sa.String(length=64), nullable=False),
        sa.Column("issuer", sa.String(length=2048), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            _utc_timestamp(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_seen_at", _utc_timestamp(), nullable=True),
        sa.CheckConstraint(
            "length(issuer) > 0", name="ck_oidc_identity_issuer_nonempty"
        ),
        sa.CheckConstraint(
            "length(subject) > 0", name="ck_oidc_identity_subject_nonempty"
        ),
        sa.ForeignKeyConstraint(["app_user_id"], ["app_user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "issuer", "subject", name="uq_oidc_identity_issuer_subject"
        ),
    )
    op.create_index("ix_oidc_identity_app_user_id", "oidc_identity", ["app_user_id"])

    op.create_table(
        "ow_link",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("app_user_id", sa.String(length=64), nullable=False),
        sa.Column("ow_user_ref", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("linked_by_ref", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            _utc_timestamp(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            _utc_timestamp(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("linked_at", _utc_timestamp(), nullable=True),
        sa.Column("unlinked_at", _utc_timestamp(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'revoked', 'blocked')",
            name="ck_ow_link_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_ow_link_version_positive"),
        sa.CheckConstraint(
            "status <> 'active' OR (linked_at IS NOT NULL AND unlinked_at IS NULL)",
            name="ck_ow_link_active_timestamps",
        ),
        sa.ForeignKeyConstraint(["app_user_id"], ["app_user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_user_id", "version", name="uq_ow_link_user_version"),
    )
    op.create_index("ix_ow_link_user_status", "ow_link", ["app_user_id", "status"])
    op.create_index(
        "uq_ow_link_one_active_per_user",
        "ow_link",
        ["app_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_ow_link_one_active_per_ow_user",
        "ow_link",
        ["ow_user_ref"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "session",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("app_user_id", sa.String(length=64), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            _utc_timestamp(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            _utc_timestamp(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", _utc_timestamp(), nullable=False),
        sa.Column("revoked_at", _utc_timestamp(), nullable=True),
        sa.Column("revocation_reason", sa.String(length=128), nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_session_expiry_after_create"
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_session_revoked_after_create",
        ),
        sa.CheckConstraint(
            "revoked_at IS NOT NULL OR revocation_reason IS NULL",
            name="ck_session_revocation_reason_lifecycle",
        ),
        sa.CheckConstraint(
            "revocation_reason IS NULL OR revocation_reason IN "
            "('account_blocked', 'admin_revoke', 'expired', 'logout', "
            "'security_event')",
            name="ck_session_revocation_reason",
        ),
        sa.CheckConstraint(
            "length(session_hash) = 64 AND lower(session_hash) = session_hash",
            name="ck_session_hash_sha256",
        ),
        sa.CheckConstraint(
            "session_hash ~ '^[0-9a-f]{64}$'",
            name="ck_session_hash_sha256_hex",
        ),
        sa.ForeignKeyConstraint(["app_user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_hash", name="uq_session_session_hash"),
    )
    op.create_index(
        "ix_session_user_expiry_revoked",
        "session",
        ["app_user_id", "expires_at", "revoked_at"],
    )

    op.create_table(
        "audit_event",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("actor_ref", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=96), nullable=False),
        sa.Column("target_type", sa.String(length=48), nullable=False),
        sa.Column("target_ref", sa.String(length=128), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("request_ref", sa.String(length=128), nullable=True),
        sa.Column(
            "occurred_at",
            _utc_timestamp(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "result IN ('success', 'failure', 'denied')",
            name="ck_audit_event_result",
        ),
        sa.CheckConstraint(
            "action IN ('access.denied', 'auth.callback', 'auth.login', 'auth.logout', "
            "'identity.create', 'identity.update', 'ow_link.attach', 'ow_link.detach', "
            "'session.create', 'session.revoke', 'verification.run.create', "
            "'verification.run.read', 'verification.runs.list')",
            name="ck_audit_event_action",
        ),
        sa.CheckConstraint(
            "target_type IN ('app_user', 'idempotency_record', 'oidc_identity', "
            "'ow_link', 'session', 'system', 'verification_run')",
            name="ck_audit_event_target_type",
        ),
        sa.CheckConstraint("length(action) > 0", name="ck_audit_event_action_nonempty"),
        sa.CheckConstraint(
            "length(target_type) > 0", name="ck_audit_event_target_type_nonempty"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_event_occurred_at_id", "audit_event", ["occurred_at", "id"]
    )
    op.create_index(
        "ix_audit_event_actor_occurred_at",
        "audit_event",
        ["actor_ref", "occurred_at"],
    )

    op.create_table(
        "idempotency_record",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner_ref", sa.String(length=128), nullable=False),
        sa.Column("scope", sa.String(length=96), nullable=False),
        sa.Column("key_digest", sa.String(length=64), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("result_ref", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            _utc_timestamp(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            _utc_timestamp(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", _utc_timestamp(), nullable=False),
        sa.Column("completed_at", _utc_timestamp(), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending', 'completed', 'failed', 'expired')",
            name="ck_idempotency_record_state",
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_idempotency_expiry_after_create"
        ),
        sa.CheckConstraint(
            "length(key_digest) = 64 AND lower(key_digest) = key_digest",
            name="ck_idempotency_key_digest_sha256",
        ),
        sa.CheckConstraint(
            "key_digest ~ '^[0-9a-f]{64}$'",
            name="ck_idempotency_key_digest_sha256_hex",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64 AND lower(request_digest) = request_digest",
            name="ck_idempotency_request_digest_sha256",
        ),
        sa.CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'",
            name="ck_idempotency_request_digest_sha256_hex",
        ),
        sa.CheckConstraint("length(scope) > 0", name="ck_idempotency_scope_nonempty"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_ref",
            "scope",
            "key_digest",
            name="uq_idempotency_owner_scope_key_digest",
        ),
    )
    op.create_index(
        "ix_idempotency_owner_scope_expiry",
        "idempotency_record",
        ["owner_ref", "scope", "expires_at"],
    )

    op.create_table(
        "verification_run",
        sa.Column("run_key", sa.String(length=128), nullable=False),
        sa.Column("owner_ref", sa.String(length=128), nullable=False),
        sa.Column("scope_date", sa.Date(), nullable=False),
        sa.Column("scope_timezone", sa.String(length=64), nullable=False),
        sa.Column("scope_domains", sa.String(length=512), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("records_seen", sa.Integer(), nullable=True),
        sa.Column("records_accepted", sa.Integer(), nullable=True),
        sa.Column("records_rejected", sa.Integer(), nullable=True),
        sa.Column("records_duplicated", sa.Integer(), nullable=True),
        sa.Column("fields_unsupported", sa.Integer(), nullable=True),
        sa.Column(
            "warning_codes", sa.String(length=512), server_default="", nullable=False
        ),
        sa.Column(
            "requested_at",
            _utc_timestamp(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", _utc_timestamp(), nullable=True),
        sa.Column("finished_at", _utc_timestamp(), nullable=True),
        sa.Column(
            "created_at",
            _utc_timestamp(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            _utc_timestamp(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'persisted', 'partial', 'failed', 'cancelled', "
            "'skipped', 'completed_with_findings', 'not_verifiable', 'inconclusive')",
            name="ck_verification_run_state",
        ),
        sa.CheckConstraint(
            "length(scope_domains) > 0", name="ck_verification_scope_domains"
        ),
        sa.CheckConstraint(
            "length(scope_timezone) > 0", name="ck_verification_scope_timezone"
        ),
        sa.CheckConstraint(
            "length(warning_codes) <= 512",
            name="ck_verification_warning_codes_length",
        ),
        sa.CheckConstraint(
            "records_seen IS NULL OR records_seen >= 0",
            name="ck_verification_records_seen_nonnegative",
        ),
        sa.CheckConstraint(
            "records_accepted IS NULL OR records_accepted >= 0",
            name="ck_verification_records_accepted_nonnegative",
        ),
        sa.CheckConstraint(
            "records_rejected IS NULL OR records_rejected >= 0",
            name="ck_verification_records_rejected_nonnegative",
        ),
        sa.CheckConstraint(
            "records_duplicated IS NULL OR records_duplicated >= 0",
            name="ck_verification_records_duplicated_nonnegative",
        ),
        sa.CheckConstraint(
            "fields_unsupported IS NULL OR fields_unsupported >= 0",
            name="ck_verification_fields_unsupported_nonnegative",
        ),
        sa.PrimaryKeyConstraint("run_key"),
    )
    op.create_index(
        "ix_verification_run_owner_requested_at",
        "verification_run",
        ["owner_ref", "requested_at"],
    )
    op.create_index(
        "ix_verification_run_state_requested_at",
        "verification_run",
        ["state", "requested_at"],
    )


def downgrade() -> None:
    op.drop_table("verification_run")
    op.drop_table("idempotency_record")
    op.drop_table("audit_event")
    op.drop_table("session")
    op.drop_table("ow_link")
    op.drop_table("oidc_identity")
    op.drop_table("app_user")
