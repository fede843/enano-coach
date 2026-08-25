from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from bff.control_plane import AuditEvent, Base, ServerSession, hash_session_token
from bff.control_plane_config import ControlPlaneSettings
from bff.control_plane_db import (
    ControlPlaneConfigurationError,
    ControlPlaneDisabledError,
    _create_test_control_plane_database,
    create_control_plane_database,
)
from bff.control_plane_db import _ControlPlaneDatabase as ControlPlaneDatabase
from bff.control_plane_repositories import (
    AppUserRepository,
    ControlPlaneRepositories,
    IdempotencyConflictError,
    digest_verification_request,
)

NOW = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock() -> dict[str, datetime]:
    return {"now": NOW}


@pytest.fixture
def database(clock: dict[str, datetime]) -> ControlPlaneDatabase:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    database = _create_test_control_plane_database(engine, now=lambda: clock["now"])
    try:
        yield database
    finally:
        database.dispose()


def _create_active_owner(
    repositories, *, user_id: str = "user-one", link_id: str = "link-one"
) -> None:
    repositories.app_users.create(
        user_id=user_id,
        status="active",
        role="viewer",
    )
    repositories.ow_links.create(
        link_id=link_id,
        app_user_id=user_id,
        ow_user_ref=f"ow-{user_id}",
        status="active",
        version=1,
        linked_at=NOW,
    )


def _request_kwargs(
    *,
    scope_date_value: date = date(2026, 1, 2),
    scope_domains: tuple[str, ...] = ("activity",),
) -> dict[str, object]:
    return {
        "scope_date": scope_date_value,
        "scope_timezone": "UTC",
        "scope_domains": scope_domains,
    }


def test_disabled_control_plane_does_not_create_an_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_engine(*args, **kwargs):
        raise AssertionError("disabled control plane must not create an engine")

    monkeypatch.setattr("bff.control_plane_db.create_engine", unexpected_engine)

    with pytest.raises(ControlPlaneDisabledError):
        create_control_plane_database(ControlPlaneSettings(enabled=False))


def test_unit_of_work_commits_and_rolls_back_on_exception(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        created = unit_of_work.repositories.app_users.create(
            user_id="user-commit",
            status="active",
            role="viewer",
        )

    assert created.id == "user-commit"
    with database.unit_of_work() as unit_of_work:
        assert unit_of_work.repositories.app_users.get("user-commit") is not None

    with pytest.raises(RuntimeError, match="rollback marker"):
        with database.unit_of_work() as unit_of_work:
            unit_of_work.repositories.app_users.create(
                user_id="user-rollback",
                status="active",
                role="viewer",
            )
            raise RuntimeError("rollback marker")

    with database.unit_of_work() as unit_of_work:
        assert unit_of_work.repositories.app_users.get("user-rollback") is None


def test_repository_handle_rejects_use_after_unit_of_work_close(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories

    with pytest.raises(RuntimeError, match="closed"):
        repositories.app_users.get("user-one")


def test_public_repository_constructors_reject_arbitrary_sessions(
    database: ControlPlaneDatabase,
) -> None:
    with Session(database.engine) as session:
        with pytest.raises(TypeError, match="unit-of-work"):
            ControlPlaneRepositories(session)

        with pytest.raises(TypeError, match="unit-of-work"):
            ControlPlaneRepositories(
                session,
                is_open=lambda: True,
                invalidate=lambda: None,
            )

        with pytest.raises(TypeError, match="unit-of-work"):
            AppUserRepository(
                session,
                now=lambda: NOW,
                id_factory=lambda prefix: f"{prefix}-test",
            )


def test_private_test_database_path_provides_repository_context(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        created = unit_of_work.repositories.app_users.create(
            user_id="user-context",
            status="pending",
            role="pending",
        )

    with database.unit_of_work() as unit_of_work:
        assert unit_of_work.repositories.app_users.get(created.id) == created


def test_identity_and_active_link_reads_are_explicitly_owner_scoped(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        repositories.app_users.create(
            user_id="user-one",
            status="active",
            role="viewer",
        )
        repositories.app_users.create(
            user_id="user-two",
            status="active",
            role="viewer",
        )
        identity = repositories.oidc_identities.create(
            identity_id="identity-one",
            app_user_id="user-one",
            issuer="https://issuer.example.test",
            subject="subject-one",
        )
        link = repositories.ow_links.create(
            link_id="link-one",
            app_user_id="user-one",
            ow_user_ref="ow-user-one",
            status="active",
            version=1,
            linked_at=NOW,
        )

    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        assert (
            repositories.oidc_identities.get_by_issuer_subject(
                "https://issuer.example.test", "subject-one"
            )
            == identity
        )
        assert repositories.ow_links.get_active_for_app_user("user-one") == link
        assert repositories.ow_links.get_active_for_app_user("user-two") is None
        assert repositories.ow_links.get_active_for_ow_user("ow-user-one") == link


def test_active_ow_link_creation_preserves_one_active_link_invariant(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        repositories.app_users.create(
            user_id="user-one",
            status="active",
            role="viewer",
        )
        repositories.ow_links.create(
            link_id="link-one",
            app_user_id="user-one",
            ow_user_ref="ow-user-one",
            status="active",
            version=1,
            linked_at=NOW,
        )

    with pytest.raises(IntegrityError):
        with database.unit_of_work() as unit_of_work:
            unit_of_work.repositories.ow_links.create(
                link_id="link-two",
                app_user_id="user-one",
                ow_user_ref="ow-user-two",
                status="active",
                version=2,
                linked_at=NOW,
            )

    with database.unit_of_work() as unit_of_work:
        assert (
            unit_of_work.repositories.ow_links.get_active_for_app_user("user-one").id
            == "link-one"
        )


def test_session_repository_only_stores_hashes_and_rotates_atomically(
    database: ControlPlaneDatabase,
) -> None:
    raw_token = "synthetic-session-token"
    replacement_token = "synthetic-replacement-token"

    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        repositories.app_users.create(
            user_id="user-one",
            status="active",
            role="viewer",
        )
        repositories.ow_links.create(
            link_id="link-one",
            app_user_id="user-one",
            ow_user_ref="ow-user-one",
            status="active",
            version=1,
            linked_at=NOW,
        )
        created = repositories.sessions.create(
            session_id="session-one",
            app_user_id="user-one",
            raw_token=raw_token,
            expires_in=timedelta(hours=1),
        )

    assert raw_token not in repr(created)
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        assert repositories.sessions.get_active_by_token(raw_token) == created
        rotated = repositories.sessions.rotate(
            raw_token=raw_token,
            session_id="session-two",
            replacement_raw_token=replacement_token,
            expires_in=timedelta(hours=1),
        )
        assert rotated.previous.id == "session-one"
        assert rotated.current.id == "session-two"

    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        assert repositories.sessions.get_active_by_token(raw_token) is None
        assert (
            repositories.sessions.get_active_by_token(replacement_token)
            == rotated.current
        )
        stored_hashes = unit_of_work.session.scalars(
            select(ServerSession.session_hash)
        ).all()

    assert hash_session_token(raw_token) in stored_hashes
    assert hash_session_token(replacement_token) in stored_hashes
    assert raw_token not in stored_hashes
    assert replacement_token not in stored_hashes


def test_session_revoke_is_hash_based_and_removes_only_the_selected_session(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        repositories.app_users.create(
            user_id="user-one",
            status="active",
            role="viewer",
        )
        repositories.ow_links.create(
            link_id="link-one",
            app_user_id="user-one",
            ow_user_ref="ow-user-one",
            status="active",
            version=1,
            linked_at=NOW,
        )
        repositories.sessions.create(
            session_id="session-one",
            app_user_id="user-one",
            raw_token="token-one",
            expires_in=timedelta(hours=1),
        )
        repositories.sessions.create(
            session_id="session-two",
            app_user_id="user-one",
            raw_token="token-two",
            expires_in=timedelta(hours=1),
        )
        revoked = repositories.sessions.revoke(
            raw_token="token-one",
            reason="logout",
        )
        assert revoked is not None
        assert revoked.id == "session-one"

    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        assert repositories.sessions.get_active_by_token("token-one") is None
        assert repositories.sessions.get_active_by_token("token-two") is not None


def test_idempotency_is_scoped_and_replays_only_the_same_request_digest(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        _create_active_owner(
            repositories, user_id="owner-one", link_id="link-owner-one"
        )
        _create_active_owner(
            repositories, user_id="owner-two", link_id="link-owner-two"
        )
        first = repositories.idempotency.begin(
            record_id="idempotency-one",
            owner_ref="owner-one",
            scope="verification-run-create",
            key="same-header",
            **_request_kwargs(),
            expires_in=timedelta(minutes=15),
        )
        assert first.created is True
        assert first.replayed is False

        pending_replay = repositories.idempotency.begin(
            record_id="idempotency-unused",
            owner_ref="owner-one",
            scope="verification-run-create",
            key="same-header",
            **_request_kwargs(),
            expires_in=timedelta(minutes=15),
        )
        assert pending_replay.created is False
        assert pending_replay.replayed is False
        assert pending_replay.record.id == "idempotency-one"

        with pytest.raises(IdempotencyConflictError):
            repositories.idempotency.begin(
                record_id="idempotency-conflict",
                owner_ref="owner-one",
                scope="verification-run-create",
                key="same-header",
                **_request_kwargs(scope_date_value=date(2026, 1, 3)),
                expires_in=timedelta(minutes=15),
            )

        other_owner = repositories.idempotency.begin(
            record_id="idempotency-two",
            owner_ref="owner-two",
            scope="verification-run-create",
            key="same-header",
            **_request_kwargs(),
            expires_in=timedelta(minutes=15),
        )
        assert other_owner.created is True

        completed = repositories.idempotency.complete(
            owner_ref="owner-one",
            record_id=first.record.id,
            ow_link_id=first.record.ow_link_id,
            claim_nonce=first.claim_nonce,
            scope="verification-run-create",
            key="same-header",
            **_request_kwargs(),
            state="completed",
            result_ref="run-one",
        )
        assert completed.state == "completed"

        replay = repositories.idempotency.begin(
            record_id="idempotency-unused-again",
            owner_ref="owner-one",
            scope="verification-run-create",
            key="same-header",
            **_request_kwargs(),
            expires_in=timedelta(minutes=15),
        )
        assert replay.created is False
        assert replay.replayed is True
        assert replay.record.result_ref == "run-one"


def test_audit_repository_accepts_only_allowlisted_machine_values(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        event = unit_of_work.repositories.audit_events.record(
            event_id="audit-one",
            actor_ref="user-one",
            action="verification.run.create",
            target_type="verification_run",
            target_ref="run-one",
            result="success",
            request_ref="request-one",
            occurred_at=NOW,
        )
        assert event.id == "audit-one"
        assert not hasattr(event, "message")

        with pytest.raises(ValueError, match="allowlist"):
            unit_of_work.repositories.audit_events.record(
                event_id="audit-two",
                actor_ref="user-one",
                action="provider message",
                target_type="verification_run",
                result="success",
                occurred_at=NOW,
            )


def test_verification_control_is_readable_only_with_the_matching_owner(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        _create_active_owner(
            unit_of_work.repositories, user_id="owner-one", link_id="link-owner-one"
        )
        created = unit_of_work.repositories.verification_runs.create(
            run_key="run-one",
            owner_ref="owner-one",
            scope_date=date(2026, 1, 2),
            scope_timezone="UTC",
            scope_domains=("sources", "activity"),
            state="pending",
            warning_codes=(),
            requested_at=NOW,
        )
        assert created.scope_domains == ("activity", "sources")
        assert created.records_seen is None
        assert not hasattr(created, "results")

    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        assert repositories.verification_runs.get("run-one", "owner-one") == created
        assert repositories.verification_runs.get("run-one", "owner-two") is None


def test_database_from_settings_requires_an_enabled_server_side_postgres_url() -> None:
    settings = ControlPlaneSettings.from_environment(
        {
            "BFF_CONTROL_PLANE_ENABLED": "true",
            "APP_DATABASE_URL": "postgresql+psycopg://database.example.test:5432/control",
        }
    )

    database = create_control_plane_database(settings)
    try:
        assert database.engine.url.drivername == "postgresql+psycopg"
        assert database.engine.url.database == "control"
    finally:
        database.dispose()


@pytest.mark.parametrize("status", ("blocked", "disabled"))
def test_blocked_or_disabled_user_invalidates_all_sessions(
    database: ControlPlaneDatabase, status: str
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        _create_active_owner(repositories)
        repositories.sessions.create(
            session_id="session-one",
            app_user_id="user-one",
            raw_token="token-one",
            expires_in=timedelta(hours=1),
        )
        repositories.sessions.create(
            session_id="session-two",
            app_user_id="user-one",
            raw_token="token-two",
            expires_in=timedelta(hours=1),
        )

    with database.unit_of_work() as unit_of_work:
        updated = unit_of_work.repositories.app_users.update_state(
            "user-one",
            status=status,
            role="viewer",
            updated_at=NOW,
        )
        assert updated.status == status
        assert (
            unit_of_work.repositories.sessions.get_active_by_token("token-one") is None
        )
        assert (
            unit_of_work.repositories.sessions.get_active_by_token("token-two") is None
        )
        stored = unit_of_work.session.scalars(select(ServerSession)).all()
        assert {session.revocation_reason for session in stored} == {"account_blocked"}


def test_user_state_and_session_invalidation_roll_back_as_one_unit(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        _create_active_owner(repositories)
        repositories.sessions.create(
            session_id="session-one",
            app_user_id="user-one",
            raw_token="token-one",
            expires_in=timedelta(hours=1),
        )

    with pytest.raises(RuntimeError, match="atomic marker"):
        with database.unit_of_work() as unit_of_work:
            unit_of_work.repositories.app_users.update_state(
                "user-one",
                status="blocked",
                role="viewer",
                updated_at=NOW,
            )
            raise RuntimeError("atomic marker")

    with database.unit_of_work() as unit_of_work:
        assert unit_of_work.repositories.app_users.get("user-one").status == "active"
        assert (
            unit_of_work.repositories.sessions.get_active_by_token("token-one")
            is not None
        )


def test_ow_unlink_invalidates_sessions_in_the_same_transaction(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        _create_active_owner(repositories)
        repositories.sessions.create(
            session_id="session-one",
            app_user_id="user-one",
            raw_token="token-one",
            expires_in=timedelta(hours=1),
        )
        link = repositories.ow_links.revoke(
            app_user_id="user-one",
            link_id="link-one",
            unlinked_at=NOW,
        )
        assert link.status == "revoked"
        assert repositories.sessions.get_active_by_token("token-one") is None
        stored = unit_of_work.session.get(ServerSession, "session-one")
        assert stored.revocation_reason == "ow_unlink"


def test_session_rotation_and_revocation_request_row_locks(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        _create_active_owner(repositories)
        repositories.sessions.create(
            session_id="session-one",
            app_user_id="user-one",
            raw_token="token-one",
            expires_in=timedelta(hours=1),
        )

    with database.unit_of_work() as unit_of_work:
        statements = []

        def capture(execute_state) -> None:
            if (
                execute_state.is_select
                and execute_state.statement._for_update_arg is not None
            ):
                statements.append(execute_state.statement)

        event.listen(unit_of_work.session, "do_orm_execute", capture)
        try:
            unit_of_work.repositories.sessions.rotate(
                raw_token="token-one",
                replacement_raw_token="token-two",
                session_id="session-two",
                expires_in=timedelta(hours=1),
            )
        finally:
            event.remove(unit_of_work.session, "do_orm_execute", capture)
        assert statements

    with database.unit_of_work() as unit_of_work:
        statements = []

        def capture(execute_state) -> None:
            if (
                execute_state.is_select
                and execute_state.statement._for_update_arg is not None
            ):
                statements.append(execute_state.statement)

        event.listen(unit_of_work.session, "do_orm_execute", capture)
        try:
            unit_of_work.repositories.sessions.revoke(
                raw_token="token-two",
                reason="logout",
            )
        finally:
            event.remove(unit_of_work.session, "do_orm_execute", capture)
        assert statements


def test_repository_ownership_requires_active_user_and_ow_link(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        with pytest.raises(ValueError, match="owner"):
            repositories.verification_runs.create(
                run_key="run-unbound",
                owner_ref="owner-not-a-user",
                scope_date=date(2026, 1, 2),
                scope_timezone="UTC",
                scope_domains=("activity",),
            )

        repositories.app_users.create(
            user_id="user-no-link",
            status="active",
            role="viewer",
        )
        with pytest.raises(ValueError, match="owner"):
            repositories.idempotency.begin(
                owner_ref="user-no-link",
                scope="verification-run-create",
                key="key-no-link",
                **_request_kwargs(),
                expires_in=timedelta(minutes=5),
            )

        _create_active_owner(repositories, user_id="user-bound", link_id="link-bound")
        claim = repositories.idempotency.begin(
            owner_ref="user-bound",
            scope="verification-run-create",
            key="key-bound",
            **_request_kwargs(),
            expires_in=timedelta(minutes=5),
        )
        assert claim.created is True


@pytest.mark.parametrize(
    "reference",
    (
        "person@example.test",
        "https://example.test/reference",
        "Bearer synthetic-secret",
        "plain prose",
        "line\nbreak",
        "a" * 129,
        "a" * 64,
        "synthetic" + "A" * 32,
    ),
)
def test_audit_references_reject_pii_urls_tokens_prose_controls_and_oversize(
    database: ControlPlaneDatabase, reference: str
) -> None:
    with database.unit_of_work() as unit_of_work:
        with pytest.raises(ValueError, match="reference"):
            unit_of_work.repositories.audit_events.record(
                actor_ref=reference,
                action="verification.run.read",
                target_type="verification_run",
                result="success",
                occurred_at=NOW,
            )


def test_verification_pending_and_terminal_lifecycle_rules_are_enforced(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        _create_active_owner(repositories)
        with pytest.raises(ValueError, match="pending"):
            repositories.verification_runs.create(
                run_key="run-pending-started",
                owner_ref="user-one",
                scope_date=date(2026, 1, 2),
                scope_timezone="UTC",
                scope_domains=("activity",),
                started_at=NOW,
            )
        with pytest.raises(ValueError, match="pending"):
            repositories.verification_runs.create(
                run_key="run-pending-counts",
                owner_ref="user-one",
                scope_date=date(2026, 1, 2),
                scope_timezone="UTC",
                scope_domains=("activity",),
                records_seen=1,
            )
        with pytest.raises(ValueError, match="terminal"):
            repositories.verification_runs.create(
                run_key="run-terminal-missing-time",
                owner_ref="user-one",
                scope_date=date(2026, 1, 2),
                scope_timezone="UTC",
                scope_domains=("activity",),
                state="persisted",
            )
        with pytest.raises(ValueError, match="counter"):
            repositories.verification_runs.create(
                run_key="run-terminal-bad-counter",
                owner_ref="user-one",
                scope_date=date(2026, 1, 2),
                scope_timezone="UTC",
                scope_domains=("activity",),
                state="failed",
                records_seen=1,
                records_accepted=2,
                started_at=NOW,
                finished_at=NOW,
            )

        terminal = repositories.verification_runs.create(
            run_key="run-terminal-valid",
            owner_ref="user-one",
            scope_date=date(2026, 1, 2),
            scope_timezone="UTC",
            scope_domains=("activity",),
            state="inconclusive",
            records_seen=1,
            records_accepted=1,
            warning_codes=("INCONCLUSIVE",),
            requested_at=NOW,
            started_at=NOW,
            finished_at=NOW,
        )
        assert terminal.finished_at == NOW


def test_idempotency_completion_expires_and_reclaim_resets_the_operation(
    database: ControlPlaneDatabase,
    clock: dict[str, datetime],
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        _create_active_owner(repositories)
        claim = repositories.idempotency.begin(
            owner_ref="user-one",
            scope="verification-run-create",
            key="key-expiring",
            **_request_kwargs(),
            expires_in=timedelta(seconds=5),
        )
        clock["now"] = NOW + timedelta(seconds=6)
        with pytest.raises(ValueError, match="expired"):
            repositories.idempotency.complete(
                owner_ref="user-one",
                record_id=claim.record.id,
                ow_link_id=claim.record.ow_link_id,
                claim_nonce=claim.claim_nonce,
                scope="verification-run-create",
                key="key-expiring",
                **_request_kwargs(),
                state="completed",
                result_ref="run-one",
            )
        expired = repositories.idempotency.get(
            owner_ref="user-one",
            scope="verification-run-create",
            key="key-expiring",
        )
        assert expired.state == "expired"
        assert expired.completed_at is None

        reclaimed = repositories.idempotency.begin(
            owner_ref="user-one",
            scope="verification-run-create",
            key="key-expiring",
            **_request_kwargs(scope_domains=("sleep",)),
            expires_in=timedelta(minutes=5),
        )
        assert reclaimed.created is False
        assert reclaimed.replayed is False
        assert reclaimed.record.state == "pending"


def test_idempotency_rejects_unknown_operation_scope(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        _create_active_owner(unit_of_work.repositories)
        with pytest.raises(ValueError, match="scope"):
            unit_of_work.repositories.idempotency.begin(
                owner_ref="user-one",
                scope="arbitrary-operation",
                key="key-scope",
                **_request_kwargs(),
                expires_in=timedelta(minutes=5),
            )


def test_database_factories_reject_unvalidated_engines_and_options() -> None:
    settings = ControlPlaneSettings(
        enabled=True,
        app_database_url="postgresql+psycopg://database.example.test:5432/control",
    )
    with pytest.raises(TypeError):
        create_control_plane_database(settings, pool_size=1)
    with pytest.raises(ControlPlaneConfigurationError, match="engine"):
        _create_test_control_plane_database(object(), now=lambda: NOW)

    import bff.control_plane_db as control_plane_db

    assert not hasattr(control_plane_db, "ControlPlaneDatabase")
    assert not hasattr(control_plane_db, "ControlPlaneUnitOfWork")


def test_idempotency_and_verification_reads_are_bound_to_link_generation(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        _create_active_owner(
            repositories,
            user_id="owner-generation",
            link_id="link-owner-generation",
        )
        repositories.idempotency.begin(
            owner_ref="owner-generation",
            scope="verification-run-create",
            key="same-key-after-relink",
            **_request_kwargs(),
            expires_in=timedelta(minutes=15),
        )
        repositories.verification_runs.create(
            run_key="run-old-generation",
            owner_ref="owner-generation",
            scope_date=date(2026, 1, 2),
            scope_timezone="UTC",
            scope_domains=("activity",),
            requested_at=NOW,
        )
        repositories.ow_links.revoke(
            app_user_id="owner-generation",
            link_id="link-owner-generation",
            unlinked_at=NOW,
        )
        repositories.ow_links.create(
            link_id="link-owner-generation-new",
            app_user_id="owner-generation",
            ow_user_ref="ow-owner-generation-new",
            status="active",
            version=2,
            linked_at=NOW,
        )

        assert (
            repositories.idempotency.get(
                owner_ref="owner-generation",
                scope="verification-run-create",
                key="same-key-after-relink",
            )
            is None
        )
        assert (
            repositories.verification_runs.get("run-old-generation", "owner-generation")
            is None
        )
        fresh_claim = repositories.idempotency.begin(
            owner_ref="owner-generation",
            scope="verification-run-create",
            key="same-key-after-relink",
            **_request_kwargs(),
            expires_in=timedelta(minutes=15),
        )
        assert fresh_claim.created is True
        assert fresh_claim.replayed is False


def test_ow_link_lookup_requires_an_active_app_user(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        _create_active_owner(repositories, user_id="owner-inactive")
        repositories.app_users.update_state(
            "owner-inactive",
            status="blocked",
            role="viewer",
            updated_at=NOW,
        )

        assert repositories.ow_links.get("link-owner-inactive") is None
        assert repositories.ow_links.get_active_for_app_user("owner-inactive") is None
        assert repositories.ow_links.get_active_for_ow_user("ow-owner-inactive") is None


def test_verification_transitions_are_locked_one_way_and_validate_counters(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        _create_active_owner(repositories, user_id="owner-lifecycle")
        repositories.verification_runs.create(
            run_key="run-lifecycle",
            owner_ref="owner-lifecycle",
            scope_date=date(2026, 1, 2),
            scope_timezone="UTC",
            scope_domains=("activity",),
            requested_at=NOW,
        )

        with pytest.raises(ValueError, match="counter"):
            repositories.verification_runs.transition(
                run_key="run-lifecycle",
                owner_ref="owner-lifecycle",
                state="persisted",
                records_seen=1,
                records_accepted=2,
                started_at=NOW,
                finished_at=NOW,
            )

        statements = []

        def capture(execute_state) -> None:
            if (
                execute_state.is_select
                and execute_state.statement._for_update_arg is not None
            ):
                statements.append(execute_state.statement)

        event.listen(unit_of_work.session, "do_orm_execute", capture)
        try:
            terminal = repositories.verification_runs.transition(
                run_key="run-lifecycle",
                owner_ref="owner-lifecycle",
                state="persisted",
                records_seen=1,
                records_accepted=1,
                records_rejected=0,
                records_duplicated=0,
                fields_unsupported=0,
                started_at=NOW,
                finished_at=NOW,
            )
        finally:
            event.remove(unit_of_work.session, "do_orm_execute", capture)

        assert terminal.state == "persisted"
        assert statements
        with pytest.raises(ValueError, match="terminal"):
            repositories.verification_runs.transition(
                run_key="run-lifecycle",
                owner_ref="owner-lifecycle",
                state="failed",
                started_at=NOW,
                finished_at=NOW,
            )


def test_mutation_audits_are_required_and_roll_back_with_the_mutation(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        unit_of_work.repositories.app_users.create(
            user_id="owner-audited",
            status="pending",
            role="pending",
        )

    with database.unit_of_work() as unit_of_work:
        events = unit_of_work.session.scalars(select(AuditEvent)).all()
        assert any(
            event.action == "identity.create"
            and event.target_type == "app_user"
            and event.target_ref == "owner-audited"
            for event in events
        )

    with pytest.raises(RuntimeError, match="audit rollback"):
        with database.unit_of_work() as unit_of_work:
            unit_of_work.repositories.app_users.create(
                user_id="owner-audit-rolled-back",
                status="pending",
                role="pending",
            )
            raise RuntimeError("audit rollback")

    with database.unit_of_work() as unit_of_work:
        assert (
            unit_of_work.repositories.app_users.get("owner-audit-rolled-back") is None
        )
        assert not unit_of_work.session.scalars(
            select(AuditEvent).where(AuditEvent.target_ref == "owner-audit-rolled-back")
        ).all()


def test_request_digest_is_canonical_and_not_caller_supplied() -> None:
    first = digest_verification_request(
        scope_date=date(2026, 1, 2),
        scope_timezone="UTC",
        scope_domains=("sources", "activity"),
    )
    second = digest_verification_request(
        scope_date=date(2026, 1, 2),
        scope_timezone="UTC",
        scope_domains=("activity", "sources"),
    )

    assert first == second
    assert len(first) == 64
    with pytest.raises(ValueError, match="timezone"):
        digest_verification_request(
            scope_date=date(2026, 1, 2),
            scope_timezone="not-an-IANA-zone",
            scope_domains=("activity",),
        )
    with pytest.raises(TypeError, match="scope_date"):
        digest_verification_request(
            scope_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
            scope_timezone="UTC",
            scope_domains=("activity",),
        )


def test_expired_completed_idempotency_cannot_be_read_or_completed(
    database: ControlPlaneDatabase,
    clock: dict[str, datetime],
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        _create_active_owner(repositories, user_id="owner-expired-terminal")
        claim = repositories.idempotency.begin(
            owner_ref="owner-expired-terminal",
            scope="verification-run-create",
            key="expired-terminal-key",
            **_request_kwargs(),
            expires_in=timedelta(seconds=5),
        )
        repositories.idempotency.complete(
            owner_ref="owner-expired-terminal",
            record_id=claim.record.id,
            ow_link_id=claim.record.ow_link_id,
            claim_nonce=claim.claim_nonce,
            scope="verification-run-create",
            key="expired-terminal-key",
            **_request_kwargs(),
            state="completed",
            result_ref="run-expired-terminal",
        )

        expired = repositories.idempotency.get(
            owner_ref="owner-expired-terminal",
            scope="verification-run-create",
            key="expired-terminal-key",
        )
        assert expired.state == "completed"

        expired = repositories.idempotency.get(
            owner_ref="owner-expired-terminal",
            scope="verification-run-create",
            key="expired-terminal-key",
        )
        assert expired.state == "completed"

        clock["now"] = NOW + timedelta(seconds=6)
        with pytest.raises(ValueError, match="expired"):
            repositories.idempotency.complete(
                owner_ref="owner-expired-terminal",
                record_id=claim.record.id,
                ow_link_id=claim.record.ow_link_id,
                claim_nonce=claim.claim_nonce,
                scope="verification-run-create",
                key="expired-terminal-key",
                **_request_kwargs(),
                state="completed",
                result_ref="run-expired-terminal",
            )


def test_idempotency_completion_requires_the_original_record_link_and_nonce(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        _create_active_owner(repositories)
        claim = repositories.idempotency.begin(
            owner_ref="user-one",
            scope="verification-run-create",
            key="fenced-key",
            **_request_kwargs(),
            expires_in=timedelta(minutes=5),
        )

        with pytest.raises(IdempotencyConflictError, match="claim"):
            repositories.idempotency.complete(
                owner_ref="user-one",
                record_id="wrong-record",
                ow_link_id=claim.record.ow_link_id,
                claim_nonce=claim.claim_nonce,
                scope="verification-run-create",
                key="fenced-key",
                **_request_kwargs(),
                state="completed",
                result_ref="run-fenced",
            )

        completed = repositories.idempotency.complete(
            owner_ref="user-one",
            record_id=claim.record.id,
            ow_link_id=claim.record.ow_link_id,
            claim_nonce=claim.claim_nonce,
            scope="verification-run-create",
            key="fenced-key",
            **_request_kwargs(),
            state="completed",
            result_ref="run-fenced",
        )
        assert completed.state == "completed"


def test_expiry_reclaim_changes_nonce_and_rejects_delayed_worker(
    database: ControlPlaneDatabase,
    clock: dict[str, datetime],
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        _create_active_owner(repositories)
        first = repositories.idempotency.begin(
            owner_ref="user-one",
            scope="verification-run-create",
            key="reclaimed-key",
            **_request_kwargs(),
            expires_in=timedelta(seconds=5),
        )

    clock["now"] = NOW + timedelta(seconds=6)
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        reclaimed = repositories.idempotency.begin(
            owner_ref="user-one",
            scope="verification-run-create",
            key="reclaimed-key",
            **_request_kwargs(),
            expires_in=timedelta(minutes=5),
        )
        assert reclaimed.claim_nonce != first.claim_nonce
        with pytest.raises(IdempotencyConflictError, match="claim"):
            repositories.idempotency.complete(
                owner_ref="user-one",
                record_id=first.record.id,
                ow_link_id=first.record.ow_link_id,
                claim_nonce=first.claim_nonce,
                scope="verification-run-create",
                key="reclaimed-key",
                **_request_kwargs(),
                state="completed",
                result_ref="stale-result",
            )


def test_idempotency_completion_rejects_a_revoked_link_generation(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        _create_active_owner(repositories)
        claim = repositories.idempotency.begin(
            owner_ref="user-one",
            scope="verification-run-create",
            key="unlinked-key",
            **_request_kwargs(),
            expires_in=timedelta(minutes=5),
        )
        repositories.ow_links.revoke(
            app_user_id="user-one", link_id="link-one", unlinked_at=NOW
        )
        repositories.ow_links.create(
            link_id="link-two",
            app_user_id="user-one",
            ow_user_ref="ow-user-two",
            status="active",
            version=2,
            linked_at=NOW,
        )

        with pytest.raises(IdempotencyConflictError, match="claim"):
            repositories.idempotency.complete(
                owner_ref="user-one",
                record_id=claim.record.id,
                ow_link_id=claim.record.ow_link_id,
                claim_nonce=claim.claim_nonce,
                scope="verification-run-create",
                key="unlinked-key",
                **_request_kwargs(),
                state="completed",
                result_ref="stale-link-result",
            )


def test_caught_audit_validation_failure_rolls_back_the_unit_of_work(
    database: ControlPlaneDatabase,
) -> None:
    with database.unit_of_work() as unit_of_work:
        with pytest.raises(ValueError, match="reference"):
            unit_of_work.repositories.app_users.create(
                user_id="user-audit-invalid",
                status="pending",
                role="pending",
                actor_ref="unsafe actor",
            )

    with database.unit_of_work() as unit_of_work:
        assert unit_of_work.repositories.app_users.get("user-audit-invalid") is None


def test_public_database_construction_is_not_exposed() -> None:
    import bff.control_plane_db as control_plane_db

    assert not hasattr(control_plane_db, "ControlPlaneDatabase")


@pytest.mark.parametrize(
    "reference",
    (
        "https://source.example.test/ref",
        "person@example.test",
        "Bearer synthetic-secret",
        "provider prose",
        "profile/ref",
        "secret-token-value",
    ),
)
def test_ow_user_references_reject_urls_emails_secrets_and_prose(
    database: ControlPlaneDatabase, reference: str
) -> None:
    with database.unit_of_work() as unit_of_work:
        repositories = unit_of_work.repositories
        repositories.app_users.create(
            user_id="owner-reference-validation",
            status="active",
            role="viewer",
        )
        with pytest.raises(ValueError, match="reference"):
            repositories.ow_links.create(
                link_id="link-reference-validation",
                app_user_id="owner-reference-validation",
                ow_user_ref=reference,
                status="active",
                version=1,
                linked_at=NOW,
            )
