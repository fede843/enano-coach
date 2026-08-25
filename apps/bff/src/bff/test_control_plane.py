from __future__ import annotations

import hashlib
import importlib.util
import io
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import DateTime, create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bff.control_plane import (
    AppUser,
    AuditEvent,
    Base,
    IdempotencyRecord,
    OidcIdentity,
    OwLink,
    ServerSession,
    VerificationRunControl,
    hash_session_token,
    utc_now,
)
from bff.control_plane_config import (
    APP_DATABASE_URL_ENV,
    OW_DATABASE_URL_ENV,
    ControlPlaneSettings,
    _database_url_identity,
)

EXPECTED_TABLES = {
    "app_user",
    "oidc_identity",
    "ow_link",
    "session",
    "audit_event",
    "idempotency_record",
    "verification_run",
}

EXPECTED_COLUMNS = {
    "app_user": {
        "id",
        "status",
        "role",
        "display_name_snapshot",
        "email_snapshot",
        "created_at",
        "updated_at",
        "last_login_at",
        "disabled_at",
    },
    "oidc_identity": {
        "id",
        "app_user_id",
        "issuer",
        "subject",
        "created_at",
        "last_seen_at",
    },
    "ow_link": {
        "id",
        "app_user_id",
        "ow_user_ref",
        "status",
        "version",
        "linked_by_ref",
        "created_at",
        "updated_at",
        "linked_at",
        "unlinked_at",
    },
    "session": {
        "id",
        "app_user_id",
        "session_hash",
        "created_at",
        "last_seen_at",
        "expires_at",
        "revoked_at",
        "revocation_reason",
    },
    "audit_event": {
        "id",
        "actor_ref",
        "action",
        "target_type",
        "target_ref",
        "result",
        "request_ref",
        "occurred_at",
    },
    "idempotency_record": {
        "id",
        "owner_ref",
        "ow_link_id",
        "claim_nonce",
        "scope",
        "key_digest",
        "request_digest",
        "result_ref",
        "state",
        "created_at",
        "updated_at",
        "expires_at",
        "completed_at",
    },
    "verification_run": {
        "run_key",
        "owner_ref",
        "ow_link_id",
        "scope_date",
        "scope_timezone",
        "scope_domains",
        "state",
        "records_seen",
        "records_accepted",
        "records_rejected",
        "records_duplicated",
        "fields_unsupported",
        "warning_codes",
        "requested_at",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    },
}

FORBIDDEN_COLUMN_PARTS = (
    "metric",
    "workout",
    "sleep",
    "gps",
    "latitude",
    "longitude",
    "payload",
    "token",
    "api_key",
    "claims",
    "password",
    "access_token",
    "refresh_token",
)


def _test_engine():
    return create_engine("sqlite+pysqlite:///:memory:")


def _user() -> AppUser:
    return AppUser(id="local-user-demo", status="active", role="viewer")


def _digest(label: str) -> str:
    return hash_session_token(label)


def _control_plane_values(
    app_database_url: str, ow_database_url: str | None = None
) -> dict[str, str]:
    values = {
        "BFF_CONTROL_PLANE_ENABLED": "true",
        "APP_DATABASE_URL": app_database_url,
    }
    if ow_database_url is not None:
        values["OW_DATABASE_URL"] = ow_database_url
    return values


def test_metadata_contains_only_control_plane_tables_and_columns() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES

    for table_name, expected_columns in EXPECTED_COLUMNS.items():
        actual_columns = {
            column.name for column in Base.metadata.tables[table_name].columns
        }
        assert actual_columns == expected_columns
        assert not any(
            forbidden in column
            for column in actual_columns
            for forbidden in FORBIDDEN_COLUMN_PARTS
        )


def test_model_constraint_names_match_the_reviewable_migration() -> None:
    expected_names = {
        "uq_oidc_identity_issuer_subject",
        "uq_ow_link_user_version",
        "uq_session_session_hash",
        "uq_idempotency_owner_link_scope_key_digest",
        "ck_session_hash_sha256",
        "ck_session_hash_sha256_hex",
        "ck_session_revocation_reason_lifecycle",
        "ck_session_revocation_reason",
        "ck_audit_event_action",
        "ck_audit_event_target_type",
        "ck_audit_event_action_nonempty",
        "ck_audit_event_target_type_nonempty",
        "ck_idempotency_key_digest_sha256",
        "ck_idempotency_key_digest_sha256_hex",
        "ck_idempotency_request_digest_sha256",
        "ck_idempotency_request_digest_sha256_hex",
        "ck_idempotency_claim_nonce_length",
        "ck_idempotency_claim_nonce_hex",
        "ck_idempotency_scope_nonempty",
        "ck_idempotency_scope_allowlist",
        "ck_verification_scope_timezone",
        "ck_verification_started_at_order",
        "ck_verification_finished_at_order",
        "ck_verification_terminal_timestamps",
        "ck_verification_counter_relationship",
        "ck_verification_warning_codes_length",
    }
    actual_names = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.name is not None
    }

    assert expected_names <= actual_names
    assert {
        "uq_ow_link_one_active_per_user",
        "uq_ow_link_one_active_per_ow_user",
    } <= {index.name for index in OwLink.__table__.indexes}


def test_every_timestamp_column_requires_timezone_aware_values() -> None:
    timestamp_columns = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, DateTime):
                timestamp_columns.append((table.name, column.name))
                assert column.type.timezone is True, (table.name, column.name)

    assert timestamp_columns
    assert utc_now().tzinfo == timezone.utc


def test_digest_columns_are_fixed_width_storage() -> None:
    assert ServerSession.__table__.c.session_hash.type.length == 64
    assert IdempotencyRecord.__table__.c.key_digest.type.length == 64
    assert IdempotencyRecord.__table__.c.request_digest.type.length == 64


def test_identity_requires_unique_issuer_and_subject() -> None:
    engine = _test_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as database:
        database.add(_user())
        database.add(
            OidcIdentity(
                id="oidc-identity-demo",
                app_user_id="local-user-demo",
                issuer="https://issuer.example.test",
                subject="subject-demo",
            )
        )
        database.commit()

        database.add(
            OidcIdentity(
                id="oidc-identity-other",
                app_user_id="local-user-demo",
                issuer="https://issuer.example.test",
                subject="subject-demo",
            )
        )
        with pytest.raises(IntegrityError):
            database.commit()


def test_only_one_active_ow_link_is_allowed_per_local_user() -> None:
    engine = _test_engine()
    Base.metadata.create_all(engine)
    linked_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with Session(engine) as database:
        database.add(_user())
        database.add(
            OwLink(
                id="ow-link-demo-a",
                app_user_id="local-user-demo",
                ow_user_ref="ow-user-ref-a",
                status="active",
                version=1,
                linked_by_ref="admin-ref-demo",
                linked_at=linked_at,
            )
        )
        database.commit()

        database.add(
            OwLink(
                id="ow-link-demo-b",
                app_user_id="local-user-demo",
                ow_user_ref="ow-user-ref-b",
                status="active",
                version=2,
                linked_by_ref="admin-ref-demo",
                linked_at=linked_at,
            )
        )
        with pytest.raises(IntegrityError):
            database.commit()


def test_only_one_active_ow_link_is_allowed_per_ow_user() -> None:
    engine = _test_engine()
    Base.metadata.create_all(engine)
    linked_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with Session(engine) as database:
        database.add_all(
            [
                _user(),
                AppUser(id="local-user-demo-two", status="active", role="viewer"),
                OwLink(
                    id="ow-link-demo-a",
                    app_user_id="local-user-demo",
                    ow_user_ref="ow-user-ref-shared",
                    status="active",
                    version=1,
                    linked_by_ref="admin-ref-demo",
                    linked_at=linked_at,
                ),
            ]
        )
        database.commit()

        database.add(
            OwLink(
                id="ow-link-demo-b",
                app_user_id="local-user-demo-two",
                ow_user_ref="ow-user-ref-shared",
                status="active",
                version=1,
                linked_by_ref="admin-ref-demo",
                linked_at=linked_at,
            )
        )
        with pytest.raises(IntegrityError):
            database.commit()


def test_active_link_indexes_are_postgresql_partial_unique_indexes() -> None:
    indexes = {
        index.name: index
        for index in OwLink.__table__.indexes
        if index.name is not None
    }

    assert {
        "uq_ow_link_one_active_per_user",
        "uq_ow_link_one_active_per_ow_user",
    } <= indexes.keys()
    for name in (
        "uq_ow_link_one_active_per_user",
        "uq_ow_link_one_active_per_ow_user",
    ):
        index = indexes[name]
        assert index.unique is True
        assert str(index.dialect_options["postgresql"]["where"]) == (
            "status = 'active'"
        )


def test_revoked_link_can_be_kept_as_history_without_becoming_active() -> None:
    engine = _test_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as database:
        database.add(_user())
        database.add(
            OwLink(
                id="ow-link-demo-revoked",
                app_user_id="local-user-demo",
                ow_user_ref="ow-user-ref-old",
                status="revoked",
                version=1,
                unlinked_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        database.add(
            OwLink(
                id="ow-link-demo-current",
                app_user_id="local-user-demo",
                ow_user_ref="ow-user-ref-current",
                status="active",
                version=2,
                linked_by_ref="admin-ref-demo",
                linked_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            )
        )
        database.commit()

        assert database.query(OwLink).count() == 2


def test_session_table_has_hash_and_lifecycle_metadata_but_no_raw_token_fields() -> (
    None
):
    engine = _test_engine()
    Base.metadata.create_all(engine)
    session_columns = {column.name for column in ServerSession.__table__.columns}

    assert "session_hash" in session_columns
    assert not any(
        forbidden in column
        for column in session_columns
        for forbidden in ("token", "access_token", "refresh_token", "claims")
    )

    with Session(engine) as database:
        database.add(_user())
        database.add(
            ServerSession(
                id="session-record-demo",
                app_user_id="local-user-demo",
                session_hash=_digest("session-record-demo"),
                expires_at=datetime(2027, 1, 2, tzinfo=timezone.utc),
            )
        )
        database.commit()

        stored = database.query(ServerSession).one()
        assert stored.session_hash == _digest("session-record-demo")


def test_idempotency_scope_and_key_digest_are_unique() -> None:
    engine = _test_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as database:
        database.add(
            IdempotencyRecord(
                id="idempotency-demo-a",
                owner_ref="local-user-demo",
                ow_link_id="ow-link-demo-a",
                claim_nonce=_digest("claim-nonce-demo"),
                scope="verification-run-create",
                key_digest=_digest("key-digest-demo"),
                request_digest=_digest("request-digest-demo"),
                state="pending",
                expires_at=datetime(2027, 1, 2, tzinfo=timezone.utc),
            )
        )
        database.commit()
        database.add(
            IdempotencyRecord(
                id="idempotency-demo-b",
                owner_ref="local-user-demo",
                ow_link_id="ow-link-demo-a",
                claim_nonce=_digest("claim-nonce-other-demo"),
                scope="verification-run-create",
                key_digest=_digest("key-digest-demo"),
                request_digest=_digest("different-request-digest"),
                state="pending",
                expires_at=datetime(2027, 1, 2, tzinfo=timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            database.commit()


def test_verification_run_control_record_has_only_sanitized_aggregates() -> None:
    engine = _test_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as database:
        database.add(
            VerificationRunControl(
                run_key="verify-demo-control-01",
                owner_ref="local-user-demo",
                ow_link_id="ow-link-demo-a",
                scope_date=date(2026, 1, 2),
                scope_timezone="UTC",
                scope_domains="activity,sources",
                state="pending",
                warning_codes="",
            )
        )
        database.commit()

        stored = database.query(VerificationRunControl).one()
        assert stored.warning_codes == ""
        assert stored.records_seen is None
        assert stored.scope_domains == "activity,sources"
        assert "warning_messages" not in VerificationRunControl.__table__.columns


def test_alembic_configuration_is_offline_capable_and_forward_revisioned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_path = (
        Path(__file__).parents[2]
        / "migrations"
        / "versions"
        / "20260817_0001_control_plane.py"
    )
    spec = importlib.util.spec_from_file_location(
        "control_plane_migration", migration_path
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "20260817_0001"
    assert migration.down_revision is None

    forward_migration_path = migration_path.with_name(
        "20260822_0002_control_plane_hardening.py"
    )
    forward_spec = importlib.util.spec_from_file_location(
        "control_plane_hardening_migration", forward_migration_path
    )
    assert forward_spec is not None and forward_spec.loader is not None
    forward_migration = importlib.util.module_from_spec(forward_spec)
    forward_spec.loader.exec_module(forward_migration)
    assert forward_migration.revision == "20260822_0002"
    assert forward_migration.down_revision == "20260817_0001"

    config = Config(str(migration_path.parents[1].parent / "alembic.ini"))
    output = io.StringIO()
    config.output_buffer = output
    config.set_main_option("script_location", str(migration_path.parents[1]))

    # Offline mode renders DDL and does not connect to a database.
    monkeypatch.setenv("BFF_CONTROL_PLANE_ENABLED", "true")
    monkeypatch.setenv(
        "APP_DATABASE_URL", "postgresql+psycopg://database.example.test:5432/control"
    )
    config.attributes["_test_output_buffer"] = output
    # A configured/CLI sqlalchemy.url must not be consulted by migrations.
    config.set_main_option("sqlalchemy.url", "not-a-database-url")
    command.upgrade(config, "head", sql=True)
    rendered = output.getvalue()
    assert "CREATE TABLE app_user" in rendered
    assert "CREATE TABLE verification_run" in rendered
    assert "uq_ow_link_one_active_per_user" in rendered
    assert "uq_ow_link_one_active_per_ow_user" in rendered
    for schema_marker in (
        "ADD COLUMN ow_link_id",
        "fk_idempotency_record_ow_link_id",
        "fk_verification_run_ow_link_id",
        "uq_idempotency_owner_link_scope_key_digest",
        "ix_idempotency_owner_link_scope_expiry",
        "claim_nonce",
        "cannot reconstruct ",
        "claim nonces; aborting",
        "cannot prove ",
        "OW-link generation bindings; aborting",
        "UPDATE verification_run",
    ):
        assert schema_marker in rendered
    for constraint_name in (
        "ck_session_hash_sha256",
        "ck_session_hash_sha256_hex",
        "ck_session_revocation_reason",
        "ck_idempotency_key_digest_sha256",
        "ck_idempotency_key_digest_sha256_hex",
        "ck_idempotency_request_digest_sha256",
        "ck_idempotency_request_digest_sha256_hex",
        "ck_idempotency_scope_allowlist",
        "ck_audit_event_action",
        "ck_audit_event_target_type",
        "ck_audit_event_action",
        "ck_verification_scope_timezone",
        "ck_verification_started_at_order",
        "ck_verification_finished_at_order",
        "ck_verification_terminal_timestamps",
        "ck_verification_counter_relationship",
    ):
        assert constraint_name in rendered

    output.seek(0)
    output.truncate(0)
    command.downgrade(config, "20260817_0001:base", sql=True)
    downgraded = output.getvalue()
    assert "cannot represent " in forward_migration._DOWNGRADE_CONTROL_PLANE_PREFLIGHT
    assert "existing control-plane values; aborting" in (
        forward_migration._DOWNGRADE_CONTROL_PLANE_PREFLIGHT
    )
    assert "action NOT IN" in forward_migration._DOWNGRADE_CONTROL_PLANE_PREFLIGHT
    assert (
        "revocation_reason NOT IN"
        in forward_migration._DOWNGRADE_CONTROL_PLANE_PREFLIGHT
    )
    assert "'ow_unlink'" not in forward_migration._DOWNGRADE_CONTROL_PLANE_PREFLIGHT
    assert "verification.run.update" not in (
        forward_migration._DOWNGRADE_CONTROL_PLANE_PREFLIGHT
    )
    assert "DROP TABLE verification_run" in downgraded
    assert "DROP TABLE app_user" in downgraded


def test_hardening_downgrade_fails_closed_before_destructive_operations() -> None:
    migration_path = (
        Path(__file__).parents[2]
        / "migrations"
        / "versions"
        / "20260822_0002_control_plane_hardening.py"
    )
    spec = importlib.util.spec_from_file_location(
        "control_plane_hardening_downgrade_policy", migration_path
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    class FailingPreflightOperations:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def execute(self, statement: object) -> None:
            self.calls.append(("execute", statement))
            rendered = str(statement)
            if (
                "cannot represent " in rendered
                and "existing control-plane values; aborting" in rendered
            ):
                raise RuntimeError("synthetic preflight failure")

        def __getattr__(self, operation: str):
            def record(*args: object, **kwargs: object) -> None:
                del kwargs
                self.calls.append((operation, (args,)))

            return record

    operations = FailingPreflightOperations()
    migration.op = operations

    with pytest.raises(RuntimeError, match="synthetic preflight failure"):
        migration.downgrade()

    assert len(operations.calls) == 1
    operation, statement = operations.calls[0]
    assert operation == "execute"
    rendered = str(statement)
    assert "action NOT IN" in rendered
    assert "revocation_reason NOT IN" in rendered


@pytest.mark.parametrize("working_directory", ("bff", "repository"))
def test_alembic_configuration_resolves_paths_relative_to_its_file(
    monkeypatch: pytest.MonkeyPatch, working_directory: str
) -> None:
    bff_directory = Path(__file__).parents[2]
    if working_directory == "bff":
        monkeypatch.chdir(bff_directory)
    else:
        monkeypatch.chdir(bff_directory.parents[1])
    config = Config(str(bff_directory / "alembic.ini"))

    assert (
        Path(config.get_main_option("script_location")).resolve()
        == (bff_directory / "migrations").resolve()
    )
    assert (
        Path(config.get_main_option("prepend_sys_path")).resolve()
        == (bff_directory / "src").resolve()
    )


def test_control_plane_is_disabled_by_default_and_reads_only_app_database_url() -> None:
    settings = ControlPlaneSettings.from_environment({})

    assert settings.enabled is False
    assert settings.app_database_url is None

    enabled = ControlPlaneSettings.from_environment(
        {
            "BFF_CONTROL_PLANE_ENABLED": "true",
            "APP_DATABASE_URL": "postgresql+psycopg://database.example.test:5432/control",
            "OW_DATABASE_URL": "postgresql+psycopg://not-used.example.test:5432/ow",
        }
    )
    assert enabled.enabled is True
    assert enabled.app_database_url == (
        "postgresql+psycopg://database.example.test:5432/control"
    )
    assert not hasattr(enabled, "ow_database_url")
    assert "database.example.test" not in repr(enabled)


def test_control_plane_requires_a_postgres_app_database_when_enabled() -> None:
    with pytest.raises(ValueError, match="APP_DATABASE_URL"):
        ControlPlaneSettings.from_environment({"BFF_CONTROL_PLANE_ENABLED": "true"})

    with pytest.raises(ValueError, match="PostgreSQL"):
        ControlPlaneSettings.from_environment(
            {
                "BFF_CONTROL_PLANE_ENABLED": "true",
                "APP_DATABASE_URL": "sqlite+pysqlite:///:memory:",
            }
        )

    with pytest.raises(ValueError, match="PostgreSQL"):
        ControlPlaneSettings.from_environment(
            {
                "BFF_CONTROL_PLANE_ENABLED": "true",
                "APP_DATABASE_URL": "file:application.db",
            }
        )


def test_control_plane_rejects_an_app_database_url_equal_to_the_ow_database_url() -> (
    None
):
    with pytest.raises(ValueError, match="separate"):
        ControlPlaneSettings.from_environment(
            {
                "BFF_CONTROL_PLANE_ENABLED": "true",
                "APP_DATABASE_URL": "postgresql+psycopg://database.example.test:5432/control",
                "OW_DATABASE_URL": "postgresql+psycopg://database.example.test:5432/control",
            }
        )


def test_control_plane_rejects_same_postgresql_target_across_url_variants() -> None:
    with pytest.raises(ValueError, match="separate"):
        ControlPlaneSettings.from_environment(
            {
                "BFF_CONTROL_PLANE_ENABLED": "true",
                "APP_DATABASE_URL": (
                    "postgresql+psycopg://app-user:alpha@DB.EXAMPLE.TEST:5432/control"
                    "?sslmode=require"
                ),
                "OW_DATABASE_URL": (
                    "postgresql+asyncpg://ow-user:beta@db.example.test:5432/control"
                    "?application_name=demo"
                ),
            }
        )


@pytest.mark.parametrize(
    ("app_database_name", "ow_database_name"),
    (
        ("Control", "control"),
        ("control", " control"),
        ("control", "control "),
    ),
)
def test_control_plane_preserves_case_and_spaces_in_database_identity(
    app_database_name: str, ow_database_name: str
) -> None:
    app_database_url = (
        f"postgresql+psycopg://app-user:credential-a@DB.EXAMPLE.TEST.:5432/"
        f"{app_database_name}"
    )
    ow_database_url = (
        f"postgresql+asyncpg://ow-user:credential-b@db.example.test:5432/"
        f"{ow_database_name}"
    )
    settings = ControlPlaneSettings.from_environment(
        _control_plane_values(app_database_url, ow_database_url)
    )

    assert settings.enabled is True
    assert (
        _database_url_identity(app_database_url, env_name=APP_DATABASE_URL_ENV)[2]
        == app_database_name
    )
    assert (
        _database_url_identity(ow_database_url, env_name=OW_DATABASE_URL_ENV)[2]
        == ow_database_name
    )


@pytest.mark.parametrize(
    "app_database_url",
    (
        "postgresql+psycopg://app-user:credential-demo@/control",
        "postgresql+psycopg://app-user:credential-demo@database.example.test/control",
        "postgresql+psycopg://app-user:credential-demo@db-a.example.test,db-b.example.test:5432/control",
        "postgresql+psycopg://app-user:credential-demo@%2Fsocket%2Fpg:5432/control",
    ),
)
def test_control_plane_rejects_ambiguous_postgresql_targets(
    app_database_url: str,
) -> None:
    with pytest.raises(ValueError, match="PostgreSQL") as error:
        ControlPlaneSettings.from_environment(
            _control_plane_values(
                app_database_url,
                "postgresql+asyncpg://other.example.test:5432/ow",
            )
        )

    assert "credential-demo" not in str(error.value)
    assert app_database_url not in repr(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    "app_database_url",
    (
        "postgresql+psycopg://[2001:db8:::1]:5432/control",
        "postgresql+psycopg://2001:db8::1:5432/control",
        "postgresql+psycopg://[127.0.0.1]:5432/control",
        "postgresql+psycopg://[fe80::1%25eth0]:5432/control",
    ),
)
def test_control_plane_rejects_invalid_ipv6_target_forms(
    app_database_url: str,
) -> None:
    with pytest.raises(ValueError, match="PostgreSQL") as error:
        ControlPlaneSettings.from_environment(
            _control_plane_values(
                app_database_url,
                "postgresql+asyncpg://other.example.test:5432/ow",
            )
        )

    assert app_database_url not in repr(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    ("app_database_url", "ow_database_url"),
    (
        (
            "postgresql+psycopg://DB.EXAMPLE.TEST.:5432/control",
            "postgresql+asyncpg://db.example.test:5432/control",
        ),
        (
            "postgresql+psycopg://127.0.0.1.:5432/control",
            "postgresql+asyncpg://127.0.0.1:5432/control",
        ),
        (
            "postgresql+psycopg://[2001:0DB8:0:0:0:0:0:1]:5432/control",
            "postgresql+asyncpg://[2001:db8::1]:5432/control",
        ),
        (
            "postgresql+psycopg://[::FFFF:192.0.2.1]:5432/control",
            "postgresql+asyncpg://192.0.2.1:5432/control",
        ),
    ),
)
def test_control_plane_rejects_same_target_after_safe_host_canonicalization(
    app_database_url: str, ow_database_url: str
) -> None:
    with pytest.raises(ValueError, match="separate"):
        ControlPlaneSettings.from_environment(
            _control_plane_values(app_database_url, ow_database_url)
        )


@pytest.mark.parametrize(
    ("app_host", "ow_host"),
    (
        ("127.0.0.1", "127.0.0.1"),
        ("127.000.000.001", "127.0.0.1"),
        ("127.1", "127.0.0.1"),
        ("2130706433", "127.0.0.1"),
        ("0x7f000001", "127.0.0.1"),
        ("017700000001", "127.0.0.1"),
    ),
)
def test_control_plane_rejects_same_target_for_legacy_ipv4_spellings(
    app_host: str, ow_host: str
) -> None:
    with pytest.raises(ValueError, match="separate"):
        ControlPlaneSettings.from_environment(
            _control_plane_values(
                f"postgresql+psycopg://{app_host}:5432/control",
                f"postgresql+asyncpg://{ow_host}:5432/control",
            )
        )


@pytest.mark.parametrize(
    "numeric_host",
    (
        "127.0.0.08",
        "00198.51.1.1",
        "1.2.3.4.5",
        "0x100000000",
        "0o17700000001",
        "0O17700000001",
    ),
)
def test_control_plane_rejects_invalid_numeric_ipv4_like_hosts(
    numeric_host: str,
) -> None:
    with pytest.raises(ValueError, match="PostgreSQL") as error:
        ControlPlaneSettings.from_environment(
            _control_plane_values(
                f"postgresql+psycopg://{numeric_host}:5432/control",
                "postgresql+asyncpg://other.example.test:5432/ow",
            )
        )

    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    ("app_driver", "ow_driver"),
    (
        ("postgresql+psycopg", "postgresql+asyncpg"),
        ("postgresql+psycopg", "postgresql+psycopg"),
        ("postgresql+psycopg", "postgresql"),
    ),
)
def test_control_plane_rejects_same_target_across_supported_and_ow_drivers(
    app_driver: str, ow_driver: str
) -> None:
    with pytest.raises(ValueError, match="separate"):
        ControlPlaneSettings.from_environment(
            _control_plane_values(
                f"{app_driver}://app-user:credential-a@DB.EXAMPLE.TEST:5432/control"
                "?application_name=app-demo&connect_timeout=5",
                f"{ow_driver}://ow-user:credential-b@db.example.test:5432/control"
                "?application_name=ow-demo&sslmode=require",
            )
        )


@pytest.mark.parametrize(
    "app_driver",
    (
        "postgresql",
        "postgresql+asyncpg",
        "postgresql+psycopg2",
        "POSTGRESQL+PSYCOGP",
    ),
)
def test_control_plane_rejects_application_drivers_not_supported_by_runtime(
    app_driver: str,
) -> None:
    with pytest.raises(ValueError, match="PostgreSQL") as error:
        ControlPlaneSettings.from_environment(
            _control_plane_values(
                f"{app_driver}://database.example.test:5432/control",
                "postgresql+asyncpg://other.example.test:5432/ow",
            )
        )

    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    "app_database_url",
    (
        "postgresql+psycopg://app-user:credential-demo@database.example.test@other.example.test:5432/control",
        "postgresql+psycopg://app-user@database.example.test@other.example.test:5432/control",
        "postgresql+psycopg://app-user%40database.example.test:credential-demo@other.example.test:5432/control",
    ),
)
def test_control_plane_rejects_postgresql_authorities_with_extra_or_embedded_at(
    app_database_url: str,
) -> None:
    with pytest.raises(ValueError, match="PostgreSQL") as error:
        ControlPlaneSettings.from_environment(
            _control_plane_values(
                app_database_url,
                "postgresql+asyncpg://other.example.test:5432/ow",
            )
        )

    assert "credential-demo" not in str(error.value)
    assert app_database_url not in repr(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    ("query_option", "app_database_url", "ow_database_url"),
    (
        (
            "dbname=control",
            "postgresql+psycopg://app.example.test/application",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "database=control",
            "postgresql+psycopg://app.example.test/application",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "host=db.example.test",
            "postgresql+psycopg://app.example.test/control",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "hostaddr=db.example.test",
            "postgresql+psycopg://app.example.test/control",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "port=5432",
            "postgresql+psycopg://db.example.test:6543/control",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "service=control-service",
            "postgresql+psycopg://app.example.test/control",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "user=ow-user",
            "postgresql+psycopg://db.example.test/application",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "username=ow-user",
            "postgresql+psycopg://db.example.test/application",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "target_session_attrs=read-write",
            "postgresql+psycopg://db.example.test/application",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "load_balance_hosts=random",
            "postgresql+psycopg://db.example.test/application",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "replication=database",
            "postgresql+psycopg://db.example.test/application",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "dsn=control-service",
            "postgresql+psycopg://db.example.test/application",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "db=control",
            "postgresql+psycopg://app.example.test/application",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "db_name=control",
            "postgresql+psycopg://app.example.test/application",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "database_name=control",
            "postgresql+psycopg://app.example.test/application",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "server=db.example.test",
            "postgresql+psycopg://app.example.test/control",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "server_name=db.example.test",
            "postgresql+psycopg://app.example.test/control",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "endpoint=db.example.test",
            "postgresql+psycopg://app.example.test/control",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "instance=db.example.test",
            "postgresql+psycopg://app.example.test/control",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "instance_name=db.example.test",
            "postgresql+psycopg://app.example.test/control",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "url=postgresql://db.example.test/control",
            "postgresql+psycopg://app.example.test/control",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "connection_string=postgresql://db.example.test/control",
            "postgresql+psycopg://app.example.test/control",
            "postgresql+psycopg://db.example.test/control",
        ),
        (
            "connectionstring=postgresql://db.example.test/control",
            "postgresql+psycopg://app.example.test/control",
            "postgresql+psycopg://db.example.test/control",
        ),
    ),
)
def test_control_plane_rejects_target_or_connection_selection_query_options(
    query_option: str, app_database_url: str, ow_database_url: str
) -> None:
    with pytest.raises(ValueError, match="connection options"):
        ControlPlaneSettings.from_environment(
            _control_plane_values(f"{app_database_url}?{query_option}", ow_database_url)
        )


def test_control_plane_rejects_unknown_postgresql_query_options_conservatively() -> (
    None
):
    with pytest.raises(ValueError, match="connection options"):
        ControlPlaneSettings.from_environment(
            _control_plane_values(
                "postgresql+psycopg://app.example.test/application"
                "?future_target_option=control",
                "postgresql+psycopg://db.example.test/control",
            )
        )


@pytest.mark.parametrize(
    "query_option",
    (
        "DBNAME=control",
        "%64%62%6e%61%6d%65=control",
        "HOST=other.example.test",
        "%68%6f%73%74%61%64%64%72=127.0.0.1",
        "PORT=6543",
        "USER=other-user",
    ),
)
def test_control_plane_rejects_case_or_encoded_target_query_keys(
    query_option: str,
) -> None:
    with pytest.raises(ValueError, match="connection options") as error:
        ControlPlaneSettings.from_environment(
            _control_plane_values(
                f"postgresql+psycopg://db.example.test/control?{query_option}",
                "postgresql+psycopg://other.example.test/ow",
            )
        )

    assert "control" not in str(error.value)


@pytest.mark.parametrize(
    "query",
    (
        "application_name=app-demo",
        "connect_timeout=5",
        "sslmode=require",
    ),
)
def test_control_plane_allows_only_clearly_non_targeting_query_options(
    query: str,
) -> None:
    settings = ControlPlaneSettings.from_environment(
        _control_plane_values(
            f"postgresql+psycopg://db.example.test:5432/control?{query}",
            "postgresql+asyncpg://db.example.test:5432/other",
        )
    )

    assert settings.enabled is True


@pytest.mark.parametrize(
    "app_database_url",
    (
        "postgresql+psycopg://database.example.test",
        "postgresql+psycopg://database.example.test/",
    ),
)
def test_control_plane_rejects_an_app_database_without_a_nonempty_database(
    app_database_url: str,
) -> None:
    with pytest.raises(ValueError, match="database"):
        ControlPlaneSettings.from_environment(
            _control_plane_values(
                app_database_url,
                "postgresql+psycopg://other.example.test/ow",
            )
        )


@pytest.mark.parametrize(
    "ow_database_url",
    (
        "postgresql+psycopg://database.example.test",
        "postgresql+psycopg://database.example.test/",
    ),
)
def test_control_plane_rejects_an_ow_comparison_target_without_a_nonempty_database(
    ow_database_url: str,
) -> None:
    with pytest.raises(ValueError, match="database"):
        ControlPlaneSettings.from_environment(
            _control_plane_values(
                "postgresql+psycopg://database.example.test:5432/control",
                ow_database_url,
            )
        )


@pytest.mark.parametrize("database_name", (" ", "\t", "\x00", "control/name"))
def test_control_plane_rejects_empty_or_malformed_database_names(
    database_name: str,
) -> None:
    with pytest.raises(ValueError, match="database") as error:
        ControlPlaneSettings.from_environment(
            _control_plane_values(
                f"postgresql+psycopg://database.example.test:5432/{database_name}",
                "postgresql+asyncpg://other.example.test:5432/ow",
            )
        )

    assert error.value.__cause__ is None


def test_control_plane_allows_distinct_postgresql_database_names() -> None:
    settings = ControlPlaneSettings.from_environment(
        {
            "BFF_CONTROL_PLANE_ENABLED": "true",
            "APP_DATABASE_URL": "postgresql+psycopg://database.example.test:5432/control",
            "OW_DATABASE_URL": "postgresql+asyncpg://database.example.test:5432/ow",
        }
    )

    assert settings.enabled is True


def test_control_plane_allows_an_app_database_without_an_ow_database_url() -> None:
    settings = ControlPlaneSettings.from_environment(
        {
            "BFF_CONTROL_PLANE_ENABLED": "true",
            "APP_DATABASE_URL": "postgresql+psycopg://database.example.test:5432/control",
        }
    )

    assert settings.enabled is True
    assert settings.app_database_url == (
        "postgresql+psycopg://database.example.test:5432/control"
    )


def test_hash_session_token_uses_sha256_lowercase_hex_without_model_storage() -> None:
    raw_token = "synthetic-session-token"

    digest = hash_session_token(raw_token)

    assert digest == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    assert len(digest) == 64
    assert digest == digest.lower()
    assert raw_token not in digest


@pytest.mark.parametrize(
    "invalid_digest",
    (
        "placeholder",
        "0" * 64,
        "a" * 64,
        "deadbeef" * 8,
        "A" * 64,
        "g" * 64,
        "0" * 63,
        "0" * 65,
    ),
)
def test_session_hash_rejects_noncanonical_digests(invalid_digest: str) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        ServerSession(
            id="session-invalid-demo",
            app_user_id="local-user-demo",
            session_hash=invalid_digest,
            expires_at=datetime(2027, 1, 2, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize("field_name", ("key_digest", "request_digest"))
@pytest.mark.parametrize(
    "invalid_digest",
    ("placeholder", "A" * 64, "g" * 64, "0" * 63, "0" * 65),
)
def test_idempotency_digests_reject_noncanonical_values(
    field_name: str, invalid_digest: str
) -> None:
    values = {
        "id": "idempotency-invalid-demo",
        "owner_ref": "local-user-demo",
        "ow_link_id": "ow-link-demo-a",
        "claim_nonce": _digest("claim-nonce-demo"),
        "scope": "verification-run-create",
        "key_digest": _digest("valid-key-digest"),
        "request_digest": _digest("valid-request-digest"),
        "state": "pending",
        "expires_at": datetime(2027, 1, 2, tzinfo=timezone.utc),
    }
    values[field_name] = invalid_digest

    with pytest.raises(ValueError, match="SHA-256"):
        IdempotencyRecord(**values)


@pytest.mark.parametrize(
    "invalid_nonce",
    ("0" * 64, "a" * 64, "A" * 64, "g" * 64, "not-a-nonce"),
)
def test_idempotency_claim_nonce_rejects_noncanonical_values(
    invalid_nonce: str,
) -> None:
    with pytest.raises(ValueError, match="nonce"):
        IdempotencyRecord(
            id="idempotency-invalid-nonce-demo",
            owner_ref="local-user-demo",
            ow_link_id="ow-link-demo-a",
            claim_nonce=invalid_nonce,
            scope="verification-run-create",
            key_digest=_digest("valid-key-digest"),
            request_digest=_digest("valid-request-digest"),
            state="pending",
            expires_at=datetime(2027, 1, 2, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize(
    "factory",
    (
        lambda: AppUser(
            id="invalid-status-demo", status="upstream prose", role="viewer"
        ),
        lambda: AppUser(id="invalid-role-demo", status="active", role="upstream prose"),
        lambda: OwLink(
            id="invalid-link-status-demo",
            app_user_id="local-user-demo",
            ow_user_ref="ow-user-ref-demo",
            status="upstream prose",
            version=1,
        ),
        lambda: AuditEvent(
            id="invalid-audit-demo",
            action="upstream prose",
            target_type="verification_run",
            result="success",
        ),
        lambda: AuditEvent(
            id="invalid-audit-target-demo",
            action="verification.run.read",
            target_type="upstream prose",
            result="success",
        ),
        lambda: AuditEvent(
            id="invalid-audit-result-demo",
            action="verification.run.read",
            target_type="verification_run",
            result="upstream prose",
        ),
        lambda: IdempotencyRecord(
            id="invalid-idempotency-state-demo",
            owner_ref="local-user-demo",
            ow_link_id="ow-link-demo-a",
            claim_nonce=_digest("claim-nonce-demo"),
            scope="verification-run-create",
            key_digest=_digest("valid-key-digest"),
            request_digest=_digest("valid-request-digest"),
            state="upstream prose",
            expires_at=datetime(2027, 1, 2, tzinfo=timezone.utc),
        ),
        lambda: VerificationRunControl(
            run_key="verify-demo-invalid-state",
            owner_ref="local-user-demo",
            ow_link_id="ow-link-demo-a",
            scope_date=date(2026, 1, 2),
            scope_timezone="UTC",
            scope_domains="activity",
            state="upstream prose",
        ),
    ),
)
def test_control_plane_status_and_audit_allowlists_reject_unknown_values(
    factory,
) -> None:
    with pytest.raises(ValueError, match="allowlist"):
        factory()


def test_verification_scope_and_warning_allowlists_reject_unknown_values() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        VerificationRunControl(
            run_key="verify-demo-invalid-domain",
            owner_ref="local-user-demo",
            ow_link_id="ow-link-demo-a",
            scope_date=date(2026, 1, 2),
            scope_timezone="UTC",
            scope_domains="activity,provider-message",
            state="pending",
        )

    with pytest.raises(ValueError, match="allowlist"):
        VerificationRunControl(
            run_key="verify-demo-invalid-warning",
            owner_ref="local-user-demo",
            ow_link_id="ow-link-demo-a",
            scope_date=date(2026, 1, 2),
            scope_timezone="UTC",
            scope_domains="activity",
            state="pending",
            warning_codes="PARTIAL_COVERAGE,provider-message",
        )


def test_revocation_reason_allowlist_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        ServerSession(
            id="session-invalid-revocation-demo",
            app_user_id="local-user-demo",
            session_hash=_digest("session-invalid-revocation-demo"),
            expires_at=datetime(2027, 1, 2, tzinfo=timezone.utc),
            revocation_reason="provider message",
        )


def test_control_plane_rejects_invalid_feature_flag_without_connecting() -> None:
    with pytest.raises(ValueError, match="BFF_CONTROL_PLANE_ENABLED"):
        ControlPlaneSettings.from_environment({"BFF_CONTROL_PLANE_ENABLED": "maybe"})


def test_control_plane_dsn_errors_are_generic_and_do_not_chain_the_dsn() -> None:
    app_database_url = "postgresql+psycopg://user:credential-demo@["

    with pytest.raises(ValueError) as error:
        ControlPlaneSettings.from_environment(
            {
                "BFF_CONTROL_PLANE_ENABLED": "true",
                "APP_DATABASE_URL": app_database_url,
            }
        )

    assert str(error.value) == "APP_DATABASE_URL must use PostgreSQL"
    assert app_database_url not in repr(error.value)
    assert error.value.__cause__ is None


def test_control_plane_invalid_dsn_does_not_expose_credentials_or_chain_details() -> (
    None
):
    app_database_url = "postgresql+psycopg://app-user:credential-demo@database.example.test:bad/control"

    with pytest.raises(ValueError) as error:
        ControlPlaneSettings.from_environment(
            {
                "BFF_CONTROL_PLANE_ENABLED": "true",
                "APP_DATABASE_URL": app_database_url,
            }
        )

    assert str(error.value) == "APP_DATABASE_URL must use PostgreSQL"
    assert "credential-demo" not in str(error.value)
    assert "credential-demo" not in repr(error.value)
    assert error.value.__cause__ is None


def test_control_plane_validates_an_app_database_port_without_an_ow_url() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        ControlPlaneSettings.from_environment(
            {
                "BFF_CONTROL_PLANE_ENABLED": "true",
                "APP_DATABASE_URL": (
                    "postgresql+psycopg://database.example.test:not-a-port/control"
                ),
            }
        )


def test_schema_inspector_sees_no_health_fact_tables() -> None:
    engine = _test_engine()
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())

    assert tables == EXPECTED_TABLES
    assert not tables.intersection(
        {"metric", "metrics", "workout", "workouts", "sleep", "gps", "samples"}
    )
