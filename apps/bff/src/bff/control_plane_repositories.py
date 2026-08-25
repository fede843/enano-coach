"""Typed repositories for the BFF technical control plane.

These repositories persist identity, ownership, session, audit, idempotency,
and verification control records only.  They return immutable views instead of
SQLAlchemy models and do not retain health payloads, OIDC tokens, or raw session
tokens.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .control_plane import (
    ALLOWED_APP_USER_ROLES,
    ALLOWED_APP_USER_STATUSES,
    ALLOWED_AUDIT_ACTIONS,
    ALLOWED_AUDIT_RESULTS,
    ALLOWED_AUDIT_TARGET_TYPES,
    ALLOWED_IDEMPOTENCY_SCOPES,
    ALLOWED_OW_LINK_STATUSES,
    ALLOWED_REVOCATION_REASONS,
    ALLOWED_SCOPE_DOMAINS,
    ALLOWED_VERIFICATION_STATES,
    ALLOWED_VERIFICATION_TERMINAL_STATES,
    ALLOWED_WARNING_CODES,
    AppUser,
    AuditEvent,
    IdempotencyRecord,
    OidcIdentity,
    OwLink,
    ServerSession,
    VerificationRunControl,
    hash_session_token,
    utc_now,
    validate_iana_timezone,
    validate_technical_reference,
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_AUDIT_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PLACEHOLDER_DIGESTS = frozenset(
    {
        "deadbeef" * 8,
        "0123456789abcdef" * 4,
        "abcdef0123456789" * 4,
    }
)
IdFactory = Callable[[str], str]


class IdempotencyConflictError(ValueError):
    """Raised when one scoped key is reused for a different request."""


@dataclass(frozen=True, slots=True)
class AppUserRecord:
    id: str
    status: str
    role: str
    display_name_snapshot: str | None
    email_snapshot: str | None
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None
    disabled_at: datetime | None


@dataclass(frozen=True, slots=True)
class OidcIdentityRecord:
    id: str
    app_user_id: str
    issuer: str
    subject: str
    created_at: datetime
    last_seen_at: datetime | None


@dataclass(frozen=True, slots=True)
class OwLinkRecord:
    id: str
    app_user_id: str
    ow_user_ref: str
    status: str
    version: int
    linked_by_ref: str | None
    created_at: datetime
    updated_at: datetime
    linked_at: datetime | None
    unlinked_at: datetime | None


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: str
    app_user_id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    revocation_reason: str | None


@dataclass(frozen=True, slots=True)
class SessionRotation:
    previous: SessionRecord
    current: SessionRecord


@dataclass(frozen=True, slots=True)
class AuditEventRecord:
    id: str
    actor_ref: str | None
    action: str
    target_type: str
    target_ref: str | None
    result: str
    request_ref: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class IdempotencyRecordView:
    id: str
    owner_ref: str
    ow_link_id: str
    claim_nonce: str
    scope: str
    key_digest: str
    request_digest: str
    result_ref: str | None
    state: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    created: bool
    replayed: bool
    claim_nonce: str
    record: IdempotencyRecordView


@dataclass(frozen=True, slots=True)
class VerificationRunRecord:
    run_key: str
    owner_ref: str
    ow_link_id: str
    scope_date: date
    scope_timezone: str
    scope_domains: tuple[str, ...]
    state: str
    records_seen: int | None
    records_accepted: int | None
    records_rejected: int | None
    records_duplicated: int | None
    fields_unsupported: int | None
    warning_codes: tuple[str, ...]
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class _RepositoryContext:
    """Private binding supplied by an active control-plane unit of work."""

    session: Session
    now: Callable[[], datetime]
    id_factory: IdFactory
    is_open: Callable[[], bool]
    invalidate: Callable[[], None]


class _Repository:
    def __init__(
        self,
        context: _RepositoryContext,
        *,
        now: Callable[[], datetime] | None = None,
        id_factory: IdFactory | None = None,
        is_open: Callable[[], bool] | None = None,
        invalidate: Callable[[], None] | None = None,
    ) -> None:
        if not isinstance(context, _RepositoryContext):
            raise TypeError("repositories require a control-plane unit-of-work context")
        if any(value is not None for value in (now, id_factory, is_open, invalidate)):
            raise TypeError("repository context owns its construction callbacks")
        self._session = context.session
        self._now = context.now
        self._id_factory = context.id_factory
        self._is_open = context.is_open
        self._invalidate = context.invalidate

    @property
    def session(self) -> Session:
        if not self._is_open():
            raise RuntimeError("control-plane repository is closed")
        return self._session

    def _timestamp(self, value: datetime | None, *, field_name: str) -> datetime:
        return _aware_utc(self._now() if value is None else value, field_name)

    def _id(self, value: str | None, prefix: str, *, max_length: int = 64) -> str:
        candidate = self._id_factory(prefix) if value is None else value
        return _technical_ref(
            candidate, field_name=f"{prefix}_id", max_length=max_length
        )

    def _require_active_app_user(self, app_user_id: str) -> AppUser:
        normalized_id = _technical_ref(
            app_user_id, field_name="app_user_id", max_length=64
        )
        user = self.session.scalar(
            select(AppUser).where(AppUser.id == normalized_id).with_for_update()
        )
        if user is None or user.status != "active":
            raise ValueError("app_user_id must identify an active app user")
        return user

    def _active_link(self, owner_ref: str, *, for_update: bool) -> OwLink | None:
        normalized_owner = _technical_ref(
            owner_ref, field_name="owner_ref", max_length=128
        )
        statement = (
            select(OwLink)
            .join(AppUser, OwLink.app_user_id == AppUser.id)
            .where(
                AppUser.id == normalized_owner,
                AppUser.status == "active",
                OwLink.status == "active",
            )
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def _active_owner(self, owner_ref: str, *, for_update: bool) -> AppUser | None:
        normalized_owner = _technical_ref(
            owner_ref, field_name="owner_ref", max_length=128
        )
        statement = (
            select(AppUser)
            .join(OwLink, OwLink.app_user_id == AppUser.id)
            .where(
                AppUser.id == normalized_owner,
                AppUser.status == "active",
                OwLink.status == "active",
            )
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def _require_active_binding(self, owner_ref: str) -> tuple[str, OwLink]:
        normalized_owner = _technical_ref(
            owner_ref, field_name="owner_ref", max_length=128
        )
        link = self._active_link(normalized_owner, for_update=True)
        if link is None:
            raise ValueError(
                "owner_ref must identify an active user with an active OW link"
            )
        return normalized_owner, link

    def _active_link_for_owner(
        self, owner_ref: str, ow_link_id: str, *, for_update: bool
    ) -> OwLink | None:
        normalized_owner = _technical_ref(
            owner_ref, field_name="owner_ref", max_length=128
        )
        normalized_link = _technical_ref(
            ow_link_id, field_name="ow_link_id", max_length=64
        )
        statement = (
            select(OwLink)
            .join(AppUser, OwLink.app_user_id == AppUser.id)
            .where(
                OwLink.id == normalized_link,
                OwLink.app_user_id == normalized_owner,
                OwLink.status == "active",
                AppUser.status == "active",
            )
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def _require_active_owner(self, owner_ref: str) -> str:
        normalized_owner, _ = self._require_active_binding(owner_ref)
        return normalized_owner

    def _record_audit(
        self,
        *,
        action: str,
        target_type: str,
        target_ref: str | None,
        result: str = "success",
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> None:
        """Write the mutation audit row in this repository transaction."""

        try:
            event = AuditEvent(
                id=self._id(None, "audit-event"),
                actor_ref=_audit_ref(actor_ref, "actor_ref", 128),
                action=_allowlisted(action, ALLOWED_AUDIT_ACTIONS, "action"),
                target_type=_allowlisted(
                    target_type, ALLOWED_AUDIT_TARGET_TYPES, "target_type"
                ),
                target_ref=_audit_ref(target_ref, "target_ref", 128),
                result=_allowlisted(result, ALLOWED_AUDIT_RESULTS, "result"),
                request_ref=_audit_ref(request_ref, "request_ref", 128),
                occurred_at=self._timestamp(None, field_name="occurred_at"),
            )
            self.session.add(event)
            self.session.flush()
        except Exception:
            self._invalidate()
            raise

    def _invalidate_user_sessions(
        self,
        app_user_id: str,
        *,
        revoked_at: datetime,
        reason: str = "account_blocked",
    ) -> None:
        sessions = self.session.scalars(
            select(ServerSession)
            .where(
                ServerSession.app_user_id == app_user_id,
                ServerSession.revoked_at.is_(None),
            )
            .with_for_update()
        ).all()
        for session in sessions:
            session.revoked_at = max(revoked_at, _as_utc(session.created_at))
            session.revocation_reason = reason
        self.session.flush()


class AppUserRepository(_Repository):
    """Persist and retrieve local application identities and roles."""

    def create(
        self,
        *,
        user_id: str | None = None,
        status: str = "pending",
        role: str = "pending",
        display_name_snapshot: str | None = None,
        email_snapshot: str | None = None,
        created_at: datetime | None = None,
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> AppUserRecord:
        created = self._timestamp(created_at, field_name="created_at")
        user = AppUser(
            id=self._id(user_id, "app-user"),
            status=_allowlisted(status, ALLOWED_APP_USER_STATUSES, "status"),
            role=_allowlisted(role, ALLOWED_APP_USER_ROLES, "role"),
            display_name_snapshot=_bounded_text(
                display_name_snapshot,
                field_name="display_name_snapshot",
                max_length=256,
            ),
            email_snapshot=_bounded_text(
                email_snapshot,
                field_name="email_snapshot",
                max_length=320,
            ),
            created_at=created,
            updated_at=created,
        )
        self.session.add(user)
        self.session.flush()
        self._record_audit(
            action="identity.create",
            target_type="app_user",
            target_ref=user.id,
            actor_ref=actor_ref,
            request_ref=request_ref,
        )
        return _app_user_record(user)

    def get(self, user_id: str) -> AppUserRecord | None:
        user = self.session.get(
            AppUser,
            _technical_ref(user_id, field_name="user_id", max_length=64),
        )
        return None if user is None else _app_user_record(user)

    def update_state(
        self,
        user_id: str,
        *,
        status: str,
        role: str,
        updated_at: datetime | None = None,
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> AppUserRecord | None:
        normalized_id = _technical_ref(user_id, field_name="user_id", max_length=64)
        user = self.session.scalar(
            select(AppUser).where(AppUser.id == normalized_id).with_for_update()
        )
        if user is None:
            return None
        status_value = _allowlisted(status, ALLOWED_APP_USER_STATUSES, "status")
        role_value = _allowlisted(role, ALLOWED_APP_USER_ROLES, "role")
        timestamp = self._timestamp(updated_at, field_name="updated_at")
        user.status = status_value
        user.role = role_value
        user.disabled_at = timestamp if status_value == "disabled" else None
        user.updated_at = timestamp
        if status_value in {"blocked", "disabled"}:
            self._invalidate_user_sessions(normalized_id, revoked_at=timestamp)
        self.session.flush()
        self._record_audit(
            action="identity.update",
            target_type="app_user",
            target_ref=user.id,
            actor_ref=actor_ref,
            request_ref=request_ref,
        )
        return _app_user_record(user)

    def record_login(
        self,
        user_id: str,
        *,
        logged_in_at: datetime | None = None,
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> AppUserRecord | None:
        user = self.session.get(
            AppUser,
            _technical_ref(user_id, field_name="user_id", max_length=64),
        )
        if user is None:
            return None
        timestamp = self._timestamp(logged_in_at, field_name="logged_in_at")
        user.last_login_at = timestamp
        user.updated_at = timestamp
        self.session.flush()
        self._record_audit(
            action="auth.login",
            target_type="app_user",
            target_ref=user.id,
            actor_ref=actor_ref or user.id,
            request_ref=request_ref,
        )
        return _app_user_record(user)


class OidcIdentityRepository(_Repository):
    """Resolve identities only by the stable issuer/subject pair."""

    def create(
        self,
        *,
        app_user_id: str,
        issuer: str,
        subject: str,
        identity_id: str | None = None,
        created_at: datetime | None = None,
        last_seen_at: datetime | None = None,
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> OidcIdentityRecord:
        created = self._timestamp(created_at, field_name="created_at")
        identity = OidcIdentity(
            id=self._id(identity_id, "oidc-identity"),
            app_user_id=_technical_ref(
                app_user_id, field_name="app_user_id", max_length=64
            ),
            issuer=_opaque_ref(issuer, field_name="issuer", max_length=2048),
            subject=_opaque_ref(subject, field_name="subject", max_length=512),
            created_at=created,
            last_seen_at=(
                None
                if last_seen_at is None
                else _aware_utc(last_seen_at, "last_seen_at")
            ),
        )
        self.session.add(identity)
        self.session.flush()
        self._record_audit(
            action="identity.create",
            target_type="oidc_identity",
            target_ref=identity.id,
            actor_ref=actor_ref or identity.app_user_id,
            request_ref=request_ref,
        )
        return _oidc_identity_record(identity)

    def get(self, identity_id: str) -> OidcIdentityRecord | None:
        identity = self.session.get(
            OidcIdentity,
            _technical_ref(identity_id, field_name="identity_id", max_length=64),
        )
        return None if identity is None else _oidc_identity_record(identity)

    def get_by_issuer_subject(
        self,
        issuer: str,
        subject: str,
    ) -> OidcIdentityRecord | None:
        identity = self.session.scalar(
            select(OidcIdentity).where(
                OidcIdentity.issuer
                == _opaque_ref(issuer, field_name="issuer", max_length=2048),
                OidcIdentity.subject
                == _opaque_ref(subject, field_name="subject", max_length=512),
            )
        )
        return None if identity is None else _oidc_identity_record(identity)

    def mark_seen(
        self,
        identity_id: str,
        *,
        seen_at: datetime | None = None,
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> OidcIdentityRecord | None:
        identity = self.session.get(
            OidcIdentity,
            _technical_ref(identity_id, field_name="identity_id", max_length=64),
        )
        if identity is None:
            return None
        identity.last_seen_at = self._timestamp(seen_at, field_name="seen_at")
        self.session.flush()
        self._record_audit(
            action="identity.update",
            target_type="oidc_identity",
            target_ref=identity.id,
            actor_ref=actor_ref or identity.app_user_id,
            request_ref=request_ref,
        )
        return _oidc_identity_record(identity)


class OwLinkRepository(_Repository):
    """Manage explicit, versioned ownership links without health data."""

    def create(
        self,
        *,
        app_user_id: str,
        ow_user_ref: str,
        status: str,
        version: int,
        link_id: str | None = None,
        linked_by_ref: str | None = None,
        created_at: datetime | None = None,
        linked_at: datetime | None = None,
        unlinked_at: datetime | None = None,
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> OwLinkRecord:
        created = self._timestamp(created_at, field_name="created_at")
        status_value = _allowlisted(status, ALLOWED_OW_LINK_STATUSES, "status")
        if status_value == "active":
            self._require_active_app_user(app_user_id)
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValueError("version must be a positive integer")
        if status_value == "active":
            effective_linked_at = (
                created if linked_at is None else _aware_utc(linked_at, "linked_at")
            )
            effective_unlinked_at = None
        elif status_value in {"revoked", "blocked"}:
            effective_linked_at = (
                None if linked_at is None else _aware_utc(linked_at, "linked_at")
            )
            effective_unlinked_at = (
                created
                if unlinked_at is None
                else _aware_utc(unlinked_at, "unlinked_at")
            )
        else:
            effective_linked_at = (
                None if linked_at is None else _aware_utc(linked_at, "linked_at")
            )
            effective_unlinked_at = (
                None if unlinked_at is None else _aware_utc(unlinked_at, "unlinked_at")
            )

        link = OwLink(
            id=self._id(link_id, "ow-link"),
            app_user_id=_technical_ref(
                app_user_id, field_name="app_user_id", max_length=64
            ),
            ow_user_ref=_technical_ref(
                ow_user_ref, field_name="ow_user_ref", max_length=128
            ),
            status=status_value,
            version=version,
            linked_by_ref=_optional_ref(linked_by_ref, "linked_by_ref", 128),
            created_at=created,
            updated_at=created,
            linked_at=effective_linked_at,
            unlinked_at=effective_unlinked_at,
        )
        self.session.add(link)
        self.session.flush()
        self._record_audit(
            action="ow_link.attach",
            target_type="ow_link",
            target_ref=link.id,
            actor_ref=actor_ref or link.linked_by_ref or link.app_user_id,
            request_ref=request_ref,
        )
        return _ow_link_record(link)

    def get(self, link_id: str) -> OwLinkRecord | None:
        link = self.session.scalar(
            select(OwLink)
            .join(AppUser, OwLink.app_user_id == AppUser.id)
            .where(
                OwLink.id
                == _technical_ref(link_id, field_name="link_id", max_length=64),
                AppUser.status == "active",
            )
        )
        return None if link is None else _ow_link_record(link)

    def get_active_for_app_user(self, app_user_id: str) -> OwLinkRecord | None:
        link = self._active_link(
            _technical_ref(app_user_id, field_name="app_user_id", max_length=64),
            for_update=False,
        )
        return None if link is None else _ow_link_record(link)

    def get_active_for_ow_user(self, ow_user_ref: str) -> OwLinkRecord | None:
        link = self.session.scalar(
            select(OwLink)
            .join(AppUser, OwLink.app_user_id == AppUser.id)
            .where(
                OwLink.ow_user_ref
                == _technical_ref(
                    ow_user_ref, field_name="ow_user_ref", max_length=128
                ),
                OwLink.status == "active",
                AppUser.status == "active",
            )
        )
        return None if link is None else _ow_link_record(link)

    def revoke(
        self,
        *,
        app_user_id: str,
        link_id: str,
        unlinked_at: datetime | None = None,
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> OwLinkRecord | None:
        link = self.session.scalar(
            select(OwLink)
            .join(AppUser, OwLink.app_user_id == AppUser.id)
            .where(
                OwLink.id
                == _technical_ref(link_id, field_name="link_id", max_length=64),
                OwLink.app_user_id
                == _technical_ref(app_user_id, field_name="app_user_id", max_length=64),
                OwLink.status == "active",
                AppUser.status == "active",
            )
            .with_for_update()
        )
        if link is None:
            return None
        timestamp = self._timestamp(unlinked_at, field_name="unlinked_at")
        link.status = "revoked"
        link.updated_at = timestamp
        link.unlinked_at = timestamp
        self._invalidate_user_sessions(
            link.app_user_id,
            revoked_at=timestamp,
            reason="ow_unlink",
        )
        self.session.flush()
        self._record_audit(
            action="ow_link.detach",
            target_type="ow_link",
            target_ref=link.id,
            actor_ref=actor_ref or link.app_user_id,
            request_ref=request_ref,
        )
        return _ow_link_record(link)


class SessionRepository(_Repository):
    """Create and resolve server sessions through SHA-256 digests only."""

    def create(
        self,
        *,
        app_user_id: str,
        raw_token: str | bytes,
        expires_in: timedelta,
        session_id: str | None = None,
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> SessionRecord:
        created = self._timestamp(None, field_name="server_now")
        normalized_user_id = _technical_ref(
            app_user_id, field_name="app_user_id", max_length=64
        )
        if self._active_owner(normalized_user_id, for_update=True) is None:
            raise ValueError(
                "app_user_id must identify an active user with an active OW link"
            )
        effective_expires = _expires_at(created, expires_in)
        session = ServerSession(
            id=self._id(session_id, "session"),
            app_user_id=normalized_user_id,
            session_hash=hash_session_token(raw_token),
            created_at=created,
            last_seen_at=created,
            expires_at=effective_expires,
        )
        self.session.add(session)
        self.session.flush()
        self._record_audit(
            action="session.create",
            target_type="session",
            target_ref=session.id,
            actor_ref=actor_ref or session.app_user_id,
            request_ref=request_ref,
        )
        return _session_record(session)

    def get_active_by_token(
        self,
        raw_token: str | bytes,
    ) -> SessionRecord | None:
        timestamp = self._timestamp(None, field_name="server_now")
        session = self.session.scalar(
            select(ServerSession)
            .join(AppUser, ServerSession.app_user_id == AppUser.id)
            .join(OwLink, OwLink.app_user_id == AppUser.id)
            .where(
                ServerSession.session_hash == hash_session_token(raw_token),
                ServerSession.revoked_at.is_(None),
                ServerSession.expires_at > timestamp,
                AppUser.status == "active",
                OwLink.status == "active",
            )
        )
        return None if session is None else _session_record(session)

    def revoke(
        self,
        *,
        raw_token: str | bytes,
        reason: str,
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> SessionRecord | None:
        timestamp = self._timestamp(None, field_name="server_now")
        reason_value = _allowlisted(reason, ALLOWED_REVOCATION_REASONS, "reason")
        session = self.session.scalar(
            select(ServerSession)
            .where(
                ServerSession.session_hash == hash_session_token(raw_token),
                ServerSession.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if session is None:
            return None
        if timestamp < _as_utc(session.created_at):
            raise ValueError("revoked_at must not precede created_at")
        session.revoked_at = timestamp
        session.revocation_reason = reason_value
        self.session.flush()
        self._record_audit(
            action="session.revoke",
            target_type="session",
            target_ref=session.id,
            actor_ref=actor_ref or session.app_user_id,
            request_ref=request_ref,
        )
        return _session_record(session)

    def rotate(
        self,
        *,
        raw_token: str | bytes,
        replacement_raw_token: str | bytes,
        expires_in: timedelta,
        session_id: str | None = None,
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> SessionRotation | None:
        timestamp = self._timestamp(None, field_name="server_now")
        previous_hash = hash_session_token(raw_token)
        replacement_hash = hash_session_token(replacement_raw_token)
        if previous_hash == replacement_hash:
            raise ValueError("replacement session token must be different")
        previous = self.session.scalar(
            select(ServerSession)
            .join(AppUser, ServerSession.app_user_id == AppUser.id)
            .join(OwLink, OwLink.app_user_id == AppUser.id)
            .where(
                ServerSession.session_hash == previous_hash,
                ServerSession.revoked_at.is_(None),
                ServerSession.expires_at > timestamp,
                AppUser.status == "active",
                OwLink.status == "active",
            )
            .with_for_update()
        )
        if previous is None:
            return None
        effective_expires = _expires_at(timestamp, expires_in)

        previous.revoked_at = timestamp
        previous.revocation_reason = "security_event"
        current = ServerSession(
            id=self._id(session_id, "session"),
            app_user_id=previous.app_user_id,
            session_hash=replacement_hash,
            created_at=timestamp,
            last_seen_at=timestamp,
            expires_at=effective_expires,
        )
        self.session.add(current)
        self.session.flush()
        self._record_audit(
            action="session.revoke",
            target_type="session",
            target_ref=previous.id,
            actor_ref=actor_ref or previous.app_user_id,
            request_ref=request_ref,
        )
        self._record_audit(
            action="session.create",
            target_type="session",
            target_ref=current.id,
            actor_ref=actor_ref or current.app_user_id,
            request_ref=request_ref,
        )
        return SessionRotation(
            previous=_session_record(previous),
            current=_session_record(current),
        )


class AuditEventRepository(_Repository):
    """Persist only allowlisted, PII-free audit event fields."""

    def record(
        self,
        *,
        action: str,
        target_type: str,
        result: str,
        event_id: str | None = None,
        actor_ref: str | None = None,
        target_ref: str | None = None,
        request_ref: str | None = None,
        occurred_at: datetime | None = None,
    ) -> AuditEventRecord:
        try:
            event = AuditEvent(
                id=self._id(event_id, "audit-event"),
                actor_ref=_audit_ref(actor_ref, "actor_ref", 128),
                action=_allowlisted(action, ALLOWED_AUDIT_ACTIONS, "action"),
                target_type=_allowlisted(
                    target_type, ALLOWED_AUDIT_TARGET_TYPES, "target_type"
                ),
                target_ref=_audit_ref(target_ref, "target_ref", 128),
                result=_allowlisted(result, ALLOWED_AUDIT_RESULTS, "result"),
                request_ref=_audit_ref(request_ref, "request_ref", 128),
                occurred_at=self._timestamp(occurred_at, field_name="occurred_at"),
            )
            self.session.add(event)
            self.session.flush()
            return _audit_event_record(event)
        except Exception:
            self._invalidate()
            raise

    def get(self, event_id: str) -> AuditEventRecord | None:
        event = self.session.get(
            AuditEvent,
            _technical_ref(event_id, field_name="event_id", max_length=64),
        )
        return None if event is None else _audit_event_record(event)


class IdempotencyRepository(_Repository):
    """Claim and finalize idempotent operations within an owner and scope."""

    def _expire_if_due(
        self,
        record: IdempotencyRecord,
        *,
        timestamp: datetime,
        actor_ref: str | None,
        request_ref: str | None,
    ) -> bool:
        if record.state == "expired":
            return True
        if _as_utc(record.expires_at) > timestamp:
            return False
        record.state = "expired"
        record.result_ref = None
        record.completed_at = None
        record.updated_at = timestamp
        self.session.flush()
        self._record_audit(
            action="verification.run.update",
            target_type="idempotency_record",
            target_ref=record.id,
            result="failure",
            actor_ref=actor_ref,
            request_ref=request_ref,
        )
        return True

    def begin(
        self,
        *,
        owner_ref: str,
        scope: str,
        key: str | bytes,
        scope_date: date,
        scope_timezone: str,
        scope_domains: Iterable[str],
        expires_in: timedelta,
        record_id: str | None = None,
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> IdempotencyClaim:
        owner, link = self._require_active_binding(owner_ref)
        scope_value = _allowlisted(scope, ALLOWED_IDEMPOTENCY_SCOPES, "scope")
        key_digest = digest_idempotency_key(key)
        request_digest_value = digest_verification_request(
            scope_date=scope_date,
            scope_timezone=scope_timezone,
            scope_domains=scope_domains,
        )
        timestamp = self._timestamp(None, field_name="server_now")
        effective_expires = _expires_at(timestamp, expires_in)

        existing = self._find(owner, link.id, scope_value, key_digest, for_update=True)
        if existing is not None:
            return self._claim_existing(
                existing,
                request_digest=request_digest_value,
                timestamp=timestamp,
                expires_at=effective_expires,
                actor_ref=actor_ref or owner,
                request_ref=request_ref,
            )

        record = IdempotencyRecord(
            id=self._id(record_id, "idempotency"),
            owner_ref=owner,
            ow_link_id=link.id,
            claim_nonce=_new_claim_nonce(),
            scope=scope_value,
            key_digest=key_digest,
            request_digest=request_digest_value,
            state="pending",
            created_at=timestamp,
            updated_at=timestamp,
            expires_at=effective_expires,
        )
        try:
            with self.session.begin_nested():
                self.session.add(record)
                self.session.flush()
        except IntegrityError:
            existing = self._find(
                owner, link.id, scope_value, key_digest, for_update=True
            )
            if existing is None:
                raise
            return self._claim_existing(
                existing,
                request_digest=request_digest_value,
                timestamp=timestamp,
                expires_at=effective_expires,
                actor_ref=actor_ref or owner,
                request_ref=request_ref,
            )
        self._record_audit(
            action="verification.run.create",
            target_type="idempotency_record",
            target_ref=record.id,
            actor_ref=actor_ref or owner,
            request_ref=request_ref,
        )
        return IdempotencyClaim(
            created=True,
            replayed=False,
            claim_nonce=record.claim_nonce,
            record=_idempotency_record(record),
        )

    def complete(
        self,
        *,
        owner_ref: str,
        record_id: str,
        ow_link_id: str,
        claim_nonce: str,
        scope: str,
        key: str | bytes,
        scope_date: date,
        scope_timezone: str,
        scope_domains: Iterable[str],
        state: str,
        result_ref: str | None = None,
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> IdempotencyRecordView:
        if state not in {"completed", "failed"}:
            raise ValueError("idempotency completion requires a terminal state")
        owner = _technical_ref(owner_ref, field_name="owner_ref", max_length=128)
        link_id = _technical_ref(ow_link_id, field_name="ow_link_id", max_length=64)
        nonce = _claim_nonce(claim_nonce)
        if self._active_link_for_owner(owner, link_id, for_update=True) is None:
            raise IdempotencyConflictError(
                "idempotency claim binding is no longer active"
            )
        scope_value = _allowlisted(scope, ALLOWED_IDEMPOTENCY_SCOPES, "scope")
        key_digest = digest_idempotency_key(key)
        request_digest_value = digest_verification_request(
            scope_date=scope_date,
            scope_timezone=scope_timezone,
            scope_domains=scope_domains,
        )
        record = self._find_for_completion(
            record_id=_technical_ref(record_id, field_name="record_id", max_length=64),
            owner_ref=owner,
            ow_link_id=link_id,
            claim_nonce=nonce,
            scope=scope_value,
            key_digest=key_digest,
        )
        if record is None:
            raise IdempotencyConflictError("idempotency claim is not valid")
        if record.request_digest != request_digest_value:
            raise IdempotencyConflictError(
                "idempotency request conflicts with existing record"
            )
        result = _optional_ref(result_ref, "result_ref", 128)
        timestamp = self._timestamp(None, field_name="server_now")
        if self._expire_if_due(
            record,
            timestamp=timestamp,
            actor_ref=actor_ref or owner,
            request_ref=request_ref,
        ):
            raise ValueError("idempotency record has expired")
        if record.state in {"completed", "failed"}:
            if record.state != state or record.result_ref != result:
                raise IdempotencyConflictError(
                    "idempotency record has already been finalized"
                )
            return _idempotency_record(record)

        record.state = state
        record.result_ref = result
        record.completed_at = timestamp
        record.updated_at = timestamp
        self.session.flush()
        self._record_audit(
            action="verification.run.update",
            target_type="idempotency_record",
            target_ref=record.id,
            actor_ref=actor_ref or owner,
            request_ref=request_ref,
        )
        return _idempotency_record(record)

    def get(
        self,
        *,
        owner_ref: str,
        scope: str,
        key: str | bytes,
    ) -> IdempotencyRecordView | None:
        owner = _technical_ref(owner_ref, field_name="owner_ref", max_length=128)
        scope_value = _allowlisted(scope, ALLOWED_IDEMPOTENCY_SCOPES, "scope")
        link = self._active_link(owner, for_update=True)
        if link is None:
            return None
        record = self._find(
            owner, link.id, scope_value, digest_idempotency_key(key), for_update=True
        )
        if record is None:
            return None
        timestamp = self._timestamp(None, field_name="server_now")
        self._expire_if_due(
            record,
            timestamp=timestamp,
            actor_ref=owner,
            request_ref=None,
        )
        return _idempotency_record(record)

    def _find(
        self,
        owner_ref: str,
        ow_link_id: str,
        scope: str,
        key_digest: str,
        *,
        for_update: bool,
    ) -> IdempotencyRecord | None:
        statement = select(IdempotencyRecord).where(
            IdempotencyRecord.owner_ref == owner_ref,
            IdempotencyRecord.ow_link_id == ow_link_id,
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.key_digest == key_digest,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def _find_for_completion(
        self,
        *,
        record_id: str,
        owner_ref: str,
        ow_link_id: str,
        claim_nonce: str,
        scope: str,
        key_digest: str,
    ) -> IdempotencyRecord | None:
        statement = select(IdempotencyRecord).where(
            IdempotencyRecord.id == record_id,
            IdempotencyRecord.owner_ref == owner_ref,
            IdempotencyRecord.ow_link_id == ow_link_id,
            IdempotencyRecord.claim_nonce == claim_nonce,
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.key_digest == key_digest,
        )
        return self.session.scalar(statement.with_for_update())

    def _claim_existing(
        self,
        record: IdempotencyRecord,
        *,
        request_digest: str,
        timestamp: datetime,
        expires_at: datetime,
        actor_ref: str | None,
        request_ref: str | None,
    ) -> IdempotencyClaim:
        if self._expire_if_due(
            record,
            timestamp=timestamp,
            actor_ref=actor_ref,
            request_ref=request_ref,
        ):
            record.claim_nonce = _new_claim_nonce()
            record.request_digest = request_digest
            record.result_ref = None
            record.state = "pending"
            record.updated_at = timestamp
            record.expires_at = expires_at
            record.completed_at = None
            self.session.flush()
            self._record_audit(
                action="verification.run.update",
                target_type="idempotency_record",
                target_ref=record.id,
                actor_ref=actor_ref,
                request_ref=request_ref,
            )
            return IdempotencyClaim(
                created=False,
                replayed=False,
                claim_nonce=record.claim_nonce,
                record=_idempotency_record(record),
            )
        if record.request_digest != request_digest:
            raise IdempotencyConflictError(
                "idempotency request conflicts with existing record"
            )
        return IdempotencyClaim(
            created=False,
            replayed=record.state in {"completed", "failed"},
            claim_nonce=record.claim_nonce,
            record=_idempotency_record(record),
        )


class VerificationRunRepository(_Repository):
    """Persist and read BFF-owned verification control aggregates only."""

    def create(
        self,
        *,
        owner_ref: str,
        scope_date: date,
        scope_timezone: str,
        scope_domains: Iterable[str],
        state: str = "pending",
        run_key: str | None = None,
        records_seen: int | None = None,
        records_accepted: int | None = None,
        records_rejected: int | None = None,
        records_duplicated: int | None = None,
        fields_unsupported: int | None = None,
        warning_codes: Iterable[str] = (),
        requested_at: datetime | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> VerificationRunRecord:
        if not isinstance(scope_date, date) or isinstance(scope_date, datetime):
            raise TypeError("scope_date must be a date")
        owner, link = self._require_active_binding(owner_ref)
        domains = _allowlisted_csv(
            scope_domains,
            allowed=ALLOWED_SCOPE_DOMAINS,
            field_name="scope_domains",
            allow_empty=False,
        )
        warnings = _allowlisted_csv(
            warning_codes,
            allowed=ALLOWED_WARNING_CODES,
            field_name="warning_codes",
            allow_empty=True,
        )
        counts = {
            "records_seen": records_seen,
            "records_accepted": records_accepted,
            "records_rejected": records_rejected,
            "records_duplicated": records_duplicated,
            "fields_unsupported": fields_unsupported,
        }
        _validate_verification_counters(counts)
        requested = self._timestamp(requested_at, field_name="requested_at")
        started = None if started_at is None else _aware_utc(started_at, "started_at")
        finished = (
            None if finished_at is None else _aware_utc(finished_at, "finished_at")
        )
        if started is not None and started < requested:
            raise ValueError("started_at must not precede requested_at")
        if finished is not None and (started is None or finished < started):
            raise ValueError("finished_at must follow started_at")
        state_value = _allowlisted(state, ALLOWED_VERIFICATION_STATES, "state")
        if state_value == "pending":
            if (
                started is not None
                or finished is not None
                or any(value is not None for value in counts.values())
                or warnings
            ):
                raise ValueError(
                    "pending verification cannot include terminal timestamps "
                    "or counters"
                )
        elif state_value in ALLOWED_VERIFICATION_TERMINAL_STATES:
            if started is None or finished is None:
                raise ValueError(
                    "terminal verification requires started_at and finished_at"
                )

        run = VerificationRunControl(
            run_key=_technical_ref(
                (
                    run_key
                    if run_key is not None
                    else self._id(None, "verification-run", max_length=128)
                ),
                field_name="run_key",
                max_length=128,
            ),
            owner_ref=owner,
            ow_link_id=link.id,
            scope_date=scope_date,
            scope_timezone=validate_iana_timezone(
                scope_timezone, field_name="scope_timezone"
            ),
            scope_domains=domains,
            state=state_value,
            records_seen=records_seen,
            records_accepted=records_accepted,
            records_rejected=records_rejected,
            records_duplicated=records_duplicated,
            fields_unsupported=fields_unsupported,
            warning_codes=warnings,
            requested_at=requested,
            started_at=started,
            finished_at=finished,
            created_at=requested,
            updated_at=requested,
        )
        self.session.add(run)
        self.session.flush()
        self._record_audit(
            action="verification.run.create",
            target_type="verification_run",
            target_ref=run.run_key,
            actor_ref=actor_ref or owner,
            request_ref=request_ref,
        )
        return _verification_run_record(run)

    def get(self, run_key: str, owner_ref: str) -> VerificationRunRecord | None:
        normalized_owner = _technical_ref(
            owner_ref, field_name="owner_ref", max_length=128
        )
        link = self._active_link(normalized_owner, for_update=False)
        if link is None:
            return None
        run = self.session.scalar(
            select(VerificationRunControl).where(
                VerificationRunControl.run_key
                == _technical_ref(run_key, field_name="run_key", max_length=128),
                VerificationRunControl.owner_ref == normalized_owner,
                VerificationRunControl.ow_link_id == link.id,
            )
        )
        if run is None:
            return None
        return _verification_run_record(run)

    def transition(
        self,
        *,
        run_key: str,
        owner_ref: str,
        state: str,
        records_seen: int | None = None,
        records_accepted: int | None = None,
        records_rejected: int | None = None,
        records_duplicated: int | None = None,
        fields_unsupported: int | None = None,
        warning_codes: Iterable[str] | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        updated_at: datetime | None = None,
        actor_ref: str | None = None,
        request_ref: str | None = None,
    ) -> VerificationRunRecord | None:
        """Apply one locked, forward-only state transition."""

        normalized_owner = _technical_ref(
            owner_ref, field_name="owner_ref", max_length=128
        )
        link = self._active_link(normalized_owner, for_update=True)
        if link is None:
            return None
        run = self.session.scalar(
            select(VerificationRunControl)
            .where(
                VerificationRunControl.run_key
                == _technical_ref(run_key, field_name="run_key", max_length=128),
                VerificationRunControl.owner_ref == normalized_owner,
                VerificationRunControl.ow_link_id == link.id,
            )
            .with_for_update()
        )
        if run is None:
            return None
        if run.state in ALLOWED_VERIFICATION_TERMINAL_STATES:
            raise ValueError("terminal verification cannot transition")

        state_value = _allowlisted(state, ALLOWED_VERIFICATION_STATES, "state")
        new_started = (
            None
            if run.started_at is None and started_at is None
            else (
                _aware_utc(started_at, "started_at")
                if started_at is not None
                else _as_utc(run.started_at)
            )
        )
        new_finished = (
            None
            if finished_at is None and run.finished_at is None
            else (
                _as_utc(run.finished_at)
                if finished_at is None
                else _aware_utc(finished_at, "finished_at")
            )
        )
        if new_started is not None and new_started < _as_utc(run.requested_at):
            raise ValueError("started_at must not precede requested_at")
        if new_finished is not None and (
            new_started is None or new_finished < new_started
        ):
            raise ValueError("finished_at must follow started_at")
        if state_value == "pending" and new_finished is not None:
            raise ValueError("pending verification cannot have finished_at")
        if state_value != "pending" and (new_started is None or new_finished is None):
            raise ValueError(
                "terminal verification requires started_at and finished_at"
            )

        new_counts = {
            "records_seen": run.records_seen if records_seen is None else records_seen,
            "records_accepted": (
                run.records_accepted if records_accepted is None else records_accepted
            ),
            "records_rejected": (
                run.records_rejected if records_rejected is None else records_rejected
            ),
            "records_duplicated": (
                run.records_duplicated
                if records_duplicated is None
                else records_duplicated
            ),
            "fields_unsupported": (
                run.fields_unsupported
                if fields_unsupported is None
                else fields_unsupported
            ),
        }
        _validate_verification_counters(new_counts)
        for field_name, value in new_counts.items():
            previous = getattr(run, field_name)
            if previous is not None and value is not None and value < previous:
                raise ValueError(f"{field_name} counter cannot decrease")

        warnings = (
            run.warning_codes
            if warning_codes is None
            else _allowlisted_csv(
                warning_codes,
                allowed=ALLOWED_WARNING_CODES,
                field_name="warning_codes",
                allow_empty=True,
            )
        )
        timestamp = self._timestamp(updated_at, field_name="updated_at")
        run.state = state_value
        run.records_seen = new_counts["records_seen"]
        run.records_accepted = new_counts["records_accepted"]
        run.records_rejected = new_counts["records_rejected"]
        run.records_duplicated = new_counts["records_duplicated"]
        run.fields_unsupported = new_counts["fields_unsupported"]
        run.warning_codes = warnings
        run.started_at = new_started
        run.finished_at = new_finished
        run.updated_at = timestamp
        self.session.flush()
        self._record_audit(
            action="verification.run.update",
            target_type="verification_run",
            target_ref=run.run_key,
            actor_ref=actor_ref or normalized_owner,
            request_ref=request_ref,
        )
        return _verification_run_record(run)


class ControlPlaneRepositories:
    """Repository bundle bound to one unit-of-work session."""

    def __init__(
        self,
        session: Session,
        *,
        now: Callable[[], datetime] | None = None,
        id_factory: IdFactory | None = None,
        is_open: Callable[[], bool] | None = None,
        invalidate: Callable[[], None] | None = None,
    ) -> None:
        effective_now = now or utc_now
        effective_id_factory = id_factory or _default_id
        context = _repository_context(
            session,
            now=effective_now,
            id_factory=effective_id_factory,
            is_open=is_open,
            invalidate=invalidate,
        )
        self.app_users = AppUserRepository(
            context,
        )
        self.oidc_identities = OidcIdentityRepository(
            context,
        )
        self.ow_links = OwLinkRepository(
            context,
        )
        self.sessions = SessionRepository(
            context,
        )
        self.audit_events = AuditEventRepository(
            context,
        )
        self.idempotency = IdempotencyRepository(
            context,
        )
        self.verification_runs = VerificationRunRepository(
            context,
        )


def _repository_context(
    session: Session,
    *,
    now: Callable[[], datetime],
    id_factory: IdFactory,
    is_open: Callable[[], bool] | None,
    invalidate: Callable[[], None] | None,
) -> _RepositoryContext:
    """Accept only the callbacks issued by an active private unit of work."""

    if not isinstance(session, Session):
        raise TypeError("repositories require a control-plane unit-of-work context")
    if not callable(is_open) or not callable(invalidate):
        raise TypeError("repositories require a control-plane unit-of-work context")

    owner = getattr(invalidate, "__self__", None)
    if owner is None or getattr(owner, "session", None) is not session:
        raise TypeError("repositories require a control-plane unit-of-work context")
    if getattr(owner, "_active_token", None) is None:
        raise TypeError("repositories require an active unit-of-work context")

    closure_values = tuple(
        cell.cell_contents for cell in (getattr(is_open, "__closure__", None) or ())
    )
    if not any(value is owner for value in closure_values) or not is_open():
        raise TypeError("repositories require a control-plane unit-of-work context")

    return _RepositoryContext(
        session=session,
        now=now,
        id_factory=id_factory,
        is_open=is_open,
        invalidate=invalidate,
    )


def digest_idempotency_key(value: str | bytes) -> str:
    """Hash an opaque idempotency key without retaining the raw value."""

    if isinstance(value, str):
        raw = value.encode("utf-8")
    elif isinstance(value, bytes):
        raw = value
    else:
        raise TypeError("idempotency key must be text or bytes")
    if not raw:
        raise ValueError("idempotency key must not be empty")
    return hashlib.sha256(raw).hexdigest()


def _new_claim_nonce() -> str:
    return secrets.token_hex(32)


def _claim_nonce(value: str) -> str:
    if (
        not isinstance(value, str)
        or _SHA256_PATTERN.fullmatch(value) is None
        or value in _PLACEHOLDER_DIGESTS
        or len(set(value)) == 1
    ):
        raise ValueError("claim_nonce must be a random nonce")
    return value


def _expires_at(now: datetime, expires_in: timedelta) -> datetime:
    if not isinstance(expires_in, timedelta) or expires_in <= timedelta(0):
        raise ValueError("expires_in must be positive")
    try:
        expires_at = now + expires_in
    except OverflowError:
        raise ValueError("expires_in is too large") from None
    if expires_at <= now:
        raise ValueError("expires_in must be positive")
    return expires_at


def digest_verification_request(
    *,
    scope_date: date,
    scope_timezone: str,
    scope_domains: Iterable[str],
) -> str:
    """Hash the canonical verification request without accepting a caller digest."""

    if not isinstance(scope_date, date) or isinstance(scope_date, datetime):
        raise TypeError("scope_date must be a date")
    timezone_name = validate_iana_timezone(scope_timezone, field_name="scope_timezone")
    domains = _allowlisted_csv(
        scope_domains,
        allowed=ALLOWED_SCOPE_DOMAINS,
        field_name="scope_domains",
        allow_empty=False,
    )
    canonical = json.dumps(
        {
            "scopeDate": scope_date.isoformat(),
            "scopeDomains": domains.split(","),
            "scopeTimezone": timezone_name,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _default_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _opaque_ref(value: str, *, field_name: str, max_length: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > max_length
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded opaque reference")
    return value


def _technical_ref(value: str, *, field_name: str, max_length: int) -> str:
    return validate_technical_reference(
        value, field_name=field_name, max_length=max_length
    )


def _optional_ref(value: str | None, field_name: str, max_length: int) -> str | None:
    if value is None:
        return None
    return _technical_ref(value, field_name=field_name, max_length=max_length)


def _audit_ref(value: str | None, field_name: str, max_length: int) -> str | None:
    if value is None:
        return None
    return _technical_ref(value, field_name=field_name, max_length=max_length)


def _bounded_text(
    value: str | None,
    *,
    field_name: str,
    max_length: int,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > max_length:
        raise ValueError(f"{field_name} exceeds its storage limit")
    if any(
        ord(character) < 0x20 and character not in {"\t", "\n"} for character in value
    ):
        raise ValueError(f"{field_name} contains control characters")
    return value


def _allowlisted(value: str, allowed: frozenset[str], field_name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{field_name} is not in the control-plane allowlist")
    return value


def _validate_verification_counters(counts: dict[str, int | None]) -> None:
    for field_name, value in counts.items():
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise ValueError(f"{field_name} must be a non-negative integer")

    records_seen = counts["records_seen"]
    derived_counts = (
        counts["records_accepted"],
        counts["records_rejected"],
        counts["records_duplicated"],
    )
    if records_seen is None and any(value is not None for value in derived_counts):
        raise ValueError("records_seen is required when record counters are present")
    if (
        records_seen is not None
        and sum(value or 0 for value in derived_counts) > records_seen
    ):
        raise ValueError("verification counters must not exceed records_seen")


def _allowlisted_csv(
    values: Iterable[str],
    *,
    allowed: frozenset[str],
    field_name: str,
    allow_empty: bool,
) -> str:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be an iterable of machine values")
    items = tuple(values)
    if not items and allow_empty:
        return ""
    if not items or any(not isinstance(item, str) for item in items):
        raise ValueError(f"{field_name} is not in the control-plane allowlist")
    if len(set(items)) != len(items):
        raise ValueError(f"{field_name} is not in the control-plane allowlist")
    if any(item not in allowed for item in items):
        raise ValueError(f"{field_name} is not in the control-plane allowlist")
    return ",".join(sorted(items))


def _canonical_digest(value: str, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or _SHA256_PATTERN.fullmatch(value) is None
        or value in _PLACEHOLDER_DIGESTS
        or len(set(value)) == 1
    ):
        raise ValueError(f"{field_name} must be a non-placeholder SHA-256 digest")
    return value


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _app_user_record(user: AppUser) -> AppUserRecord:
    return AppUserRecord(
        id=user.id,
        status=user.status,
        role=user.role,
        display_name_snapshot=user.display_name_snapshot,
        email_snapshot=user.email_snapshot,
        created_at=_as_utc(user.created_at),
        updated_at=_as_utc(user.updated_at),
        last_login_at=(
            None if user.last_login_at is None else _as_utc(user.last_login_at)
        ),
        disabled_at=None if user.disabled_at is None else _as_utc(user.disabled_at),
    )


def _oidc_identity_record(identity: OidcIdentity) -> OidcIdentityRecord:
    return OidcIdentityRecord(
        id=identity.id,
        app_user_id=identity.app_user_id,
        issuer=identity.issuer,
        subject=identity.subject,
        created_at=_as_utc(identity.created_at),
        last_seen_at=(
            None if identity.last_seen_at is None else _as_utc(identity.last_seen_at)
        ),
    )


def _ow_link_record(link: OwLink) -> OwLinkRecord:
    return OwLinkRecord(
        id=link.id,
        app_user_id=link.app_user_id,
        ow_user_ref=link.ow_user_ref,
        status=link.status,
        version=link.version,
        linked_by_ref=link.linked_by_ref,
        created_at=_as_utc(link.created_at),
        updated_at=_as_utc(link.updated_at),
        linked_at=None if link.linked_at is None else _as_utc(link.linked_at),
        unlinked_at=None if link.unlinked_at is None else _as_utc(link.unlinked_at),
    )


def _session_record(session: ServerSession) -> SessionRecord:
    return SessionRecord(
        id=session.id,
        app_user_id=session.app_user_id,
        created_at=_as_utc(session.created_at),
        last_seen_at=_as_utc(session.last_seen_at),
        expires_at=_as_utc(session.expires_at),
        revoked_at=None if session.revoked_at is None else _as_utc(session.revoked_at),
        revocation_reason=session.revocation_reason,
    )


def _audit_event_record(event: AuditEvent) -> AuditEventRecord:
    return AuditEventRecord(
        id=event.id,
        actor_ref=event.actor_ref,
        action=event.action,
        target_type=event.target_type,
        target_ref=event.target_ref,
        result=event.result,
        request_ref=event.request_ref,
        occurred_at=_as_utc(event.occurred_at),
    )


def _idempotency_record(record: IdempotencyRecord) -> IdempotencyRecordView:
    return IdempotencyRecordView(
        id=record.id,
        owner_ref=record.owner_ref,
        ow_link_id=record.ow_link_id,
        claim_nonce=record.claim_nonce,
        scope=record.scope,
        key_digest=record.key_digest,
        request_digest=record.request_digest,
        result_ref=record.result_ref,
        state=record.state,
        created_at=_as_utc(record.created_at),
        updated_at=_as_utc(record.updated_at),
        expires_at=_as_utc(record.expires_at),
        completed_at=(
            None if record.completed_at is None else _as_utc(record.completed_at)
        ),
    )


def _verification_run_record(run: VerificationRunControl) -> VerificationRunRecord:
    return VerificationRunRecord(
        run_key=run.run_key,
        owner_ref=run.owner_ref,
        ow_link_id=run.ow_link_id,
        scope_date=run.scope_date,
        scope_timezone=run.scope_timezone,
        scope_domains=tuple(run.scope_domains.split(",")),
        state=run.state,
        records_seen=run.records_seen,
        records_accepted=run.records_accepted,
        records_rejected=run.records_rejected,
        records_duplicated=run.records_duplicated,
        fields_unsupported=run.fields_unsupported,
        warning_codes=tuple(filter(None, run.warning_codes.split(","))),
        requested_at=_as_utc(run.requested_at),
        started_at=None if run.started_at is None else _as_utc(run.started_at),
        finished_at=None if run.finished_at is None else _as_utc(run.finished_at),
        created_at=_as_utc(run.created_at),
        updated_at=_as_utc(run.updated_at),
    )


__all__ = [
    "AppUserRecord",
    "AppUserRepository",
    "AuditEventRecord",
    "AuditEventRepository",
    "ControlPlaneRepositories",
    "IdempotencyClaim",
    "IdempotencyConflictError",
    "IdempotencyRecordView",
    "IdempotencyRepository",
    "OidcIdentityRecord",
    "OidcIdentityRepository",
    "OwLinkRecord",
    "OwLinkRepository",
    "SessionRecord",
    "SessionRepository",
    "SessionRotation",
    "VerificationRunRecord",
    "VerificationRunRepository",
    "digest_idempotency_key",
    "digest_verification_request",
]
