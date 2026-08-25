"""SQLAlchemy metadata for the BFF technical control plane.

This module describes ownership, identity, session, audit, and verification
control records only.  It deliberately does not create an engine or open a
database connection; the synthetic BFF remains in-memory until a later wave
enables the separate application database.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates

ALLOWED_APP_USER_STATUSES: Final = frozenset(
    {"pending", "active", "blocked", "disabled"}
)
ALLOWED_APP_USER_ROLES: Final = frozenset(
    {"pending", "viewer", "operator", "admin", "root"}
)
ALLOWED_OW_LINK_STATUSES: Final = frozenset({"pending", "active", "revoked", "blocked"})
ALLOWED_IDEMPOTENCY_STATES: Final = frozenset(
    {"pending", "completed", "failed", "expired"}
)
ALLOWED_IDEMPOTENCY_SCOPES: Final = frozenset({"verification-run-create"})
ALLOWED_VERIFICATION_STATES: Final = frozenset(
    {
        "pending",
        "persisted",
        "partial",
        "failed",
        "cancelled",
        "skipped",
        "completed_with_findings",
        "not_verifiable",
        "inconclusive",
    }
)
ALLOWED_VERIFICATION_TERMINAL_STATES: Final = frozenset(
    ALLOWED_VERIFICATION_STATES - {"pending"}
)
ALLOWED_SCOPE_DOMAINS: Final = frozenset(
    {"activity", "sleep", "recovery", "body", "workouts", "sources"}
)
ALLOWED_WARNING_CODES: Final = frozenset(
    {
        "BODY_RELATIVE_TO_NOW",
        "CURSOR_EXPIRED",
        "INCONCLUSIVE",
        "MISMATCH",
        "NOT_VERIFIABLE",
        "PARTIAL_COVERAGE",
        "SOURCE_AMBIGUOUS",
        "UNSUPPORTED",
        "UPSTREAM_LIMITED",
    }
)
ALLOWED_AUDIT_ACTIONS: Final = frozenset(
    {
        "access.denied",
        "auth.callback",
        "auth.login",
        "auth.logout",
        "identity.create",
        "identity.update",
        "ow_link.attach",
        "ow_link.detach",
        "session.create",
        "session.revoke",
        "verification.run.create",
        "verification.run.read",
        "verification.run.update",
        "verification.runs.list",
    }
)
ALLOWED_AUDIT_TARGET_TYPES: Final = frozenset(
    {
        "app_user",
        "idempotency_record",
        "oidc_identity",
        "ow_link",
        "session",
        "system",
        "verification_run",
    }
)
ALLOWED_AUDIT_RESULTS: Final = frozenset({"success", "failure", "denied"})
ALLOWED_REVOCATION_REASONS: Final = frozenset(
    {
        "account_blocked",
        "admin_revoke",
        "expired",
        "logout",
        "ow_unlink",
        "security_event",
    }
)

SHA256_HEX_LENGTH: Final = hashlib.sha256().digest_size * 2
_SHA256_HEX_PATTERN = re.compile(rf"^[0-9a-f]{{{SHA256_HEX_LENGTH}}}$")
_PLACEHOLDER_DIGESTS = frozenset(
    {
        "deadbeef" * 8,
        "0123456789abcdef" * 4,
        "abcdef0123456789" * 4,
    }
)
_TECHNICAL_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_FORBIDDEN_REFERENCE_TERMS = (
    "api-key",
    "api_key",
    "authorization",
    "bearer",
    "credential",
    "password",
    "private-key",
    "private_key",
    "secret",
    "token",
)


def hash_session_token(raw_token: str | bytes) -> str:
    """Return a canonical digest for a raw token without retaining the token."""

    if isinstance(raw_token, str):
        raw_bytes = raw_token.encode("utf-8")
    elif isinstance(raw_token, bytes):
        raw_bytes = raw_token
    else:
        raise TypeError("raw session token must be text or bytes")
    if not raw_bytes:
        raise ValueError("raw session token must not be empty")
    return hashlib.sha256(raw_bytes).hexdigest()


def _validate_digest(value: str, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not _SHA256_HEX_PATTERN.fullmatch(value)
        or len(set(value)) == 1
        or value in _PLACEHOLDER_DIGESTS
    ):
        raise ValueError(f"{field_name} must be a non-placeholder SHA-256 digest")
    return value


def _validate_claim_nonce(value: str) -> str:
    if (
        not isinstance(value, str)
        or not _SHA256_HEX_PATTERN.fullmatch(value)
        or value in _PLACEHOLDER_DIGESTS
        or len(set(value)) == 1
    ):
        raise ValueError("idempotency_record.claim_nonce must be a random nonce")
    return value


def _validate_allowlisted_value(
    value: str, *, field_name: str, allowed: frozenset[str]
) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{field_name} is not in the control-plane allowlist")
    return value


def _validate_allowlisted_csv(
    value: str,
    *,
    field_name: str,
    allowed: frozenset[str],
    allow_empty: bool,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} is not in the control-plane allowlist")
    if value == "":
        if allow_empty:
            return value
        raise ValueError(f"{field_name} is not in the control-plane allowlist")

    values = value.split(",")
    if any(item not in allowed for item in values) or len(set(values)) != len(values):
        raise ValueError(f"{field_name} is not in the control-plane allowlist")
    return ",".join(sorted(values))


def validate_technical_reference(
    value: str, *, field_name: str, max_length: int = 128
) -> str:
    """Validate a bounded machine reference without accepting content text."""

    if (
        not isinstance(value, str)
        or not value
        or len(value) > max_length
        or _TECHNICAL_REFERENCE_PATTERN.fullmatch(value) is None
    ):
        raise ValueError(f"{field_name} must be a bounded machine reference")

    folded = value.casefold()
    if any(term in folded for term in _FORBIDDEN_REFERENCE_TERMS):
        raise ValueError(f"{field_name} must be a bounded machine reference")
    if _SHA256_HEX_PATTERN.fullmatch(folded) or len(set(value)) == 1:
        raise ValueError(f"{field_name} must be a bounded machine reference")
    if re.search(r"(.)\1{15,}", value):
        raise ValueError(f"{field_name} must be a bounded machine reference")
    return value


def validate_iana_timezone(value: str, *, field_name: str = "timezone") -> str:
    """Validate a timezone name through the local IANA zoneinfo database."""

    if (
        not isinstance(value, str)
        or not value
        or len(value) > 64
        or value.startswith(("/", "."))
        or "\\" in value
        or ".." in value
    ):
        raise ValueError(f"{field_name} must be a valid IANA timezone")
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError(f"{field_name} must be a valid IANA timezone") from None
    return value


def utc_now() -> datetime:
    """Return an aware UTC timestamp for application-side defaults."""

    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base metadata for the isolated application database."""


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'blocked', 'disabled')",
            name="ck_app_user_status",
        ),
        CheckConstraint(
            "role IN ('pending', 'viewer', 'operator', 'admin', 'root')",
            name="ck_app_user_role",
        ),
        Index("ix_app_user_status_created_at", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    display_name_snapshot: Mapped[str | None] = mapped_column(
        String(256), nullable=True
    )
    email_snapshot: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @validates("id")
    def validate_id(self, key: str, value: str) -> str:
        del key
        return validate_technical_reference(
            value, field_name="app_user.id", max_length=64
        )

    @validates("status")
    def validate_status(self, key: str, value: str) -> str:
        del key
        return _validate_allowlisted_value(
            value,
            field_name="app_user.status",
            allowed=ALLOWED_APP_USER_STATUSES,
        )

    @validates("role")
    def validate_role(self, key: str, value: str) -> str:
        del key
        return _validate_allowlisted_value(
            value,
            field_name="app_user.role",
            allowed=ALLOWED_APP_USER_ROLES,
        )


class OidcIdentity(Base):
    __tablename__ = "oidc_identity"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_oidc_identity_issuer_subject"),
        CheckConstraint("length(issuer) > 0", name="ck_oidc_identity_issuer_nonempty"),
        CheckConstraint(
            "length(subject) > 0", name="ck_oidc_identity_subject_nonempty"
        ),
        Index("ix_oidc_identity_app_user_id", "app_user_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    app_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    issuer: Mapped[str] = mapped_column(String(2048), nullable=False)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @validates("id", "app_user_id")
    def validate_reference(self, key: str, value: str) -> str:
        return validate_technical_reference(
            value, field_name=f"oidc_identity.{key}", max_length=64
        )


class OwLink(Base):
    __tablename__ = "ow_link"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'revoked', 'blocked')",
            name="ck_ow_link_status",
        ),
        CheckConstraint("version >= 1", name="ck_ow_link_version_positive"),
        CheckConstraint(
            "status <> 'active' OR (linked_at IS NOT NULL AND unlinked_at IS NULL)",
            name="ck_ow_link_active_timestamps",
        ),
        UniqueConstraint("app_user_id", "version", name="uq_ow_link_user_version"),
        Index("ix_ow_link_user_status", "app_user_id", "status"),
        Index(
            "uq_ow_link_one_active_per_user",
            "app_user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "uq_ow_link_one_active_per_ow_user",
            "ow_user_ref",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    app_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    ow_user_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    linked_by_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    linked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    unlinked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @validates("id", "app_user_id")
    def validate_reference(self, key: str, value: str) -> str:
        return validate_technical_reference(
            value, field_name=f"ow_link.{key}", max_length=64
        )

    @validates("status")
    def validate_status(self, key: str, value: str) -> str:
        del key
        return _validate_allowlisted_value(
            value,
            field_name="ow_link.status",
            allowed=ALLOWED_OW_LINK_STATUSES,
        )

    @validates("ow_user_ref")
    def validate_ow_user_ref(self, key: str, value: str) -> str:
        del key
        return validate_technical_reference(value, field_name="ow_link.ow_user_ref")

    @validates("linked_by_ref")
    def validate_linked_by_ref(self, key: str, value: str | None) -> str | None:
        del key
        if value is None:
            return None
        return validate_technical_reference(value, field_name="ow_link.linked_by_ref")


class ServerSession(Base):
    __tablename__ = "session"
    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at", name="ck_session_expiry_after_create"
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_session_revoked_after_create",
        ),
        CheckConstraint(
            "revoked_at IS NOT NULL OR revocation_reason IS NULL",
            name="ck_session_revocation_reason_lifecycle",
        ),
        CheckConstraint(
            "revocation_reason IS NULL OR revocation_reason IN "
            "('account_blocked', 'admin_revoke', 'expired', 'logout', "
            "'ow_unlink', 'security_event')",
            name="ck_session_revocation_reason",
        ),
        CheckConstraint(
            "length(session_hash) = 64 AND lower(session_hash) = session_hash",
            name="ck_session_hash_sha256",
        ),
        CheckConstraint(
            "session_hash ~ '^[0-9a-f]{64}$'",
            name="ck_session_hash_sha256_hex",
        ).ddl_if(dialect="postgresql"),
        UniqueConstraint("session_hash", name="uq_session_session_hash"),
        Index(
            "ix_session_user_expiry_revoked",
            "app_user_id",
            "expires_at",
            "revoked_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    app_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    session_hash: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revocation_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)

    @validates("id", "app_user_id")
    def validate_reference(self, key: str, value: str) -> str:
        return validate_technical_reference(
            value, field_name=f"session.{key}", max_length=64
        )

    @validates("session_hash")
    def validate_session_hash(self, key: str, value: str) -> str:
        del key
        return _validate_digest(value, field_name="session_hash")

    @validates("revocation_reason")
    def validate_revocation_reason(self, key: str, value: str | None) -> str | None:
        del key
        if value is None:
            return None
        return _validate_allowlisted_value(
            value,
            field_name="session.revocation_reason",
            allowed=ALLOWED_REVOCATION_REASONS,
        )


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        CheckConstraint(
            "result IN ('success', 'failure', 'denied')",
            name="ck_audit_event_result",
        ),
        CheckConstraint(
            "action IN ('access.denied', 'auth.callback', 'auth.login', 'auth.logout', "
            "'identity.create', 'identity.update', 'ow_link.attach', 'ow_link.detach', "
            "'session.create', 'session.revoke', 'verification.run.create', "
            "'verification.run.read', 'verification.run.update', "
            "'verification.runs.list')",
            name="ck_audit_event_action",
        ),
        CheckConstraint(
            "target_type IN ('app_user', 'idempotency_record', 'oidc_identity', "
            "'ow_link', 'session', 'system', 'verification_run')",
            name="ck_audit_event_target_type",
        ),
        CheckConstraint("length(action) > 0", name="ck_audit_event_action_nonempty"),
        CheckConstraint(
            "length(target_type) > 0", name="ck_audit_event_target_type_nonempty"
        ),
        Index("ix_audit_event_occurred_at_id", "occurred_at", "id"),
        Index("ix_audit_event_actor_occurred_at", "actor_ref", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(96), nullable=False)
    target_type: Mapped[str] = mapped_column(String(48), nullable=False)
    target_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    request_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    @validates("id")
    def validate_id(self, key: str, value: str) -> str:
        del key
        return validate_technical_reference(
            value, field_name="audit_event.id", max_length=64
        )

    @validates("action")
    def validate_action(self, key: str, value: str) -> str:
        del key
        return _validate_allowlisted_value(
            value,
            field_name="audit_event.action",
            allowed=ALLOWED_AUDIT_ACTIONS,
        )

    @validates("target_type")
    def validate_target_type(self, key: str, value: str) -> str:
        del key
        return _validate_allowlisted_value(
            value,
            field_name="audit_event.target_type",
            allowed=ALLOWED_AUDIT_TARGET_TYPES,
        )

    @validates("result")
    def validate_result(self, key: str, value: str) -> str:
        del key
        return _validate_allowlisted_value(
            value,
            field_name="audit_event.result",
            allowed=ALLOWED_AUDIT_RESULTS,
        )

    @validates("actor_ref", "target_ref", "request_ref")
    def validate_reference(self, key: str, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_technical_reference(value, field_name=f"audit_event.{key}")


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"
    __table_args__ = (
        UniqueConstraint(
            "owner_ref",
            "ow_link_id",
            "scope",
            "key_digest",
            name="uq_idempotency_owner_link_scope_key_digest",
        ),
        CheckConstraint(
            "state IN ('pending', 'completed', 'failed', 'expired')",
            name="ck_idempotency_record_state",
        ),
        CheckConstraint(
            "expires_at > created_at", name="ck_idempotency_expiry_after_create"
        ),
        CheckConstraint(
            "length(key_digest) = 64 AND lower(key_digest) = key_digest",
            name="ck_idempotency_key_digest_sha256",
        ),
        CheckConstraint(
            "key_digest ~ '^[0-9a-f]{64}$'",
            name="ck_idempotency_key_digest_sha256_hex",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "length(request_digest) = 64 AND lower(request_digest) = request_digest",
            name="ck_idempotency_request_digest_sha256",
        ),
        CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'",
            name="ck_idempotency_request_digest_sha256_hex",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "length(claim_nonce) = 64 AND lower(claim_nonce) = claim_nonce",
            name="ck_idempotency_claim_nonce_length",
        ),
        CheckConstraint(
            "claim_nonce ~ '^[0-9a-f]{64}$'",
            name="ck_idempotency_claim_nonce_hex",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint("length(scope) > 0", name="ck_idempotency_scope_nonempty"),
        CheckConstraint(
            "scope IN ('verification-run-create')",
            name="ck_idempotency_scope_allowlist",
        ),
        Index(
            "ix_idempotency_owner_link_scope_expiry",
            "owner_ref",
            "ow_link_id",
            "scope",
            "expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    ow_link_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ow_link.id", ondelete="RESTRICT"), nullable=False
    )
    claim_nonce: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH), nullable=False)
    scope: Mapped[str] = mapped_column(String(96), nullable=False)
    key_digest: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH), nullable=False)
    request_digest: Mapped[str] = mapped_column(
        String(SHA256_HEX_LENGTH), nullable=False
    )
    result_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @validates("key_digest")
    def validate_key_digest(self, key: str, value: str) -> str:
        del key
        return _validate_digest(value, field_name="idempotency_record.key_digest")

    @validates("claim_nonce")
    def validate_claim_nonce(self, key: str, value: str) -> str:
        del key
        return _validate_claim_nonce(value)

    @validates("id", "owner_ref", "ow_link_id", "result_ref")
    def validate_reference(self, key: str, value: str | None) -> str | None:
        if value is None:
            return None
        max_length = 64 if key in {"id", "ow_link_id"} else 128
        return validate_technical_reference(
            value,
            field_name=f"idempotency_record.{key}",
            max_length=max_length,
        )

    @validates("scope")
    def validate_scope(self, key: str, value: str) -> str:
        del key
        return _validate_allowlisted_value(
            value,
            field_name="idempotency_record.scope",
            allowed=ALLOWED_IDEMPOTENCY_SCOPES,
        )

    @validates("request_digest")
    def validate_request_digest(self, key: str, value: str) -> str:
        del key
        return _validate_digest(value, field_name="idempotency_record.request_digest")

    @validates("state")
    def validate_state(self, key: str, value: str) -> str:
        del key
        return _validate_allowlisted_value(
            value,
            field_name="idempotency_record.state",
            allowed=ALLOWED_IDEMPOTENCY_STATES,
        )


class VerificationRunControl(Base):
    __tablename__ = "verification_run"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'persisted', 'partial', 'failed', 'cancelled', "
            "'skipped', 'completed_with_findings', 'not_verifiable', 'inconclusive')",
            name="ck_verification_run_state",
        ),
        CheckConstraint(
            "length(scope_domains) > 0", name="ck_verification_scope_domains"
        ),
        CheckConstraint(
            "length(scope_timezone) > 0", name="ck_verification_scope_timezone"
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= requested_at",
            name="ck_verification_started_at_order",
        ),
        CheckConstraint(
            "finished_at IS NULL OR "
            "(started_at IS NOT NULL AND finished_at >= started_at)",
            name="ck_verification_finished_at_order",
        ),
        CheckConstraint(
            "state = 'pending' OR (started_at IS NOT NULL AND finished_at IS NOT NULL)",
            name="ck_verification_terminal_timestamps",
        ),
        CheckConstraint(
            "records_seen IS NULL OR (coalesce(records_accepted, 0) + "
            "coalesce(records_rejected, 0) + "
            "coalesce(records_duplicated, 0) <= records_seen)",
            name="ck_verification_counter_relationship",
        ),
        CheckConstraint(
            "length(warning_codes) <= 512",
            name="ck_verification_warning_codes_length",
        ),
        CheckConstraint(
            "records_seen IS NULL OR records_seen >= 0",
            name="ck_verification_records_seen_nonnegative",
        ),
        CheckConstraint(
            "records_accepted IS NULL OR records_accepted >= 0",
            name="ck_verification_records_accepted_nonnegative",
        ),
        CheckConstraint(
            "records_rejected IS NULL OR records_rejected >= 0",
            name="ck_verification_records_rejected_nonnegative",
        ),
        CheckConstraint(
            "records_duplicated IS NULL OR records_duplicated >= 0",
            name="ck_verification_records_duplicated_nonnegative",
        ),
        CheckConstraint(
            "fields_unsupported IS NULL OR fields_unsupported >= 0",
            name="ck_verification_fields_unsupported_nonnegative",
        ),
        Index("ix_verification_run_owner_requested_at", "owner_ref", "requested_at"),
        Index("ix_verification_run_state_requested_at", "state", "requested_at"),
    )

    run_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    ow_link_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ow_link.id", ondelete="RESTRICT"), nullable=False
    )
    scope_date: Mapped[date] = mapped_column(Date, nullable=False)
    scope_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_domains: Mapped[str] = mapped_column(String(512), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    records_seen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_accepted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_rejected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_duplicated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fields_unsupported: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warning_codes: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    @validates("scope_domains")
    def validate_scope_domains(self, key: str, value: str) -> str:
        del key
        return _validate_allowlisted_csv(
            value,
            field_name="verification_run.scope_domains",
            allowed=ALLOWED_SCOPE_DOMAINS,
            allow_empty=False,
        )

    @validates("run_key", "owner_ref", "ow_link_id")
    def validate_reference(self, key: str, value: str | None) -> str | None:
        if value is None:
            return None
        max_length = 64 if key == "ow_link_id" else 128
        return validate_technical_reference(
            value,
            field_name=f"verification_run.{key}",
            max_length=max_length,
        )

    @validates("scope_timezone")
    def validate_scope_timezone(self, key: str, value: str) -> str:
        del key
        return validate_iana_timezone(
            value, field_name="verification_run.scope_timezone"
        )

    @validates("warning_codes")
    def validate_warning_codes(self, key: str, value: str) -> str:
        del key
        return _validate_allowlisted_csv(
            value,
            field_name="verification_run.warning_codes",
            allowed=ALLOWED_WARNING_CODES,
            allow_empty=True,
        )

    @validates("state")
    def validate_state(self, key: str, value: str) -> str:
        del key
        return _validate_allowlisted_value(
            value,
            field_name="verification_run.state",
            allowed=ALLOWED_VERIFICATION_STATES,
        )


__all__ = [
    "ALLOWED_APP_USER_ROLES",
    "ALLOWED_APP_USER_STATUSES",
    "ALLOWED_AUDIT_ACTIONS",
    "ALLOWED_AUDIT_RESULTS",
    "ALLOWED_AUDIT_TARGET_TYPES",
    "ALLOWED_IDEMPOTENCY_STATES",
    "ALLOWED_IDEMPOTENCY_SCOPES",
    "ALLOWED_OW_LINK_STATUSES",
    "ALLOWED_REVOCATION_REASONS",
    "ALLOWED_SCOPE_DOMAINS",
    "ALLOWED_VERIFICATION_STATES",
    "ALLOWED_VERIFICATION_TERMINAL_STATES",
    "ALLOWED_WARNING_CODES",
    "AppUser",
    "AuditEvent",
    "Base",
    "IdempotencyRecord",
    "OidcIdentity",
    "OwLink",
    "ServerSession",
    "SHA256_HEX_LENGTH",
    "VerificationRunControl",
    "hash_session_token",
    "validate_iana_timezone",
    "validate_technical_reference",
    "utc_now",
]
