from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from adapter.offline import OfflineFixtureAdapter
from bff.config import Settings
from bff.errors import BFFError, error_for
from bff.main import create_app
from bff.models import WarningModel
from bff.session import OwnerContext
from bff.store import CursorContext, VerificationRunStore

BASE_FIELDS = {
    "schemaVersion",
    "asOf",
    "timezone",
    "data",
    "coverage",
    "warnings",
    "extensions",
}


def client_for(**kwargs: object) -> TestClient:
    kwargs.setdefault("environment", "test")
    return TestClient(create_app(**kwargs))


def dev_client_for(
    *, client_address: tuple[str, int] = ("127.0.0.1", 50000), **kwargs: object
) -> TestClient:
    kwargs.setdefault("environment", "development")
    kwargs.setdefault("session_mode", "active")
    kwargs.setdefault("dev_access_enabled", True)
    kwargs.setdefault("owner_key", "owner-dev-a")
    return TestClient(create_app(**kwargs), client=client_address)


def assert_envelope(payload: dict[str, object], *, error: bool = False) -> None:
    expected = BASE_FIELDS | ({"error"} if error else set())
    assert set(payload) == expected
    assert payload["schemaVersion"] == "1"
    assert isinstance(payload["asOf"], str)
    assert isinstance(payload["timezone"], str)
    assert isinstance(payload["coverage"], dict)
    assert isinstance(payload["warnings"], list)
    assert isinstance(payload["extensions"], dict)


def test_anonymous_session_is_public_but_protected_routes_do_not_query_adapter() -> (
    None
):
    adapter = OfflineFixtureAdapter()
    calls: list[str] = []
    original = adapter.get_bff_response

    def counted(case: str) -> dict[str, object]:
        calls.append(case)
        return original(case)

    adapter.get_bff_response = counted  # type: ignore[method-assign]
    client = client_for(session_mode="anonymous", adapter=adapter)
    calls.clear()

    session = client.get("/api/v1/session")
    assert session.status_code == 200
    assert_envelope(session.json())
    assert session.json()["data"] == {
        "authenticated": False,
        "accessState": "anonymous",
        "canReadVerification": False,
    }
    calls.clear()

    protected = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )
    assert protected.status_code == 401
    assert_envelope(protected.json(), error=True)
    assert protected.json()["error"]["code"] == "SESSION_REQUIRED"
    assert calls == []


def test_context_defaults_to_argentina_and_preserves_explicit_timezone() -> None:
    client = client_for()
    default_response = client.get(
        "/api/v1/me/verify/sleep-trend", params={"date": "2024-01-02"}
    )
    explicit_response = client.get(
        "/api/v1/me/verify/sleep-trend",
        params={"date": "2024-01-02", "timezone": "America/New_York"},
    )
    assert default_response.status_code == 200
    assert explicit_response.status_code == 200
    assert default_response.json()["timezone"] == "America/Argentina/Buenos_Aires"
    assert explicit_response.json()["timezone"] == "America/New_York"
    assert (
        default_response.json()["coverage"]["requested"]["timezone"]
        == "America/Argentina/Buenos_Aires"
    )
    assert (
        explicit_response.json()["coverage"]["requested"]["timezone"]
        == "America/New_York"
    )


@pytest.mark.parametrize(
    ("mode", "status", "code"),
    [
        ("pending", 403, "ACCESS_PENDING"),
        ("blocked", 403, "ACCESS_BLOCKED"),
        ("expired", 401, "SESSION_EXPIRED"),
    ],
)
def test_server_session_modes_are_not_client_selectable(
    mode: str, status: int, code: str
) -> None:
    client = client_for(session_mode=mode)

    session = client.get("/api/v1/session")
    assert session.status_code == 200
    assert session.json()["data"]["accessState"] in {"anonymous", mode}

    response = client.get(
        "/api/v1/me/verify/settings",
        headers={"X-BFF-Session-Mode": "active"},
    )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize("mode", ["pending", "blocked", "expired"])
def test_non_active_session_modes_never_query_the_adapter(mode: str) -> None:
    adapter = OfflineFixtureAdapter()
    calls: list[str] = []
    original = adapter.get_bff_response

    def counted(case: str) -> dict[str, object]:
        calls.append(case)
        return original(case)

    adapter.get_bff_response = counted  # type: ignore[method-assign]
    client = client_for(session_mode=mode, adapter=adapter)
    calls.clear()

    response = client.get("/api/v1/me/verify/settings")
    assert response.status_code in {401, 403}
    assert calls == []


@pytest.mark.parametrize("mode", ["anonymous", "pending", "blocked", "expired"])
def test_all_protected_operations_short_circuit_before_adapter_access(
    mode: str,
) -> None:
    adapter = OfflineFixtureAdapter()
    calls: list[str] = []
    original = adapter.get_bff_response

    def counted(case: str) -> dict[str, object]:
        calls.append(case)
        return original(case)

    adapter.get_bff_response = counted  # type: ignore[method-assign]
    client = client_for(session_mode=mode, adapter=adapter)
    calls.clear()
    create_headers = {
        "Origin": "http://testserver",
        "Idempotency-Key": "protected-short-circuit",
    }

    responses = [
        client.get(
            "/api/v1/me/verify/overview",
            params={"date": "2024-01-02", "timezone": "UTC"},
        ),
        client.get(
            "/api/v1/me/verify/sources",
            params={"date": "2024-01-02", "timezone": "UTC"},
        ),
        client.get("/api/v1/me/verify/settings"),
        client.get("/api/v1/me/verify/runs", params={"limit": 2}),
        client.get("/api/v1/me/verify/runs/verify-demo-01"),
        client.post(
            "/api/v1/me/verify/runs",
            json=_create_body(),
            headers=create_headers,
        ),
    ]

    assert [response.status_code for response in responses] == (
        [401, 401, 401, 401, 401, 401]
        if mode in {"anonymous", "expired"}
        else [403, 403, 403, 403, 403, 403]
    )
    assert calls == []


def test_active_owner_success_passes_only_server_derived_context_to_adapter() -> None:
    adapter = ContextCapturingAdapter()
    client = client_for(
        session_mode="active",
        session_key="synthetic-session-context",
        principal_key="principal-demo-a",
        owner_key="owner-demo-a",
        ow_user_key="ow-link-demo-a",
        adapter=adapter,
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
        headers={
            "X-BFF-Owner": "browser-controlled-owner",
            "X-OW-User-Key": "browser-controlled-ow-link",
            "X-OW-URL": "browser-controlled-url",
            "Authorization": "browser-controlled-credential",
        },
    )

    assert response.status_code == 200
    assert adapter.contexts
    context = adapter.contexts[0]
    assert context.principal_key == "principal-demo-a"
    assert context.owner_key == "owner-demo-a"
    assert context.ow_user_key == "ow-link-demo-a"
    assert "owner-demo-a" not in repr(response.json())
    assert "ow-link-demo-a" not in repr(response.json())


def test_invalid_server_session_mode_fails_closed() -> None:
    with pytest.raises(ValueError):
        create_app(session_mode="not-a-session-mode")


def test_disabled_development_access_preserves_fixture_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BFF_DEV_ACCESS_ENABLED", raising=False)
    settings = Settings.from_environment(environment="test", session_mode="active")
    assert settings.dev_access_enabled is False

    client = TestClient(
        create_app(environment="test", session_mode="active"),
        client=("203.0.113.10", 50000),
    )

    assert client.get("/api/v1/session").status_code == 200


def test_development_access_requires_a_server_configured_owner() -> None:
    with pytest.raises(ValueError, match="BFF_SYNTHETIC_OWNER_KEY"):
        create_app(
            environment="development",
            session_mode="active",
            dev_access_enabled=True,
        )


def test_development_access_reads_server_settings_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BFF_ENVIRONMENT", "development")
    monkeypatch.setenv("BFF_DEV_ACCESS_ENABLED", "true")
    monkeypatch.setenv("BFF_SYNTHETIC_OWNER_KEY", "owner-dev-env")

    client = TestClient(
        create_app(session_mode="active"),
        client=("127.0.0.1", 50000),
    )

    assert client.get("/api/v1/session").status_code == 200


def test_development_access_redacts_owner_context_and_settings_repr() -> None:
    client = dev_client_for(
        principal_key="principal-dev-a",
        owner_key="owner-dev-a",
        ow_user_key="ow-link-dev-a",
    )

    context = client.app.state.service.session.owner_context
    assert context is not None
    assert "principal-dev-a" not in repr(context)
    assert "owner-dev-a" not in repr(context)
    assert "ow-link-dev-a" not in repr(context)
    assert "owner-dev-a" not in repr(client.app.state.service.settings)


@pytest.mark.parametrize(
    "environment", ["local", "production", "staging", "test-server"]
)
def test_development_access_rejects_non_development_test_environments(
    environment: str,
) -> None:
    with pytest.raises(ValueError, match="development or test"):
        create_app(
            environment=environment,
            session_mode="active",
            dev_access_enabled=True,
            owner_key="owner-dev-a",
        )


def test_development_access_requires_an_explicit_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BFF_ENVIRONMENT", raising=False)

    with pytest.raises(ValueError, match="BFF_ENVIRONMENT"):
        create_app(
            session_mode="active",
            dev_access_enabled=True,
            owner_key="owner-dev-a",
        )


@pytest.mark.parametrize("client_address", [("127.0.0.1", 50000), ("::1", 50000)])
def test_development_access_accepts_loopback_client_and_allowed_origin(
    client_address: tuple[str, int],
) -> None:
    client = dev_client_for(client_address=client_address)

    response = client.get(
        "/api/v1/session",
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "client_address", [("203.0.113.10", 50000), ("testclient", 50000)]
)
def test_development_access_rejects_non_loopback_clients(
    client_address: tuple[str, int],
) -> None:
    client = dev_client_for(client_address=client_address)

    response = client.get("/api/v1/session")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert client_address[0] not in repr(response.json())


def test_development_access_rejects_disallowed_origin() -> None:
    client = dev_client_for()

    response = client.get(
        "/api/v1/session",
        headers={"Origin": "http://outside.example.test"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert "outside.example.test" not in repr(response.json())


def test_development_access_uses_only_server_derived_owner_context() -> None:
    adapter = ContextCapturingAdapter()
    client = dev_client_for(
        principal_key="principal-dev-a",
        owner_key="owner-dev-a",
        ow_user_key="ow-link-dev-a",
        adapter=adapter,
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
        headers={
            "X-BFF-Owner": "browser-controlled-owner",
            "X-OW-User-Key": "browser-controlled-ow-link",
            "X-OW-URL": "browser-controlled-url",
            "Authorization": "browser-controlled-credential",
        },
    )

    assert response.status_code == 200
    assert adapter.contexts
    context = adapter.contexts[0]
    assert context.principal_key == "principal-dev-a"
    assert context.owner_key == "owner-dev-a"
    assert context.ow_user_key == "ow-link-dev-a"
    assert "owner-dev-a" not in repr(response.json())
    assert "ow-link-dev-a" not in repr(response.json())


def test_active_overview_preserves_scalar_heart_rate_and_builds_local_window() -> None:
    def align_adapter_window(response: dict[str, object]) -> None:
        coverage = response["coverage"]
        assert isinstance(coverage, dict)
        requested = coverage["requested"]
        assert isinstance(requested, dict)
        requested.update(
            {
                "from": "2024-01-01T23:00:00Z",
                "to": "2024-01-02T23:00:00Z",
                "timezone": "Europe/Madrid",
            }
        )

    client = client_for(
        session_mode="active",
        adapter=SemanticTaintedAdapter(align_adapter_window),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "Europe/Madrid"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert_envelope(payload)
    assert payload["timezone"] == "Europe/Madrid"
    requested = payload["coverage"]["requested"]
    assert requested == {
        "logicalDate": "2024-01-02",
        "from": "2024-01-01T23:00:00Z",
        "to": "2024-01-02T23:00:00Z",
        "timezone": "Europe/Madrid",
    }
    heart_rate = payload["data"]["summary"]["heartRate"]
    assert heart_rate["value"] == 72
    assert "avgBpm" not in heart_rate
    assert "minBpm" not in heart_rate
    assert "maxBpm" not in heart_rate


@pytest.mark.parametrize(
    ("logical_date", "timezone", "expected_from", "expected_to", "case"),
    [
        (
            "2024-01-02",
            "UTC",
            "2024-01-02T00:00:00Z",
            "2024-01-03T00:00:00Z",
            "overview_mixed",
        ),
        (
            "2024-01-02",
            "Europe/Madrid",
            "2024-01-01T23:00:00Z",
            "2024-01-02T23:00:00Z",
            "overview_mixed",
        ),
        (
            "2024-03-10",
            "America/New_York",
            "2024-03-10T05:00:00Z",
            "2024-03-11T04:00:00Z",
            "overview_empty",
        ),
        (
            "2024-11-03",
            "America/New_York",
            "2024-11-03T04:00:00Z",
            "2024-11-04T05:00:00Z",
            "overview_empty",
        ),
    ],
)
def test_overview_projects_route_window_for_utc_and_dst_boundaries(
    logical_date: str,
    timezone: str,
    expected_from: str,
    expected_to: str,
    case: str,
) -> None:
    def align_logical_date(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        data["logicalDate"] = logical_date

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter(case, align_logical_date),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": logical_date, "timezone": timezone},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["timezone"] == timezone
    assert payload["asOf"].endswith("Z")
    assert payload["data"]["logicalDate"] == logical_date
    assert payload["coverage"]["requested"] == {
        "logicalDate": logical_date,
        "from": expected_from,
        "to": expected_to,
        "timezone": timezone,
    }


@pytest.mark.parametrize(
    ("logical_date", "timezone", "expected_from", "expected_to"),
    [
        (
            "2031-07-14",
            "UTC",
            "2031-07-14T00:00:00Z",
            "2031-07-15T00:00:00Z",
        ),
        (
            "2024-03-10",
            "America/New_York",
            "2024-03-10T05:00:00Z",
            "2024-03-11T04:00:00Z",
        ),
        (
            "2024-11-03",
            "America/New_York",
            "2024-11-03T04:00:00Z",
            "2024-11-04T05:00:00Z",
        ),
    ],
)
def test_valid_unmatched_dates_project_complete_route_derived_empty_overviews(
    logical_date: str,
    timezone: str,
    expected_from: str,
    expected_to: str,
) -> None:
    client = client_for(session_mode="active")

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": logical_date, "timezone": timezone},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["timezone"] == timezone
    assert payload["data"] == {
        "logicalDate": logical_date,
        "summary": {},
        "sources": [],
    }
    assert payload["coverage"] == {
        "requested": {
            "logicalDate": logical_date,
            "from": expected_from,
            "to": expected_to,
            "timezone": timezone,
        },
        "expectedDays": 1,
        "availableDays": 0,
        "isPartial": False,
        "byDomain": {},
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda response: response["data"]["summary"].update(
            {
                "steps": {
                    "state": "value",
                    "value": "not-a-number",
                    "unit": "count",
                    "isDailyTotal": True,
                }
            }
        ),
        lambda response: response["data"].pop("summary"),
    ],
)
def test_unmatched_valid_dates_do_not_mask_malformed_empty_adapter_content(
    mutation: object,
) -> None:
    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_empty", mutation),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2031-07-14", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_non_utc_overview_still_rejects_tainted_metric_coverage() -> None:
    def make_impossible_metric_coverage(response: dict[str, object]) -> None:
        metric = _summary_metric(response, "distanceMeters")
        coverage = metric["coverage"]
        assert isinstance(coverage, dict)
        coverage.update({"expectedDays": 1, "availableDays": 2, "observedFraction": 1})

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", make_impossible_metric_coverage),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "Europe/Madrid"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_scalar_heart_rate_rejects_negative_numeric_values() -> None:
    def inject_negative_heart_rate(response: dict[str, object]) -> None:
        heart_rate = _summary_metric(response, "heartRate")
        heart_rate["value"] = -1

    client = client_for(
        session_mode="active",
        adapter=SemanticTaintedAdapter(inject_negative_heart_rate),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_empty_overview_is_not_zero_and_sources_use_allowlisted_cases() -> None:
    client = client_for(session_mode="active")

    overview = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-04", "timezone": "UTC"},
    )
    assert overview.status_code == 200
    assert overview.json()["data"]["summary"] == {}
    assert overview.json()["coverage"]["availableDays"] == 0
    assert overview.json()["coverage"]["expectedDays"] == 1
    assert overview.json()["coverage"]["isPartial"] is False
    assert overview.json()["coverage"]["byDomain"] == {}
    assert "activeCaloriesKcal" not in overview.json()["data"]["summary"]

    mixed = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )
    assert mixed.status_code == 200
    assert mixed.json()["coverage"]["expectedDays"] == 1
    assert mixed.json()["coverage"]["availableDays"] == 1
    assert mixed.json()["coverage"]["isPartial"] is True

    ready = client.get(
        "/api/v1/me/verify/sources",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )
    ambiguous = client.get(
        "/api/v1/me/verify/sources",
        params={"date": "2024-01-03", "timezone": "UTC"},
    )
    date_only = client.get("/api/v1/me/verify/sources", params={"date": "2024-01-02"})
    timezone_only = client.get("/api/v1/me/verify/sources", params={"timezone": "UTC"})
    assert ready.json()["data"]["items"][0]["state"] == "ready"
    assert all(
        item["state"] == "source_ambiguous"
        for item in ambiguous.json()["data"]["items"]
    )
    assert date_only.status_code == 200
    assert timezone_only.status_code == 200


def test_runs_use_bff_cursor_order_and_context_binding() -> None:
    client = client_for(session_mode="active")

    first = client.get(
        "/api/v1/me/verify/runs",
        params={"limit": 2, "timezone": "UTC"},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert_envelope(first_payload)
    assert [item["runKey"] for item in first_payload["data"]["items"]] == [
        "verify-demo-01",
        "verify-demo-02",
    ]
    cursor = first_payload["data"]["page"]["nextCursor"]
    assert isinstance(cursor, str)
    assert "verify-demo" not in cursor
    assert "ow-run" not in cursor

    second = client.get(
        "/api/v1/me/verify/runs",
        params={"limit": 2, "timezone": "UTC", "cursor": cursor},
    )
    assert second.status_code == 200
    assert [item["runKey"] for item in second.json()["data"]["items"]] == [
        "verify-demo-03",
        "verify-demo-04",
    ]
    assert second.json()["data"]["page"]["hasNext"] is False

    mismatch = client.get(
        "/api/v1/me/verify/runs",
        params={"limit": 2, "timezone": "Europe/Madrid", "cursor": cursor},
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == "CURSOR_CONTEXT_MISMATCH"


def test_cursor_expiration_is_safe_and_does_not_restart_implicitly() -> None:
    client = client_for(session_mode="active", cursor_ttl_seconds=0)
    first = client.get("/api/v1/me/verify/runs", params={"limit": 2})
    cursor = first.json()["data"]["page"]["nextCursor"]

    expired = client.get(
        "/api/v1/me/verify/runs", params={"limit": 2, "cursor": cursor}
    )
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "CURSOR_EXPIRED"


def test_create_is_pending_idempotent_and_origin_checked() -> None:
    client = client_for(session_mode="active")
    body = {
        "date": "2024-01-02",
        "timezone": "UTC",
        "domains": ["activity", "sleep"],
    }
    headers = {"Origin": "http://testserver", "Idempotency-Key": "verify-demo-key-01"}

    created = client.post("/api/v1/me/verify/runs", json=body, headers=headers)
    repeated = client.post("/api/v1/me/verify/runs", json=body, headers=headers)
    assert created.status_code == 202
    assert repeated.status_code == 202
    assert created.json()["data"] == repeated.json()["data"]
    assert created.headers["location"].startswith("/api/v1/me/verify/runs/")

    conflict = client.post(
        "/api/v1/me/verify/runs",
        json={**body, "date": "2024-01-03"},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    missing_origin = client.post(
        "/api/v1/me/verify/runs",
        json=body,
        headers={"Idempotency-Key": "verify-demo-key-02"},
    )
    assert missing_origin.status_code == 403
    assert missing_origin.json()["error"]["code"] == "FORBIDDEN"


def test_idempotency_replay_and_conflict_short_circuit_adapter_and_state_changes() -> (
    None
):
    adapter = OfflineFixtureAdapter()
    client = client_for(session_mode="active", adapter=adapter)
    body = {
        "date": "2024-01-02",
        "timezone": "UTC",
        "domains": ["sleep", "activity"],
    }
    headers = {
        "Origin": "http://testserver",
        "Idempotency-Key": "replay-before-adapter",
    }

    created = client.post("/api/v1/me/verify/runs", json=body, headers=headers)
    assert created.status_code == 202

    service = client.app.state.service
    store = service.store
    before_replay = store._snapshot_state()
    calls: list[str] = []

    def fail_if_called(case: str) -> dict[str, object]:
        calls.append(case)
        raise AssertionError("adapter must not run for an idempotency replay")

    adapter.get_bff_response = fail_if_called  # type: ignore[method-assign]

    replayed = client.post(
        "/api/v1/me/verify/runs",
        json={**body, "domains": ["activity", "sleep"]},
        headers=headers,
    )
    assert replayed.status_code == 202
    assert replayed.json()["data"] == created.json()["data"]
    assert calls == []
    assert store._snapshot_state() == before_replay

    before_conflict = store._snapshot_state()
    conflict = client.post(
        "/api/v1/me/verify/runs",
        json={**body, "date": "2024-01-03"},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert calls == []
    assert store._snapshot_state() == before_conflict


def test_store_idempotency_lookup_normalizes_scope_domains() -> None:
    store = VerificationRunStore()
    owner = "synthetic-session-normalized-scope"

    record, created = store.create(
        owner_session_key=owner,
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("sleep", "activity"),
        idempotency_key="normalized-store-scope",
    )

    assert created is True
    assert isinstance(record.idempotency_scope(), tuple)
    assert record.idempotency_scope() == (
        "2024-01-02",
        "UTC",
        ("activity", "sleep"),
    )
    replay = store.lookup_idempotency(
        owner_session_key=owner,
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("activity", "sleep"),
        idempotency_key="normalized-store-scope",
    )

    assert replay is record


@pytest.mark.parametrize("failure_mode", ["taint", "raise"])
def test_failed_create_does_not_leave_a_run_or_idempotency_mapping(
    failure_mode: str,
) -> None:
    adapter = CreateResponseFailureAdapter(failure_mode)
    client = client_for(session_mode="active", adapter=adapter)
    body = {
        "date": "2024-01-02",
        "timezone": "UTC",
        "domains": ["activity"],
    }
    headers = {
        "Origin": "http://testserver",
        "Idempotency-Key": f"atomic-create-{failure_mode}",
    }

    failed = client.post("/api/v1/me/verify/runs", json=body, headers=headers)

    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "UPSTREAM_INVALID"

    listed = client.get(
        "/api/v1/me/verify/runs", params={"limit": 100, "timezone": "UTC"}
    )
    assert listed.status_code == 200
    assert "verify-demo-09" not in {
        item["runKey"] for item in listed.json()["data"]["items"]
    }

    missing = client.get("/api/v1/me/verify/runs/verify-demo-09")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RUN_NOT_FOUND"

    created = client.post("/api/v1/me/verify/runs", json=body, headers=headers)
    replayed = client.post("/api/v1/me/verify/runs", json=body, headers=headers)
    assert created.status_code == 202
    assert replayed.status_code == 202
    assert created.json()["data"] == replayed.json()["data"]


def test_post_rejects_client_identity_and_invalid_scope_without_adapter_access() -> (
    None
):
    adapter = OfflineFixtureAdapter()
    calls: list[str] = []
    original = adapter.get_bff_response

    def counted(case: str) -> dict[str, object]:
        calls.append(case)
        return original(case)

    adapter.get_bff_response = counted  # type: ignore[method-assign]
    client = client_for(session_mode="active", adapter=adapter)
    calls.clear()

    response = client.post(
        "/api/v1/me/verify/runs",
        json={
            "date": "2024-01-02",
            "timezone": "UTC",
            "domains": ["activity"],
            "userId": "user-demo-02",
        },
        headers={
            "Origin": "http://testserver",
            "Idempotency-Key": "verify-demo-key-03",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_SCOPE"
    assert calls == []


@pytest.mark.parametrize(
    ("fixture_case", "status", "code"),
    [
        ("overview_error", 504, "UPSTREAM_TIMEOUT"),
        ("upstream_invalid_502", 502, "UPSTREAM_INVALID"),
        ("upstream_unavailable_503", 503, "UPSTREAM_UNAVAILABLE"),
        ("upstream_timeout_504", 504, "UPSTREAM_TIMEOUT"),
        ("internal_error_500", 500, "INTERNAL_ERROR"),
        ("rate_limited_429", 429, "RATE_LIMITED"),
    ],
)
def test_server_selected_error_cases_have_safe_envelopes(
    fixture_case: str, status: int, code: str
) -> None:
    client = client_for(session_mode="active", fixture_case=fixture_case)
    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )
    assert response.status_code == status
    payload = response.json()
    assert_envelope(payload, error=True)
    assert payload["data"] is None
    assert payload["error"]["code"] == code
    assert "provider" not in repr(payload).lower()
    if status == 429:
        assert response.headers["retry-after"] == "30"


def test_validation_errors_are_enveloped_and_do_not_call_adapter() -> None:
    adapter = OfflineFixtureAdapter()
    calls: list[str] = []
    original = adapter.get_bff_response

    def counted(case: str) -> dict[str, object]:
        calls.append(case)
        return original(case)

    adapter.get_bff_response = counted  # type: ignore[method-assign]
    client = client_for(session_mode="active", adapter=adapter)
    calls.clear()

    invalid_date = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-02-30", "timezone": "UTC"},
    )
    invalid_zone = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "Not/AZone"},
    )
    invalid_limit = client.get(
        "/api/v1/me/verify/runs",
        params={"limit": 0},
    )
    assert invalid_date.status_code == 400
    assert invalid_date.json()["error"]["code"] == "INVALID_QUERY"
    assert invalid_zone.status_code == 400
    assert invalid_zone.json()["error"]["code"] == "INVALID_QUERY"
    assert invalid_limit.status_code == 400
    assert invalid_limit.json()["error"]["code"] == "INVALID_QUERY"
    assert calls == []


def test_unknown_query_parameters_are_rejected_by_route_allowlist() -> None:
    client = client_for(session_mode="active")

    response = client.get(
        "/api/v1/me/verify/settings",
        params={"userId": "user-demo-02"},
    )
    unknown = client.get(
        "/api/v1/me/verify/overview",
        params={
            "date": "2024-01-02",
            "timezone": "UTC",
            "unexpected": "value",
        },
    )
    assert response.status_code == 400
    assert unknown.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY"
    assert unknown.json()["error"]["code"] == "INVALID_QUERY"


def test_activity_trend_uses_fixed_seven_day_scope_and_sanitized_aggregation() -> None:
    client = client_for(session_mode="active")

    response = client.get(
        "/api/v1/me/verify/activity-trend",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert_envelope(payload)
    assert payload["data"]["range"] == "7d"
    assert payload["coverage"]["expectedDays"] == 7
    assert len(payload["data"]["points"]) == 7
    assert payload["data"]["points"][-1]["date"] == "2024-01-02"
    assert payload["data"]["steps"]["totalObserved"] == 8123
    assert payload["data"]["steps"]["observedDays"] == 1
    assert "source" not in repr(payload)
    assert "user_id" not in repr(payload)


@pytest.mark.parametrize("range_name", ["monthly", "180d", "annual"])
def test_sleep_trend_route_returns_successful_conservative_bucket_response(
    range_name: str,
) -> None:
    client = client_for(session_mode="active")

    response = client.get(
        "/api/v1/me/verify/sleep-trend",
        params={"date": "2024-02-29", "timezone": "Europe/Madrid", "range": range_name},
    )

    assert response.status_code == 200
    payload = response.json()
    assert_envelope(payload)
    assert payload["data"]["range"] == range_name
    assert payload["data"]["bucketMode"] == (
        "calendar-month" if range_name in {"180d", "annual"} else "daily"
    )
    assert all(
        stage["state"] in {"unsupported", "value", "zero"}
        for point in payload["data"]["points"]
        for stage in point["stages"].values()
    )


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"date": "2024-02-30", "timezone": "UTC"}, "date"),
        ({"date": "2024-02-29", "timezone": "Not/AZone"}, "timezone"),
        ({"date": "2024-02-29", "timezone": "UTC", "range": "30d"}, None),
        (
            {
                "date": "2024-02-29",
                "timezone": "UTC",
                "range": "annual",
                "timestamp": "2024-02-29T00:00:00+00:00",
            },
            None,
        ),
    ],
)
def test_sleep_trend_route_rejects_invalid_range_timestamp_and_timezone_query(
    params: dict[str, str], field: str | None
) -> None:
    client = client_for(session_mode="active")

    response = client.get("/api/v1/me/verify/sleep-trend", params=params)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY"
    assert response.json()["error"]["field"] == field


def test_sleep_trend_route_rejects_unknown_query_fields_without_adapter_access() -> (
    None
):
    adapter = OfflineFixtureAdapter()
    calls: list[str] = []
    original = adapter.get_bff_response

    def counted(case: str) -> dict[str, object]:
        calls.append(case)
        return original(case)

    adapter.get_bff_response = counted  # type: ignore[method-assign]
    client = client_for(session_mode="active", adapter=adapter)

    response = client.get(
        "/api/v1/me/verify/sleep-trend",
        params={"date": "2024-02-29", "timezone": "UTC", "unexpected": "value"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY"
    assert calls == []


@pytest.mark.parametrize(
    ("range_name", "point_count", "bucket_mode"),
    [("monthly", 31, "daily"), ("annual", 12, "calendar-month")],
)
def test_activity_trend_known_date_returns_range_buckets(
    range_name: str, point_count: int, bucket_mode: str
) -> None:
    client = client_for(session_mode="active")

    response = client.get(
        "/api/v1/me/verify/activity-trend",
        params={
            "date": "2026-08-03",
            "timezone": "UTC",
            "range": range_name,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("error") is None
    assert payload["data"]["range"] == range_name
    assert payload["data"]["bucketMode"] == bucket_mode
    assert len(payload["data"]["points"]) == point_count
    assert payload["coverage"]["requested"]["logicalDate"] == "2026-08-03"


def test_activity_trend_rejects_user_and_range_inputs_before_adapter_access() -> None:
    adapter = OfflineFixtureAdapter()
    calls: list[str] = []
    original = adapter.get_bff_response

    def counted(case: str) -> dict[str, object]:
        calls.append(case)
        return original(case)

    adapter.get_bff_response = counted  # type: ignore[method-assign]
    client = client_for(session_mode="active", adapter=adapter)

    response = client.get(
        "/api/v1/me/verify/activity-trend",
        params={
            "date": "2024-01-02",
            "timezone": "UTC",
            "range": "30d",
            "user_id": "user-demo-01",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY"
    assert calls == []


def test_invalid_cursor_is_not_treated_as_a_first_page() -> None:
    client = client_for(session_mode="active")

    response = client.get(
        "/api/v1/me/verify/runs",
        params={"limit": 2, "cursor": "client-made-cursor"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURSOR"


@pytest.mark.parametrize(
    ("cursor_case", "expected_status", "expected_code"),
    [
        ("malformed", 400, "INVALID_CURSOR"),
        ("expired", 410, "CURSOR_EXPIRED"),
        ("context", 400, "CURSOR_CONTEXT_MISMATCH"),
    ],
)
def test_invalid_cursor_validation_precedes_failing_adapter_seed(
    cursor_case: str, expected_status: int, expected_code: str
) -> None:
    session_key = "synthetic-session-cursor-order"
    store = VerificationRunStore(
        cursor_ttl_seconds=0 if cursor_case == "expired" else 300
    )
    context = CursorContext(
        session_key=(
            session_key if cursor_case != "context" else "synthetic-session-other"
        ),
        from_date=None,
        to_date=None,
        state=None,
        limit=25,
        timezone="UTC",
    )
    cursor = (
        "client-made-cursor"
        if cursor_case == "malformed"
        else store._register_cursor(context, 0, ())
    )
    adapter = AlwaysFailingAdapter()
    client = client_for(
        session_mode="active",
        session_key=session_key,
        adapter=adapter,
        store=store,
    )

    response = client.get(
        "/api/v1/me/verify/runs",
        params={"cursor": cursor, "timezone": "UTC"},
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert adapter.calls == 0


def test_all_declared_routes_are_available_with_the_expected_methods() -> None:
    client = client_for(session_mode="active")
    routes = {
        ("GET", "/api/v1/session"),
        ("GET", "/api/v1/me/verify/overview"),
        ("GET", "/api/v1/me/verify/activity-trend"),
        ("GET", "/api/v1/me/verify/sleep-trend"),
        ("GET", "/api/v1/me/verify/sources"),
        ("GET", "/api/v1/me/verify/settings"),
        ("GET", "/api/v1/me/verify/runs"),
        ("POST", "/api/v1/me/verify/runs"),
        ("GET", "/api/v1/me/verify/runs/{run_key}"),
    }
    observed = {
        (next(iter(route.methods)), route.path)
        for route in client.app.routes
        if route.path.startswith("/api/")
    }
    assert routes.issubset(observed)
    assert not any(path.startswith("/verify") for _method, path in observed)


def test_detail_preserves_closed_mismatch_and_inconclusive_states() -> None:
    client = client_for(session_mode="active")

    mismatch = client.get("/api/v1/me/verify/runs/verify-demo-07")
    inconclusive = client.get("/api/v1/me/verify/runs/verify-demo-08")
    missing = client.get("/api/v1/me/verify/runs/not-a-run")

    assert mismatch.status_code == 200
    assert (
        mismatch.json()["data"]["verificationRun"]["state"] == "completed_with_findings"
    )
    assert inconclusive.status_code == 200
    assert inconclusive.json()["data"]["verificationRun"]["state"] == "inconclusive"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RUN_NOT_FOUND"
    assert "verify-demo-07" not in repr(missing.json())


def test_detail_is_owned_by_the_server_selected_session() -> None:
    shared_store = VerificationRunStore()
    owner = client_for(
        session_mode="active",
        session_key="synthetic-session-owner",
        store=shared_store,
    )
    owner_detail = owner.get("/api/v1/me/verify/runs/verify-demo-02")
    assert owner_detail.status_code == 200

    other = client_for(
        session_mode="active",
        session_key="synthetic-session-other",
        store=shared_store,
    )
    other_detail = other.get("/api/v1/me/verify/runs/verify-demo-02")
    assert other_detail.status_code == 404
    assert other_detail.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_foreign_run_is_404_and_does_not_call_adapter_for_another_ow_link() -> None:
    shared_store = VerificationRunStore()
    owner = client_for(
        session_mode="active",
        session_key="synthetic-session-shared",
        owner_key="owner-demo-a",
        ow_user_key="ow-link-demo-a",
        store=shared_store,
    )
    own_detail = owner.get("/api/v1/me/verify/runs/verify-demo-02")
    assert own_detail.status_code == 200

    adapter = OfflineFixtureAdapter()
    calls: list[str] = []
    original = adapter.get_bff_response

    def counted(case: str) -> dict[str, object]:
        calls.append(case)
        return original(case)

    adapter.get_bff_response = counted  # type: ignore[method-assign]
    foreign = client_for(
        session_mode="active",
        session_key="synthetic-session-shared",
        owner_key="owner-demo-b",
        ow_user_key="ow-link-demo-b",
        adapter=adapter,
        store=shared_store,
    )
    seeded = foreign.get("/api/v1/me/verify/runs", params={"limit": 100})
    assert seeded.status_code == 200
    calls.clear()

    response = foreign.get("/api/v1/me/verify/runs/verify-demo-02")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RUN_NOT_FOUND"
    assert "owner-demo-a" not in repr(response.json())
    assert "ow-link-demo-a" not in repr(response.json())
    assert calls == []


def test_unseeded_foreign_detail_returns_404_without_seeding_or_adapter_access() -> (
    None
):
    shared_store = VerificationRunStore()
    owner = client_for(
        session_mode="active",
        session_key="synthetic-session-detail-owner",
        owner_key="owner-demo-detail-a",
        ow_user_key="ow-link-demo-detail-a",
        store=shared_store,
    )
    seeded = owner.get("/api/v1/me/verify/runs", params={"limit": 100})
    assert seeded.status_code == 200

    adapter = OfflineFixtureAdapter()
    calls: list[str] = []
    original = adapter.get_bff_response

    def counted(case: str) -> dict[str, object]:
        calls.append(case)
        return original(case)

    adapter.get_bff_response = counted  # type: ignore[method-assign]
    foreign = client_for(
        session_mode="active",
        session_key="synthetic-session-detail-foreign",
        owner_key="owner-demo-detail-b",
        ow_user_key="ow-link-demo-detail-b",
        adapter=adapter,
        store=shared_store,
    )
    calls.clear()

    response = foreign.get("/api/v1/me/verify/runs/verify-demo-02")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RUN_NOT_FOUND"
    assert (
        shared_store.is_seeded(
            "synthetic-session-detail-foreign",
            "owner-demo-detail-b",
            "ow-link-demo-detail-b",
        )
        is False
    )
    assert calls == []


def test_cross_owner_cursor_is_rejected_before_adapter_access() -> None:
    shared_store = VerificationRunStore()
    owner = client_for(
        session_mode="active",
        session_key="synthetic-session-shared",
        owner_key="owner-demo-a",
        ow_user_key="ow-link-demo-a",
        store=shared_store,
    )
    first = owner.get("/api/v1/me/verify/runs", params={"limit": 2})
    assert first.status_code == 200
    cursor = first.json()["data"]["page"]["nextCursor"]

    adapter = OfflineFixtureAdapter()
    calls: list[str] = []
    original = adapter.get_bff_response

    def counted(case: str) -> dict[str, object]:
        calls.append(case)
        return original(case)

    adapter.get_bff_response = counted  # type: ignore[method-assign]
    foreign = client_for(
        session_mode="active",
        session_key="synthetic-session-shared",
        owner_key="owner-demo-b",
        ow_user_key="ow-link-demo-b",
        adapter=adapter,
        store=shared_store,
    )
    calls.clear()

    response = foreign.get(
        "/api/v1/me/verify/runs",
        params={"limit": 2, "cursor": cursor},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CURSOR_CONTEXT_MISMATCH"
    assert calls == []


def test_idempotency_scope_is_bound_to_owner_even_when_session_keys_match() -> None:
    shared_store = VerificationRunStore()
    body = _create_body(domains=["activity", "sleep"])
    headers = {
        "Origin": "http://testserver",
        "Idempotency-Key": "same-owner-independent-key",
    }
    owner_a = client_for(
        session_mode="active",
        session_key="synthetic-session-shared",
        owner_key="owner-demo-a",
        ow_user_key="ow-link-demo-a",
        store=shared_store,
    )
    owner_b = client_for(
        session_mode="active",
        session_key="synthetic-session-shared",
        owner_key="owner-demo-b",
        ow_user_key="ow-link-demo-b",
        store=shared_store,
    )

    created_a = owner_a.post("/api/v1/me/verify/runs", json=body, headers=headers)
    created_b = owner_b.post("/api/v1/me/verify/runs", json=body, headers=headers)
    replayed_b = owner_b.post("/api/v1/me/verify/runs", json=body, headers=headers)

    assert created_a.status_code == 202
    assert created_b.status_code == 202
    assert replayed_b.status_code == 202
    assert (
        created_a.json()["data"]["verificationRun"]["runKey"]
        != created_b.json()["data"]["verificationRun"]["runKey"]
    )
    assert replayed_b.json()["data"] == created_b.json()["data"]

    conflict = owner_b.post(
        "/api/v1/me/verify/runs",
        json={**body, "date": "2024-01-03"},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_ow_link_rebinding_isolates_seeded_runs_cursors_and_idempotency() -> None:
    shared_store = VerificationRunStore()
    owner_a = client_for(
        session_mode="active",
        session_key="synthetic-session-link-rebind",
        owner_key="owner-demo-link-rebind",
        ow_user_key="ow-link-demo-rebind-a",
        store=shared_store,
    )
    first_a = owner_a.get(
        "/api/v1/me/verify/runs", params={"limit": 2, "timezone": "UTC"}
    )
    assert first_a.status_code == 200
    cursor_a = first_a.json()["data"]["page"]["nextCursor"]
    assert isinstance(cursor_a, str)
    keys_a = {item["runKey"] for item in first_a.json()["data"]["items"]}

    adapter_b = OfflineFixtureAdapter()
    calls: list[str] = []
    original = adapter_b.get_bff_response

    def counted(case: str) -> dict[str, object]:
        calls.append(case)
        return original(case)

    adapter_b.get_bff_response = counted  # type: ignore[method-assign]
    owner_b = client_for(
        session_mode="active",
        session_key="synthetic-session-link-rebind",
        owner_key="owner-demo-link-rebind",
        ow_user_key="ow-link-demo-rebind-b",
        adapter=adapter_b,
        store=shared_store,
    )

    second_b = owner_b.get(
        "/api/v1/me/verify/runs", params={"limit": 100, "timezone": "UTC"}
    )
    assert second_b.status_code == 200
    keys_b = {item["runKey"] for item in second_b.json()["data"]["items"]}
    assert keys_a.isdisjoint(keys_b)
    assert calls

    calls.clear()
    rebound_cursor = owner_b.get(
        "/api/v1/me/verify/runs",
        params={"limit": 2, "timezone": "UTC", "cursor": cursor_a},
    )
    assert rebound_cursor.status_code == 400
    assert rebound_cursor.json()["error"]["code"] == "CURSOR_CONTEXT_MISMATCH"
    assert calls == []

    body = _create_body(domains=["activity", "sleep"])
    headers = {
        "Origin": "http://testserver",
        "Idempotency-Key": "link-rebind-idempotency",
    }
    created_a = owner_a.post("/api/v1/me/verify/runs", json=body, headers=headers)
    created_b = owner_b.post("/api/v1/me/verify/runs", json=body, headers=headers)
    assert created_a.status_code == 202
    assert created_b.status_code == 202
    assert created_a.json()["data"] != created_b.json()["data"]


def test_delimiter_containing_owner_and_session_scopes_do_not_collide() -> None:
    shared_store = VerificationRunStore()
    body = _create_body(domains=["activity", "sleep"])
    headers = {
        "Origin": "http://testserver",
        "Idempotency-Key": "delimiter-scope-key",
    }
    owner_a = client_for(
        session_mode="active",
        session_key="session-b::session-c",
        owner_key="owner-a",
        ow_user_key="ow-link-a",
        store=shared_store,
    )
    owner_b = client_for(
        session_mode="active",
        session_key="session-c",
        owner_key="owner-a::session-b",
        ow_user_key="ow-link-b",
        store=shared_store,
    )

    created_a = owner_a.post("/api/v1/me/verify/runs", json=body, headers=headers)
    created_b = owner_b.post("/api/v1/me/verify/runs", json=body, headers=headers)
    replayed_b = owner_b.post("/api/v1/me/verify/runs", json=body, headers=headers)

    assert created_a.status_code == 202
    assert created_b.status_code == 202
    assert replayed_b.status_code == 202
    assert (
        created_a.json()["data"]["verificationRun"]["runKey"]
        != created_b.json()["data"]["verificationRun"]["runKey"]
    )
    assert replayed_b.json()["data"] == created_b.json()["data"]
    assert set(shared_store._idempotency) == {
        ("session-b::session-c", "owner-a", "ow-link-a", "delimiter-scope-key"),
        ("session-c", "owner-a::session-b", "ow-link-b", "delimiter-scope-key"),
    }


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("owner_session_key", "synthetic-session-other"),
        ("owner_key", "owner-demo-other"),
        ("scope_date", "2024-01-03"),
        ("scope_timezone", "Europe/Madrid"),
        ("domains", ("sleep",)),
    ],
)
def test_idempotency_replay_revalidates_stored_owner_session_and_scope(
    field: str, replacement: object
) -> None:
    store = VerificationRunStore()
    owner_session_key = "synthetic-session-replay-validation"
    owner_key = "owner-demo-replay-validation"
    record, created = store.create(
        owner_session_key=owner_session_key,
        owner_key=owner_key,
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("activity", "sleep"),
        idempotency_key="replay-validation-key",
    )
    assert created is True
    setattr(record, field, replacement)

    for resolver in (
        store.lookup_idempotency,
        lambda **kwargs: store.prepare_create(**kwargs)[0],
    ):
        with pytest.raises(BFFError) as caught:
            resolver(
                owner_session_key=owner_session_key,
                owner_key=owner_key,
                scope_date="2024-01-02",
                scope_timezone="UTC",
                domains=("activity", "sleep"),
                idempotency_key="replay-validation-key",
            )
        assert caught.value.code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("owner_session_key", "synthetic-session-commit-other"),
        ("owner_key", "owner-demo-commit-other"),
        ("idempotency_key", "commit-other-key"),
        ("scope_date", "2024-01-03"),
        ("scope_timezone", "Europe/Madrid"),
        ("domains", ("sleep",)),
    ],
)
def test_commit_rejects_mismatched_prepared_records_without_mutation(
    field: str, replacement: object
) -> None:
    store = VerificationRunStore()
    owner_session_key = "synthetic-session-commit"
    owner_key = "owner-demo-commit"
    record, created = store.prepare_create(
        owner_session_key=owner_session_key,
        owner_key=owner_key,
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("activity", "sleep"),
        idempotency_key="commit-key",
    )
    assert created is True
    before = store._snapshot_state()
    commit_args: dict[str, object] = {
        "owner_session_key": owner_session_key,
        "owner_key": owner_key,
        "idempotency_key": "commit-key",
        "scope_date": "2024-01-02",
        "scope_timezone": "UTC",
        "domains": ("activity", "sleep"),
        "record": record,
    }
    commit_args[field] = replacement

    with pytest.raises(BFFError) as caught:
        store.commit_create(**commit_args)  # type: ignore[arg-type]

    assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    assert store._snapshot_state() == before
    assert store._runs == {}
    assert store._idempotency == {}


def test_commit_rejects_an_orphan_record_without_mutation() -> None:
    store = VerificationRunStore()
    prepared, created = store.prepare_create(
        owner_session_key="synthetic-session-orphan",
        owner_key="owner-demo-orphan",
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("activity",),
        idempotency_key="orphan-key",
    )
    assert created is True
    orphan = deepcopy(prepared)
    before = store._snapshot_state()

    with pytest.raises(BFFError) as caught:
        store.commit_create(
            owner_session_key="synthetic-session-orphan",
            owner_key="owner-demo-orphan",
            idempotency_key="orphan-key",
            scope_date="2024-01-02",
            scope_timezone="UTC",
            domains=("activity",),
            record=orphan,
        )

    assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    assert store._snapshot_state() == before
    assert store._runs == {}
    assert store._idempotency == {}


def test_commit_rejects_a_rebound_prepared_record_even_when_arguments_follow_it() -> (
    None
):
    store = VerificationRunStore()
    record, created = store.prepare_create(
        owner_session_key="synthetic-session-rebound",
        owner_key="owner-demo-rebound",
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("activity",),
        idempotency_key="rebound-key",
    )
    assert created is True
    record.owner_session_key = "synthetic-session-rebound-other"
    record.owner_key = "owner-demo-rebound-other"
    record.idempotency_key = "rebound-other-key"
    record.scope_date = "2024-01-03"
    record.scope_timezone = "Europe/Madrid"
    record.domains = ("sleep",)
    before = store._snapshot_state()

    with pytest.raises(BFFError) as caught:
        store.commit_create(
            owner_session_key="synthetic-session-rebound-other",
            owner_key="owner-demo-rebound-other",
            idempotency_key="rebound-other-key",
            scope_date="2024-01-03",
            scope_timezone="Europe/Madrid",
            domains=("sleep",),
            record=record,
        )

    assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    assert store._snapshot_state() == before
    assert store._runs == {}
    assert store._idempotency == {}


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("owner_session_key", "synthetic-session-rollback-other"),
        ("owner_key", "owner-demo-rollback-other"),
        ("idempotency_key", "rollback-other-key"),
        ("scope_date", "2024-01-03"),
        ("scope_timezone", "Europe/Madrid"),
        ("domains", ("sleep",)),
    ],
)
def test_rollback_rejects_mismatched_requests_without_mutation(
    field: str, replacement: object
) -> None:
    store = VerificationRunStore()
    owner_session_key = "synthetic-session-rollback"
    owner_key = "owner-demo-rollback"
    record, created = store.create(
        owner_session_key=owner_session_key,
        owner_key=owner_key,
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("activity",),
        idempotency_key="rollback-key",
    )
    assert created is True
    context = CursorContext(
        session_key=owner_session_key,
        from_date=None,
        to_date=None,
        state=None,
        limit=1,
        timezone="UTC",
        owner_key=owner_key,
    )
    cursor = store._register_cursor(context, 0, (record.run_key,))
    before = store._snapshot_state()
    rollback_args: dict[str, object] = {
        "owner_session_key": owner_session_key,
        "owner_key": owner_key,
        "idempotency_key": "rollback-key",
        "scope_date": "2024-01-02",
        "scope_timezone": "UTC",
        "domains": ("activity",),
        "record": record,
    }
    rollback_args[field] = replacement

    with pytest.raises(BFFError) as caught:
        store.rollback_create(**rollback_args)  # type: ignore[arg-type]

    assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    assert store._snapshot_state() == before
    assert store._runs[record.run_key] is record
    assert (
        store._idempotency[(owner_session_key, owner_key, None, "rollback-key")][1]
        == record.run_key
    )
    assert cursor in store._cursors


def test_valid_rollback_removes_mapping_and_cursor_references() -> None:
    store = VerificationRunStore()
    owner_session_key = "synthetic-session-rollback-valid"
    owner_key = "owner-demo-rollback-valid"
    record, created = store.create(
        owner_session_key=owner_session_key,
        owner_key=owner_key,
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("activity",),
        idempotency_key="rollback-valid-key",
    )
    assert created is True
    context = CursorContext(
        session_key=owner_session_key,
        from_date=None,
        to_date=None,
        state=None,
        limit=1,
        timezone="UTC",
        owner_key=owner_key,
    )
    cursor = store._register_cursor(context, 0, (record.run_key,))

    store.rollback_create(
        owner_session_key=owner_session_key,
        owner_key=owner_key,
        idempotency_key="rollback-valid-key",
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("activity",),
        record=record,
    )

    assert record.run_key not in store._runs
    assert store._idempotency == {}
    assert cursor not in store._cursors
    with pytest.raises(BFFError) as caught:
        store.list_page(
            context=context,
            from_date=None,
            to_date=None,
            state=None,
            cursor=cursor,
        )
    assert caught.value.code == "INVALID_CURSOR"


def test_rollback_uses_logical_identity_after_deep_copy_state_restore() -> None:
    store = VerificationRunStore()
    owner_session_key = "synthetic-session-rollback-restored"
    owner_key = "owner-demo-rollback-restored"
    ow_user_key = "ow-link-demo-rollback-restored"
    record, created = store.create(
        owner_session_key=owner_session_key,
        owner_key=owner_key,
        ow_user_key=ow_user_key,
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("activity",),
        idempotency_key="rollback-restored-key",
    )
    assert created is True
    context = CursorContext(
        session_key=owner_session_key,
        from_date=None,
        to_date=None,
        state=None,
        limit=1,
        timezone="UTC",
        owner_key=owner_key,
        ow_user_key=ow_user_key,
    )
    cursor = store._register_cursor(context, 0, (record.run_key,))
    snapshot = store._snapshot_state()
    store._restore_state(snapshot)

    before_mismatch = store._snapshot_state()
    with pytest.raises(BFFError) as caught:
        store.rollback_create(
            owner_session_key=owner_session_key,
            owner_key=owner_key,
            ow_user_key="ow-link-demo-rollback-other",
            idempotency_key="rollback-restored-key",
            scope_date="2024-01-02",
            scope_timezone="UTC",
            domains=("activity",),
            record=record,
        )
    assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    assert store._snapshot_state() == before_mismatch
    assert cursor in store._cursors

    store.rollback_create(
        owner_session_key=owner_session_key,
        owner_key=owner_key,
        ow_user_key=ow_user_key,
        idempotency_key="rollback-restored-key",
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("activity",),
        record=record,
    )

    assert store._runs == {}
    assert store._idempotency == {}
    assert store._prepared == {}
    assert store._prepared_requests == {}
    assert cursor not in store._cursors


def test_rollback_rejects_a_rebound_prepared_record_without_mutation() -> None:
    store = VerificationRunStore()
    record, created = store.prepare_create(
        owner_session_key="synthetic-session-rollback-rebound",
        owner_key="owner-demo-rollback-rebound",
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("activity",),
        idempotency_key="rollback-rebound-key",
    )
    assert created is True
    record.owner_session_key = "synthetic-session-rollback-rebound-other"
    record.owner_key = "owner-demo-rollback-rebound-other"
    record.idempotency_key = "rollback-rebound-other-key"
    record.scope_date = "2024-01-03"
    record.scope_timezone = "Europe/Madrid"
    record.domains = ("sleep",)
    before = store._snapshot_state()

    with pytest.raises(BFFError) as caught:
        store.rollback_create(
            owner_session_key="synthetic-session-rollback-rebound-other",
            owner_key="owner-demo-rollback-rebound-other",
            idempotency_key="rollback-rebound-other-key",
            scope_date="2024-01-03",
            scope_timezone="Europe/Madrid",
            domains=("sleep",),
            record=record,
        )

    assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    assert store._snapshot_state() == before
    assert store._runs == {}
    assert store._idempotency == {}


def test_reseeding_a_shared_context_is_idempotent_but_other_context_gets_own_data() -> (
    None
):
    store = VerificationRunStore()
    adapter = OfflineFixtureAdapter()
    session_key = "synthetic-session-shared-seed"

    store.seed_from_adapter(
        adapter,
        session_key,
        owner_key="owner-demo-seed-a",
    )
    before = store._snapshot_state()
    store.seed_from_adapter(
        adapter,
        session_key,
        owner_key="owner-demo-seed-a",
    )
    assert store._snapshot_state() == before

    store.seed_from_adapter(
        adapter,
        session_key,
        owner_key="owner-demo-seed-b",
    )

    assert store._snapshot_state() != before
    owner_a_records = {
        record.run_key
        for record in store._runs.values()
        if record.owner_session_key == session_key
        and record.owner_key == "owner-demo-seed-a"
    }
    owner_b_records = {
        record.run_key
        for record in store._runs.values()
        if record.owner_session_key == session_key
        and record.owner_key == "owner-demo-seed-b"
    }
    assert len(owner_a_records) == 8
    assert len(owner_b_records) == 8
    assert owner_a_records.isdisjoint(owner_b_records)
    assert {
        (record.owner_session_key, record.owner_key) for record in store._runs.values()
    } == {
        (session_key, "owner-demo-seed-a"),
        (session_key, "owner-demo-seed-b"),
    }


def test_service_reseeds_when_the_server_owner_context_changes() -> None:
    client = client_for(
        session_mode="active",
        session_key="synthetic-session-context-switch",
        owner_key="owner-demo-context-a",
        ow_user_key="ow-link-demo-context-a",
    )

    first = client.get("/api/v1/me/verify/runs", params={"limit": 100})
    assert first.status_code == 200
    first_keys = {item["runKey"] for item in first.json()["data"]["items"]}

    service = client.app.state.service
    service.session = replace(
        service.session,
        owner_context=OwnerContext(
            principal_key="principal-demo-context-b",
            owner_key="owner-demo-context-b",
            ow_user_key="ow-link-demo-context-b",
        ),
    )

    second = client.get("/api/v1/me/verify/runs", params={"limit": 100})
    assert second.status_code == 200
    second_keys = {item["runKey"] for item in second.json()["data"]["items"]}

    assert len(first_keys) == 4
    assert len(second_keys) == 4
    assert first_keys.isdisjoint(second_keys)


def test_seeding_does_not_overwrite_a_prepared_run_key() -> None:
    store = VerificationRunStore()
    owner_session_key = "synthetic-session-prepared-seed-collision"
    owner_key = "owner-demo-prepared-seed-collision"
    prepared, created = store.prepare_create(
        owner_session_key=owner_session_key,
        owner_key=owner_key,
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("activity",),
        idempotency_key="prepared-seed-collision-key",
    )
    assert created is True
    assert prepared.run_key == "verify-demo-01"

    store.seed_from_adapter(
        OfflineFixtureAdapter(),
        owner_session_key,
        owner_key=owner_key,
    )

    assert store._prepared[prepared.run_key] is prepared
    assert prepared.run_key not in store._runs
    assert all(record.run_key != prepared.run_key for record in store._runs.values())


def test_seeding_does_not_overwrite_a_committed_scope_or_idempotency_record() -> None:
    store = VerificationRunStore()
    owner_session_key = "synthetic-session-committed-seed-collision"
    owner_key = "owner-demo-committed-seed-collision"
    store.create(
        owner_session_key=owner_session_key,
        owner_key=owner_key,
        scope_date="2024-01-01",
        scope_timezone="UTC",
        domains=("activity",),
        idempotency_key="committed-seed-collision-a",
    )
    committed, created = store.create(
        owner_session_key=owner_session_key,
        owner_key=owner_key,
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("sleep",),
        idempotency_key="committed-seed-collision-b",
    )
    assert created is True
    assert committed.run_key == "verify-demo-02"

    store.seed_from_adapter(
        OfflineFixtureAdapter(),
        owner_session_key,
        owner_key=owner_key,
    )

    replay = store.lookup_idempotency(
        owner_session_key=owner_session_key,
        owner_key=owner_key,
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("sleep",),
        idempotency_key="committed-seed-collision-b",
    )
    assert replay is committed
    assert committed.state == "pending"
    assert committed.scope() == {
        "date": "2024-01-02",
        "timezone": "UTC",
        "domains": ["sleep"],
    }


def test_two_active_owners_seed_independent_fixture_lists() -> None:
    shared_store = VerificationRunStore()
    owner_a = client_for(
        session_mode="active",
        session_key="synthetic-session-two-owners",
        owner_key="owner-demo-two-a",
        ow_user_key="ow-link-demo-two-a",
        store=shared_store,
    )
    owner_b = client_for(
        session_mode="active",
        session_key="synthetic-session-two-owners",
        owner_key="owner-demo-two-b",
        ow_user_key="ow-link-demo-two-b",
        store=shared_store,
    )

    first = owner_a.get("/api/v1/me/verify/runs", params={"limit": 100})
    second = owner_b.get("/api/v1/me/verify/runs", params={"limit": 100})

    assert first.status_code == 200
    assert second.status_code == 200
    first_keys = {item["runKey"] for item in first.json()["data"]["items"]}
    second_keys = {item["runKey"] for item in second.json()["data"]["items"]}
    assert len(first_keys) == 4
    assert len(second_keys) == 4
    assert first_keys.isdisjoint(second_keys)
    assert all(
        shared_store.get(
            run_key,
            "synthetic-session-two-owners",
            owner_key="owner-demo-two-a",
            ow_user_key="ow-link-demo-two-a",
        )
        is not None
        for run_key in first_keys
    )
    assert all(
        shared_store.get(
            run_key,
            "synthetic-session-two-owners",
            owner_key="owner-demo-two-b",
            ow_user_key="ow-link-demo-two-b",
        )
        is not None
        for run_key in second_keys
    )


@pytest.mark.parametrize(
    ("stage", "status", "expected"),
    [
        ("queued", "in_progress", "pending"),
        ("completed", "success", "persisted"),
        ("completed", "partial", "partial"),
        ("failed", "failed", "failed"),
        ("cancelled", "cancelled", "cancelled"),
        ("completed", "skipped", "skipped"),
        ("completed", "success", "completed_with_findings"),
        ("completed", "success", "not_verifiable"),
        ("completed", "in_progress", "inconclusive"),
    ],
)
def test_run_state_normalization_preserves_terminal_semantics(
    stage: str, status: str, expected: str
) -> None:
    from bff.service import normalize_run_state

    kwargs = {
        "closed_mismatch": expected == "completed_with_findings",
        "not_verifiable": expected == "not_verifiable",
    }
    assert normalize_run_state(stage, status, **kwargs) == expected


def test_settings_and_run_responses_do_not_expose_internal_fields() -> None:
    client = client_for(session_mode="active")
    responses = [
        client.get("/api/v1/me/verify/settings"),
        client.get("/api/v1/me/verify/runs/verify-demo-02"),
    ]
    for response in responses:
        assert response.status_code == 200
        text = repr(response.json()).lower()
        assert "adaptermappings" not in text
        assert "owrunid" not in text
        assert "user_id" not in text
        assert "raw" not in text


class TaintedAdapter(OfflineFixtureAdapter):
    """Return valid fixture data with fields a browser boundary must drop."""

    def get_bff_response(self, case: str) -> dict[str, object]:
        response = deepcopy(super().get_bff_response(case))
        data = response.get("data")
        if isinstance(data, dict):
            data["user_id"] = "user-demo-tainted"
            data["unknownData"] = {"metadata": {"path": "/private"}}
        extensions = response.setdefault("extensions", {})
        if isinstance(extensions, dict):
            extensions["unknownExtension"] = {
                "owRunId": "ow-run-demo-tainted",
                "token": "secret-taint",
            }
        if case == "overview_mixed" and isinstance(data, dict):
            summary = data.get("summary")
            if isinstance(summary, dict):
                heart_rate = summary.get("heartRate")
                if isinstance(heart_rate, dict):
                    heart_rate.update(
                        {
                            "avgBpm": 999,
                            "minBpm": 1,
                            "maxBpm": 999,
                            "metadata": {"user_id": "user-demo-tainted"},
                            "sourceKey": "source-demo-tainted",
                            "coverage": {"path": "/private"},
                        }
                    )
                summary["unknownMetric"] = {"value": 1}
        if case == "verification_run_partial" and isinstance(data, dict):
            verification_run = data.get("verificationRun")
            if isinstance(verification_run, dict):
                results = verification_run.get("results")
                if isinstance(results, list) and results:
                    results[0]["metadata"] = {"payload": "raw"}
        return response


class ContextCapturingAdapter:
    def __init__(self) -> None:
        self.delegate = OfflineFixtureAdapter()
        self.contexts: list[OwnerContext] = []

    def get_bff_response(
        self, case: str, *, owner_context: OwnerContext
    ) -> dict[str, object]:
        self.contexts.append(owner_context)
        return self.delegate.get_bff_response(case)


class TaintedErrorAdapter(OfflineFixtureAdapter):
    def get_bff_response(self, case: str) -> dict[str, object]:
        response = deepcopy(super().get_bff_response(case))
        if case == "overview_mixed":
            response["error"] = {
                "code": "UPSTREAM_TIMEOUT",
                "message": "provider secret details",
                "metadata": {"user_id": "user-demo-tainted"},
            }
        return response


class ExplodingAdapter(OfflineFixtureAdapter):
    def get_bff_response(self, case: str) -> dict[str, object]:
        if case == "overview_mixed":
            raise RuntimeError("provider secret /private/path")
        return super().get_bff_response(case)


class AlwaysFailingAdapter(OfflineFixtureAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def get_bff_response(self, case: str) -> dict[str, object]:
        self.calls += 1
        raise AssertionError(f"adapter must not run for invalid cursor: {case}")


class ContractFailingAdapter(OfflineFixtureAdapter):
    def get_bff_response(self, case: str) -> dict[str, object]:
        if case == "overview_mixed":
            from adapter.offline import FixtureContractError

            raise FixtureContractError("provider payload details")
        return super().get_bff_response(case)


class SemanticTaintedAdapter(OfflineFixtureAdapter):
    def __init__(self, mutation: object) -> None:
        super().__init__()
        self.mutation = mutation

    def get_bff_response(self, case: str) -> dict[str, object]:
        response = deepcopy(super().get_bff_response(case))
        if case == "overview_mixed":
            self.mutation(response)
        return response


class RunTaintedAdapter(OfflineFixtureAdapter):
    def __init__(self, case: str, mutation: object) -> None:
        super().__init__()
        self.tainted_case = case
        self.mutation = mutation

    def get_bff_response(self, case: str) -> dict[str, object]:
        response = deepcopy(super().get_bff_response(case))
        if case == self.tainted_case:
            self.mutation(response)
        return response


class SeedOnlyTaintedAdapter(OfflineFixtureAdapter):
    def __init__(self) -> None:
        super().__init__()
        self._tainted = True

    def get_bff_response(self, case: str) -> dict[str, object]:
        response = deepcopy(super().get_bff_response(case))
        if case == "verification_run_create" and self._tainted:
            self._tainted = False
            data = response["data"]
            assert isinstance(data, dict)
            run = data["verificationRun"]
            assert isinstance(run, dict)
            run["user_id"] = "user-demo-tainted"
        return response


class CreateResponseFailureAdapter(OfflineFixtureAdapter):
    def __init__(self, failure_mode: str) -> None:
        super().__init__()
        self.failure_mode = failure_mode
        self.create_response_calls = 0

    def get_bff_response(self, case: str) -> dict[str, object]:
        response = deepcopy(super().get_bff_response(case))
        if case == "verification_run_create":
            self.create_response_calls += 1
            if self.create_response_calls == 2:
                if self.failure_mode == "raise":
                    raise ValueError("synthetic adapter validation failure")
                data = response["data"]
                assert isinstance(data, dict)
                run = data["verificationRun"]
                assert isinstance(run, dict)
                run["user_id"] = "user-demo-tainted"
        return response


class NonMappingAdapter(OfflineFixtureAdapter):
    def get_bff_response(self, case: str) -> dict[str, object]:
        if case == "overview_mixed":
            return None  # type: ignore[return-value]
        return super().get_bff_response(case)


def _summary_metric(response: dict[str, object], name: str) -> dict[str, object]:
    data = response["data"]
    assert isinstance(data, dict)
    summary = data["summary"]
    assert isinstance(summary, dict)
    metric = summary[name]
    assert isinstance(metric, dict)
    return metric


def _verification_run(response: dict[str, object]) -> dict[str, object]:
    data = response["data"]
    assert isinstance(data, dict)
    run = data["verificationRun"]
    assert isinstance(run, dict)
    return run


@pytest.mark.parametrize(
    "mutation",
    [
        lambda response: _summary_metric(response, "steps").update(
            {"state": "unsupported", "value": 1}
        ),
        lambda response: _summary_metric(response, "steps").update(
            {"state": "null", "unit": "count"}
        ),
        lambda response: _summary_metric(response, "steps").update(
            {"state": "zero", "value": 0, "isDailyTotal": False}
        ),
        lambda response: _summary_metric(response, "steps").update(
            {"state": "value", "value": 0}
        ),
        lambda response: _summary_metric(response, "distanceMeters").update(
            {"coverage": {"expectedDays": 1, "availableDays": 1, "observedFraction": 1}}
        ),
        lambda response: _summary_metric(response, "distanceMeters").update(
            {
                "coverage": {
                    "expectedDays": 1,
                    "availableDays": 1,
                    "observedFraction": float("nan"),
                }
            }
        ),
        lambda response: _summary_metric(response, "heartRate").update({"value": 0}),
    ],
)
def test_bff_rejects_tainted_metric_semantics_with_safe_upstream_error(
    mutation: object,
) -> None:
    client = client_for(session_mode="active", adapter=SemanticTaintedAdapter(mutation))

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    payload = response.json()
    assert_envelope(payload, error=True)
    assert payload["error"]["code"] == "UPSTREAM_INVALID"
    assert payload["error"]["message"] == "The source returned an invalid response."
    assert "nan" not in repr(payload).lower()


def test_scalar_heart_rate_null_state_preserves_null_unit() -> None:
    def make_null(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        summary = data["summary"]
        assert isinstance(summary, dict)
        summary["heartRate"] = {
            "state": "null",
            "value": None,
            "unit": None,
            "isDailyTotal": False,
        }
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings[:] = [
            warning for warning in warnings if warning["code"] != "SOURCE_AMBIGUOUS"
        ]

    client = client_for(
        session_mode="active", adapter=SemanticTaintedAdapter(make_null)
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["summary"]["heartRate"] == {
        "state": "null",
        "value": None,
        "unit": None,
        "isDailyTotal": False,
    }


def test_scalar_heart_rate_preserves_a_semantically_confirmed_zero() -> None:
    def make_zero(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        summary = data["summary"]
        assert isinstance(summary, dict)
        summary["heartRate"] = {
            "state": "zero",
            "value": 0,
            "unit": "bpm",
            "isDailyTotal": True,
        }
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings[:] = [
            warning for warning in warnings if warning["code"] != "SOURCE_AMBIGUOUS"
        ]

    client = client_for(
        session_mode="active", adapter=SemanticTaintedAdapter(make_zero)
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["summary"]["heartRate"] == {
        "state": "zero",
        "value": 0,
        "unit": "bpm",
        "isDailyTotal": True,
    }


@pytest.mark.parametrize(
    ("state", "value", "is_daily_total"),
    [
        ("value", 1, False),
        ("value", 82, False),
        ("value", 100, False),
        ("zero", 0, False),
        ("zero", 0, True),
        ("zero", 0, None),
        ("null", None, False),
        ("unsupported", None, None),
    ],
)
def test_recovery_score_allows_a_unitless_value_or_zero(
    state: str, value: int | None, is_daily_total: bool | None
) -> None:
    def set_recovery_score(response: dict[str, object]) -> None:
        metric = _summary_metric(response, "recoveryScore")
        metric.update(
            {
                "state": state,
                "value": value,
                "unit": None,
                "isDailyTotal": is_daily_total,
            }
        )
        if state in {"value", "zero", "partial", "source_ambiguous"}:
            coverage = response["coverage"]
            assert isinstance(coverage, dict)
            by_domain = coverage["byDomain"]
            assert isinstance(by_domain, dict)
            by_domain["recovery"] = {
                "expectedDays": 1,
                "availableDays": 1,
                "state": "complete",
            }

    client = client_for(
        session_mode="active", adapter=SemanticTaintedAdapter(set_recovery_score)
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["summary"]["recoveryScore"] == {
        "state": state,
        "value": value,
        "unit": None,
        "isDailyTotal": is_daily_total,
    }


@pytest.mark.parametrize("is_daily_total", [False, True, None])
def test_recovery_score_rejects_zero_in_value_state(
    is_daily_total: bool | None,
) -> None:
    def set_zero_value(response: dict[str, object]) -> None:
        metric = _summary_metric(response, "recoveryScore")
        metric.update(
            {
                "state": "value",
                "value": 0,
                "unit": None,
                "isDailyTotal": is_daily_total,
            }
        )

    client = client_for(
        session_mode="active", adapter=SemanticTaintedAdapter(set_zero_value)
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_non_recovery_value_cannot_be_unitless() -> None:
    def remove_steps_unit(response: dict[str, object]) -> None:
        _summary_metric(response, "steps").update(
            {"state": "value", "value": 8123, "unit": None}
        )

    client = client_for(
        session_mode="active", adapter=SemanticTaintedAdapter(remove_steps_unit)
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda response: _summary_metric(response, "heartRate").update({"avgBpm": 73}),
        lambda response: _summary_metric(response, "heartRate").update(
            {"minBpm": 50, "maxBpm": 150}
        ),
        lambda response: response["data"]["summary"].update(
            {"providerFailure": {"value": 1}}
        ),
        lambda response: response["coverage"].update({"unexpected": 1}),
    ],
)
def test_bff_rejects_unknown_route_children_instead_of_dropping_them(
    mutation: object,
) -> None:
    client = client_for(session_mode="active", adapter=SemanticTaintedAdapter(mutation))

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"
    assert "providerFailure" not in repr(response.json())
    assert "avgBpm" not in repr(response.json())


def test_bff_rejects_non_finite_run_counts_at_the_browser_boundary() -> None:
    def inject_nan(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        items = data["items"]
        assert isinstance(items, list)
        counts = items[0]["counts"]
        assert isinstance(counts, dict)
        counts["recordsSeen"] = float("inf")

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("runs_first_page", inject_nan),
    )

    response = client.get("/api/v1/me/verify/runs", params={"limit": 2})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"
    assert "inf" not in repr(response.json()).lower()


def test_bff_rejects_non_finite_results_at_the_browser_boundary() -> None:
    def inject_nan(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        run = data["verificationRun"]
        assert isinstance(run, dict)
        results = run["results"]
        assert isinstance(results, list)
        results[0]["expected"] = float("nan")

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("verification_run_mismatch", inject_nan),
    )

    response = client.get("/api/v1/me/verify/runs/verify-demo-07")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"
    assert "nan" not in repr(response.json()).lower()


def test_bff_rejects_inconsistent_result_counts_at_the_browser_boundary() -> None:
    def inject_invalid_counts(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        run = data["verificationRun"]
        assert isinstance(run, dict)
        counts = run["counts"]
        assert isinstance(counts, dict)
        counts["recordsSeen"] = 1
        counts["recordsAccepted"] = 2

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("verification_run_partial", inject_invalid_counts),
    )

    response = client.get("/api/v1/me/verify/runs/verify-demo-02")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_pending_run_rejects_terminal_results() -> None:
    def add_pending_result(response: dict[str, object]) -> None:
        run = _verification_run(response)
        run["results"] = [{"metric": "steps", "state": "match"}]

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("verification_run_create", add_pending_result),
    )

    response = client.get("/api/v1/me/verify/runs")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_persisted_run_rejects_mismatch_findings() -> None:
    def mark_persisted_with_mismatch(response: dict[str, object]) -> None:
        _verification_run(response)["state"] = "persisted"

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter(
            "verification_run_mismatch", mark_persisted_with_mismatch
        ),
    )

    response = client.get("/api/v1/me/verify/runs")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_completed_with_findings_requires_a_closed_mismatch_result() -> None:
    def remove_mismatch_result(response: dict[str, object]) -> None:
        _verification_run(response)["results"] = []

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("verification_run_mismatch", remove_mismatch_result),
    )

    response = client.get("/api/v1/me/verify/runs")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_completed_with_findings_requires_terminal_timestamps() -> None:
    def remove_finished_timestamp(response: dict[str, object]) -> None:
        _verification_run(response)["finishedAt"] = None

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter(
            "verification_run_mismatch", remove_finished_timestamp
        ),
    )

    response = client.get("/api/v1/me/verify/runs")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda response: _verification_run(response).update({"finishedAt": None}),
        lambda response: _verification_run(response).update(
            {
                "startedAt": "2024-01-02T08:00:04Z",
                "finishedAt": "2024-01-02T08:00:03Z",
            }
        ),
    ],
)
def test_partial_terminal_runs_require_ordered_completion_timestamps(
    mutation: object,
) -> None:
    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("verification_run_partial", mutation),
    )

    response = client.get("/api/v1/me/verify/runs/verify-demo-02")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_not_verifiable_terminal_runs_require_completion_timestamps() -> None:
    def remove_finished_timestamp(response: dict[str, object]) -> None:
        _verification_run(response)["finishedAt"] = None

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter(
            "verification_not_verifiable", remove_finished_timestamp
        ),
    )

    response = client.get("/api/v1/me/verify/runs/verify-demo-06")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_persisted_runs_reject_inconclusive_warnings_without_findings() -> None:
    def make_persisted_with_inconclusive_warning(response: dict[str, object]) -> None:
        run = _verification_run(response)
        run["state"] = "persisted"
        run["results"] = None

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter(
            "verification_inconclusive", make_persisted_with_inconclusive_warning
        ),
    )

    response = client.get("/api/v1/me/verify/runs/verify-demo-08")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_inconclusive_runs_require_a_corresponding_result_and_warning() -> None:
    def remove_inconclusive_result(response: dict[str, object]) -> None:
        _verification_run(response)["results"] = None

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter(
            "verification_inconclusive", remove_inconclusive_result
        ),
    )

    response = client.get("/api/v1/me/verify/runs/verify-demo-08")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda response: _verification_run(response)["results"][0].update(
            {"observed": 8123}
        ),
        lambda response: _verification_run(response)["results"][0].update(
            {"unit": "meters"}
        ),
        lambda response: _verification_run(response)["results"][0].update(
            {"observedIsDailyTotal": False}
        ),
        lambda response: _verification_run(response)["results"].append(
            {
                "metric": "steps",
                "state": "inconclusive",
                "reasonCode": "CURSOR_EXPIRED",
            }
        ),
    ],
)
def test_closed_mismatch_requires_coherent_exclusive_result_semantics(
    mutation: object,
) -> None:
    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("verification_run_mismatch", mutation),
    )

    response = client.get("/api/v1/me/verify/runs/verify-demo-07")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_partial_run_requires_its_partial_warning() -> None:
    def remove_partial_warning(response: dict[str, object]) -> None:
        run = _verification_run(response)
        warnings = run["warnings"]
        assert isinstance(warnings, list)
        warnings.clear()

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("verification_run_partial", remove_partial_warning),
    )

    response = client.get("/api/v1/me/verify/runs")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_not_verifiable_run_requires_a_result_and_warning() -> None:
    def remove_not_verifiable_evidence(response: dict[str, object]) -> None:
        run = _verification_run(response)
        run["warnings"] = []
        run["results"] = []

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter(
            "verification_not_verifiable", remove_not_verifiable_evidence
        ),
    )

    response = client.get("/api/v1/me/verify/runs")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_inconclusive_run_rejects_an_empty_result_collection_when_provided() -> None:
    def remove_inconclusive_result(response: dict[str, object]) -> None:
        _verification_run(response)["results"] = []

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter(
            "verification_inconclusive", remove_inconclusive_result
        ),
    )

    response = client.get("/api/v1/me/verify/runs")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_failed_run_remains_failed_in_detail() -> None:
    client = client_for(session_mode="active")

    response = client.get("/api/v1/me/verify/runs/verify-demo-04")

    assert response.status_code == 200
    assert response.json()["data"]["verificationRun"]["state"] == "failed"


def test_seed_rejects_tainted_run_before_it_enters_the_store() -> None:
    client = client_for(session_mode="active", adapter=SeedOnlyTaintedAdapter())

    response = client.get("/api/v1/me/verify/runs")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_seed_failure_is_atomic_for_records_and_idempotency_state() -> None:
    store = VerificationRunStore()
    adapter = SeedOnlyTaintedAdapter()
    client = client_for(
        session_mode="active",
        session_key="synthetic-session-seed-atomic",
        adapter=adapter,
        store=store,
    )

    failed = client.get("/api/v1/me/verify/runs")

    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "UPSTREAM_INVALID"
    assert store.is_empty
    assert store.get("verify-demo-01", "synthetic-session-seed-atomic") is None
    assert store.get("verify-demo-05", "synthetic-session-seed-atomic") is None
    assert store._idempotency == {}


def test_create_serializes_before_commit_and_does_not_consume_a_failed_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bff.service as service_module

    store = VerificationRunStore()
    client = client_for(
        session_mode="active",
        session_key="synthetic-session-create-atomic",
        store=store,
    )
    original_serializer = service_module.serialize_run_create
    observed_presence: list[bool] = []

    def fail_after_observing_candidate(
        _raw: object, *, record: object, timezone_name: str
    ) -> dict[str, object]:
        del timezone_name
        assert hasattr(record, "run_key")
        observed_presence.append(
            store.get(record.run_key, "synthetic-session-create-atomic") is not None  # type: ignore[attr-defined]
        )
        raise error_for("UPSTREAM_INVALID")

    monkeypatch.setattr(
        service_module, "serialize_run_create", fail_after_observing_candidate
    )
    body = {
        "date": "2024-01-02",
        "timezone": "UTC",
        "domains": ["activity"],
    }
    headers = {
        "Origin": "http://testserver",
        "Idempotency-Key": "create-before-commit",
    }

    failed = client.post("/api/v1/me/verify/runs", json=body, headers=headers)

    assert failed.status_code == 502
    assert observed_presence == [False]

    monkeypatch.setattr(service_module, "serialize_run_create", original_serializer)
    created = client.post("/api/v1/me/verify/runs", json=body, headers=headers)

    assert created.status_code == 202
    assert created.json()["data"]["verificationRun"]["runKey"] == "verify-demo-09"


def test_bff_rejects_unknown_warning_domain_instead_of_omitting_it() -> None:
    def inject_unknown_domain(response: dict[str, object]) -> None:
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings[0]["domain"] = "provider"

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", inject_unknown_domain),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_bff_rejects_pending_metric_with_a_value_or_unit() -> None:
    def inject_pending_metric(response: dict[str, object]) -> None:
        metric = _summary_metric(response, "steps")
        metric.update({"state": "pending", "value": 8123, "unit": "count"})

    client = client_for(
        session_mode="active",
        adapter=SemanticTaintedAdapter(inject_pending_metric),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_bff_rejects_fractional_count_result_values() -> None:
    def inject_fractional_result(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        run = data["verificationRun"]
        assert isinstance(run, dict)
        results = run["results"]
        assert isinstance(results, list)
        results[0]["expected"] = 8123.5

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter(
            "verification_run_mismatch", inject_fractional_result
        ),
    )

    response = client.get("/api/v1/me/verify/runs/verify-demo-07")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_bff_rejects_missing_source_items_container() -> None:
    def remove_items(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        del data["items"]

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("source_ready", remove_items),
    )

    response = client.get(
        "/api/v1/me/verify/sources",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_bff_rejects_non_finite_source_timestamps_at_the_browser_boundary() -> None:
    def inject_nan(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        items = data["items"]
        assert isinstance(items, list)
        items[0]["lastObservedAt"] = float("nan")

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("source_ready", inject_nan),
    )

    response = client.get(
        "/api/v1/me/verify/sources",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"
    assert "nan" not in repr(response.json()).lower()


def test_bff_rejects_non_finite_values_in_extensions_and_warnings() -> None:
    def inject_inf(response: dict[str, object]) -> None:
        extensions = response["extensions"]
        assert isinstance(extensions, dict)
        capabilities = extensions["capabilities"]
        assert isinstance(capabilities, dict)
        capabilities["gps"] = float("inf")

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", inject_inf),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_bff_rejects_tainted_settings_copy() -> None:
    def inject_text(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        data["technicalState"] = "provider failure details"

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("settings_capabilities", inject_text),
    )

    response = client.get("/api/v1/me/verify/settings")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_bff_rejects_tainted_run_result_text() -> None:
    def inject_text(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        run = data["verificationRun"]
        assert isinstance(run, dict)
        run["results"][0]["reasonCode"] = "provider failure details"

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("verification_inconclusive", inject_text),
    )

    response = client.get("/api/v1/me/verify/runs/verify-demo-08")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda response: response["coverage"].update(
            {"expectedDays": 1, "availableDays": 2}
        ),
        lambda response: response["coverage"].update(
            {"expectedDays": 2, "availableDays": 1, "isPartial": False}
        ),
        lambda response: response["coverage"]["byDomain"]["activity"].update(
            {"expectedDays": 2, "availableDays": 2, "state": "partial"}
        ),
    ],
)
def test_bff_rejects_impossible_coverage_combinations(mutation: object) -> None:
    client = client_for(session_mode="active", adapter=SemanticTaintedAdapter(mutation))

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_daily_overview_rejects_metric_coverage_for_more_than_one_day() -> None:
    def change_metric_window(response: dict[str, object]) -> None:
        coverage = _summary_metric(response, "distanceMeters")["coverage"]
        assert isinstance(coverage, dict)
        coverage.update(
            {"expectedDays": 2, "availableDays": 1, "observedFraction": 0.5}
        )

    client = client_for(
        session_mode="active", adapter=SemanticTaintedAdapter(change_metric_window)
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda response: response["coverage"].update(
            {"expectedDays": 0, "availableDays": 0, "isPartial": True}
        ),
        lambda response: response["coverage"]["requested"].update(
            {"from": "2024-01-03T00:00:00Z", "to": "2024-01-02T00:00:00Z"}
        ),
    ],
)
def test_bff_rejects_inconsistent_partial_or_requested_coverage(
    mutation: object,
) -> None:
    client = client_for(session_mode="active", adapter=SemanticTaintedAdapter(mutation))

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


@pytest.mark.parametrize(
    ("expected_days", "available_days"),
    [(2, 2), (0, 0)],
)
def test_daily_overview_requires_one_expected_day(
    expected_days: int, available_days: int
) -> None:
    def change_daily_window(response: dict[str, object]) -> None:
        coverage = response["coverage"]
        assert isinstance(coverage, dict)
        coverage.update(
            {
                "expectedDays": expected_days,
                "availableDays": available_days,
                "isPartial": False,
            }
        )

    client = client_for(
        session_mode="active", adapter=SemanticTaintedAdapter(change_daily_window)
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_daily_overview_rejects_complete_coverage_with_a_partial_metric() -> None:
    def mark_complete(response: dict[str, object]) -> None:
        coverage = response["coverage"]
        assert isinstance(coverage, dict)
        coverage["isPartial"] = False

    client = client_for(
        session_mode="active", adapter=SemanticTaintedAdapter(mark_complete)
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_daily_overview_rejects_partial_coverage_without_a_partial_observation() -> (
    None
):
    def remove_partial_observation(response: dict[str, object]) -> None:
        metric = _summary_metric(response, "distanceMeters")
        metric.update({"state": "value", "value": 5300})
        metric.pop("coverage", None)
        coverage = response["coverage"]
        assert isinstance(coverage, dict)
        coverage["isPartial"] = True
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings[:] = [
            warning for warning in warnings if warning["code"] != "PARTIAL_COVERAGE"
        ]

    client = client_for(
        session_mode="active",
        adapter=SemanticTaintedAdapter(remove_partial_observation),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_overview_replaces_a_contradictory_fixture_request_window() -> None:
    def change_adapter_window(response: dict[str, object]) -> None:
        coverage = response["coverage"]
        assert isinstance(coverage, dict)
        requested = coverage["requested"]
        assert isinstance(requested, dict)
        requested.update(
            {
                "logicalDate": "2024-01-01",
                "from": "2024-01-01T00:00:00Z",
                "to": "2024-01-02T00:00:00Z",
            }
        )

    client = client_for(
        session_mode="active", adapter=SemanticTaintedAdapter(change_adapter_window)
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 200
    assert response.json()["coverage"]["requested"] == {
        "logicalDate": "2024-01-02",
        "from": "2024-01-02T00:00:00Z",
        "to": "2024-01-03T00:00:00Z",
        "timezone": "UTC",
    }


def test_empty_overview_rejects_a_complete_domain_claim() -> None:
    def add_complete_domain(response: dict[str, object]) -> None:
        coverage = response["coverage"]
        assert isinstance(coverage, dict)
        by_domain = coverage["byDomain"]
        assert isinstance(by_domain, dict)
        by_domain["activity"] = {
            "expectedDays": 1,
            "availableDays": 1,
            "state": "complete",
        }

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_empty", add_complete_domain),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-04", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_overview_rejects_an_observed_metric_with_an_empty_domain() -> None:
    def mark_activity_empty(response: dict[str, object]) -> None:
        coverage = response["coverage"]
        assert isinstance(coverage, dict)
        by_domain = coverage["byDomain"]
        assert isinstance(by_domain, dict)
        by_domain["activity"] = {
            "expectedDays": 1,
            "availableDays": 0,
            "state": "empty",
        }

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", mark_activity_empty),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_overview_rejects_missing_activity_domain_for_observed_activity_metrics() -> (
    None
):
    def remove_activity_domain(response: dict[str, object]) -> None:
        coverage = response["coverage"]
        assert isinstance(coverage, dict)
        by_domain = coverage["byDomain"]
        assert isinstance(by_domain, dict)
        del by_domain["activity"]

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", remove_activity_domain),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_overview_maps_scalar_heart_rate_to_activity_coverage() -> None:
    response = client_for(session_mode="active").get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 200
    by_domain = response.json()["coverage"]["byDomain"]
    assert "activity" in by_domain
    assert "heart_rate" not in by_domain


def test_overview_rejects_observed_metrics_when_by_domain_is_empty() -> None:
    def remove_domain_coverage(response: dict[str, object]) -> None:
        coverage = response["coverage"]
        assert isinstance(coverage, dict)
        coverage["byDomain"] = {}
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings[:] = [
            warning for warning in warnings if warning["code"] != "BODY_RELATIVE_TO_NOW"
        ]

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", remove_domain_coverage),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_overview_rejects_observed_metric_with_non_observing_domain_state() -> None:
    def mark_activity_unsupported(response: dict[str, object]) -> None:
        coverage = response["coverage"]
        assert isinstance(coverage, dict)
        by_domain = coverage["byDomain"]
        assert isinstance(by_domain, dict)
        activity = by_domain["activity"]
        assert isinstance(activity, dict)
        activity["state"] = "unsupported"

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", mark_activity_unsupported),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


@pytest.mark.parametrize(
    ("metric_name", "state"),
    [
        ("steps", "unsupported"),
        ("steps", "null"),
        ("sleepDurationSeconds", "unsupported"),
        ("sleepDurationSeconds", "null"),
        ("recoveryScore", "unsupported"),
        ("recoveryScore", "null"),
        ("heartRate", "unsupported"),
        ("heartRate", "null"),
    ],
)
def test_unobserved_metrics_do_not_require_domain_coverage(
    metric_name: str, state: str
) -> None:
    def remove_unobserved_domains(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        summary = data["summary"]
        assert isinstance(summary, dict)
        metric = summary[metric_name]
        assert isinstance(metric, dict)
        summary.clear()
        metric.update(
            {
                "state": state,
                "value": None,
                "unit": None,
                "isDailyTotal": None,
            }
        )
        summary[metric_name] = metric
        data.pop("sources", None)

        coverage = response["coverage"]
        assert isinstance(coverage, dict)
        coverage.update({"availableDays": 0, "isPartial": False, "byDomain": {}})
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings.clear()

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", remove_unobserved_domains),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 200
    assert response.json()["coverage"]["byDomain"] == {}


def test_empty_metric_can_report_zero_observed_fraction() -> None:
    def make_empty_metric(response: dict[str, object]) -> None:
        metric = _summary_metric(response, "steps")
        metric.update(
            {
                "state": "empty",
                "value": None,
                "unit": None,
                "isDailyTotal": False,
                "coverage": {
                    "expectedDays": 1,
                    "availableDays": 0,
                    "observedFraction": 0,
                },
            }
        )

    client = client_for(
        session_mode="active", adapter=SemanticTaintedAdapter(make_empty_metric)
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["summary"]["steps"]["coverage"] == {
        "expectedDays": 1,
        "availableDays": 0,
        "observedFraction": 0,
    }


def test_bff_rejects_non_mapping_adapter_responses_as_upstream_invalid() -> None:
    client = client_for(session_mode="active", adapter=NonMappingAdapter())

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"
    assert response.json()["error"]["field"] is None


def test_adapter_contract_failures_are_safe_upstream_invalid_responses() -> None:
    client = client_for(session_mode="active", adapter=ContractFailingAdapter())

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"
    assert "provider payload details" not in repr(response.json())


def test_source_label_is_replaced_by_a_closed_synthetic_label() -> None:
    def inject_narrative(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        items = data["items"]
        assert isinstance(items, list)
        items[0]["label"] = "provider failure: secret details"

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("source_ready", inject_narrative),
    )

    response = client.get(
        "/api/v1/me/verify/sources",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 200
    payload = response.json()
    label = payload["data"]["items"][0]["label"]
    assert label == "Fuente sintética A"
    assert "provider failure" not in repr(payload).lower()


def test_sources_reject_unknown_route_data_children() -> None:
    def inject_unknown_data(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        data["providerFailure"] = "raw provider narrative"

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("source_ready", inject_unknown_data),
    )

    response = client.get(
        "/api/v1/me/verify/sources",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"
    assert "raw provider narrative" not in repr(response.json())


def test_warning_narrative_is_rejected_without_forwarding_provider_copy() -> None:
    def inject_narrative(response: dict[str, object]) -> None:
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings[0]["message"] = "provider failure: private details"

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", inject_narrative),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    payload = response.json()
    assert payload["error"]["code"] == "UPSTREAM_INVALID"
    assert "provider failure" not in repr(payload).lower()


def test_body_relative_coverage_requires_its_warning() -> None:
    def remove_body_warning(response: dict[str, object]) -> None:
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings[:] = [
            warning for warning in warnings if warning["code"] != "BODY_RELATIVE_TO_NOW"
        ]

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", remove_body_warning),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_create_rejects_more_than_six_domains_without_reading_adapter() -> None:
    adapter = OfflineFixtureAdapter()
    calls: list[str] = []
    original = adapter.get_bff_response

    def counted(case: str) -> dict[str, object]:
        calls.append(case)
        return original(case)

    adapter.get_bff_response = counted  # type: ignore[method-assign]
    client = client_for(session_mode="active", adapter=adapter)
    calls.clear()

    response = client.post(
        "/api/v1/me/verify/runs",
        json={
            "date": "2024-01-02",
            "timezone": "UTC",
            "domains": [
                "activity",
                "sleep",
                "recovery",
                "body",
                "workouts",
                "sources",
                "activity",
            ],
        },
        headers={
            "Origin": "http://testserver",
            "Idempotency-Key": "too-many-domains",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_SCOPE"
    assert calls == []


def test_bounded_receive_rejects_chunked_body_before_downstream_accumulates_it() -> (
    None
):
    import bff.main as main_module

    middleware_type = getattr(main_module, "BoundedBodyMiddleware", None)
    assert middleware_type is not None

    messages = iter(
        [
            {"type": "http.request", "body": b"1234", "more_body": True},
            {"type": "http.request", "body": b"5", "more_body": False},
        ]
    )
    downstream_received: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return next(messages)

    async def send(_message: dict[str, object]) -> None:
        return None

    async def downstream(
        _scope: dict[str, object], receive_fn: object, _send: object
    ) -> None:
        downstream_received.append(await receive_fn())  # type: ignore[misc]
        await receive_fn()  # type: ignore[misc]

    middleware = middleware_type(downstream, max_bytes=4)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/me/verify/runs",
        "headers": [],
    }

    with pytest.raises(BFFError) as caught:
        asyncio.run(middleware(scope, receive, send))

    assert caught.value.code == "INVALID_QUERY"
    assert downstream_received == [
        {"type": "http.request", "body": b"1234", "more_body": True}
    ]


def test_trailing_slash_is_json_not_a_redirect_and_head_is_not_run_not_found() -> None:
    client = client_for(session_mode="active")

    trailing = client.get("/api/v1/session/", follow_redirects=False)
    head = client.request("HEAD", "/api/v1/session")

    assert trailing.status_code == 404
    assert trailing.headers["content-type"].startswith("application/json")
    assert "location" not in trailing.headers
    assert_envelope(trailing.json(), error=True)
    assert trailing.json()["error"]["code"] == "NOT_FOUND"
    assert head.status_code == 405
    assert head.headers["content-type"].startswith("application/json")
    assert int(head.headers["content-length"]) > 0


def test_bff_rejects_tainted_nested_fields_on_every_route() -> None:
    client = client_for(session_mode="active", adapter=TaintedAdapter())
    requests = [
        client.get("/api/v1/session"),
        client.get(
            "/api/v1/me/verify/overview",
            params={"date": "2024-01-02", "timezone": "UTC"},
        ),
        client.get(
            "/api/v1/me/verify/sources",
            params={"date": "2024-01-02", "timezone": "UTC"},
        ),
        client.get("/api/v1/me/verify/settings"),
        client.get("/api/v1/me/verify/runs", params={"limit": 2}),
        client.get("/api/v1/me/verify/runs/verify-demo-02"),
        client.post(
            "/api/v1/me/verify/runs",
            json={
                "date": "2024-01-02",
                "timezone": "UTC",
                "domains": ["activity"],
            },
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "taint-test-key",
                "Origin": "http://testserver",
            },
        ),
    ]

    assert all(response.status_code in {502, 202} for response in requests)
    for response in requests:
        text = repr(response.json()).lower()
        assert "user_id" not in text
        assert "userid" not in text
        assert "owrunid" not in text
        assert "adaptermappings" not in text
        assert "metadata" not in text
        assert "payload" not in text
        assert "unknown" not in text
        assert "avgBpm".lower() not in text
        assert "minBpm".lower() not in text
        assert "maxBpm".lower() not in text
        assert "token" not in text
        if response.status_code == 502:
            assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_bff_drops_tainted_error_fields_and_returns_safe_error() -> None:
    client = client_for(session_mode="active", adapter=TaintedErrorAdapter())

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    payload = response.json()
    assert payload["error"] == {
        "code": "UPSTREAM_INVALID",
        "message": "The source returned an invalid response.",
        "requestId": payload["error"]["requestId"],
        "retryable": False,
        "field": None,
    }
    assert "provider" not in repr(payload).lower()
    assert "metadata" not in repr(payload).lower()
    assert "user_id" not in repr(payload).lower()


@pytest.mark.parametrize(
    "params",
    [
        {"date": ""},
        {"timezone": ""},
    ],
)
def test_sources_rejects_explicit_empty_optional_query_values(
    params: dict[str, str],
) -> None:
    client = client_for(session_mode="active")

    response = client.get("/api/v1/me/verify/sources", params=params)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY"


@pytest.mark.parametrize(
    "params",
    [
        {"from": ""},
        {"to": ""},
        {"state": ""},
        {"limit": ""},
        {"cursor": ""},
        {"timezone": ""},
    ],
)
def test_runs_rejects_explicit_empty_query_values(params: dict[str, str]) -> None:
    client = client_for(session_mode="active")

    response = client.get("/api/v1/me/verify/runs", params=params)

    assert response.status_code == 400
    assert response.json()["error"]["code"] in {
        "INVALID_QUERY",
        "INVALID_CURSOR",
    }


@pytest.mark.parametrize(
    "content_type", [None, "text/plain", "application/json-patch+json"]
)
def test_create_requires_json_content_type(content_type: str | None) -> None:
    client = client_for(session_mode="active")
    headers = {
        "Idempotency-Key": "content-type-test",
        "Origin": "http://testserver",
    }
    if content_type is not None:
        headers["Content-Type"] = content_type

    response = client.post(
        "/api/v1/me/verify/runs",
        content='{"date":"2024-01-02","timezone":"UTC","domains":["activity"]}',
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY"


def test_create_accepts_json_charset_and_rejects_oversized_body() -> None:
    client = client_for(session_mode="active")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Idempotency-Key": "charset-test",
        "Origin": "http://testserver",
    }
    accepted = client.post(
        "/api/v1/me/verify/runs",
        content='{"date":"2024-01-02","timezone":"UTC","domains":["activity"]}',
        headers=headers,
    )
    oversized = client.post(
        "/api/v1/me/verify/runs",
        content="{" + '"domains":[' + '"activity",' * 5000 + '"activity"]}',
        headers={**headers, "Idempotency-Key": "oversized-test"},
    )

    assert accepted.status_code == 202
    assert oversized.status_code == 400
    assert oversized.json()["error"]["code"] == "INVALID_QUERY"


@pytest.mark.parametrize(
    "header_case",
    [
        "duplicate_content_length",
        "conflicting_content_length",
        "comma_joined_content_length",
        "duplicate_content_type",
        "comma_joined_content_type",
    ],
)
def test_ambiguous_framing_and_content_headers_fail_before_body_or_state_access(
    header_case: str,
) -> None:
    adapter = OfflineFixtureAdapter()
    calls: list[str] = []
    original = adapter.get_bff_response

    def counted(case: str) -> dict[str, object]:
        calls.append(case)
        return original(case)

    adapter.get_bff_response = counted  # type: ignore[method-assign]
    store = VerificationRunStore()
    client = client_for(session_mode="active", adapter=adapter, store=store)
    body = '{"date":"2024-01-02","timezone":"UTC","domains":["activity"]}'
    content_length = str(len(body.encode("utf-8")))
    raw_headers = {
        "duplicate_content_length": [
            ("Content-Length", content_length),
            ("content-length", content_length),
        ],
        "conflicting_content_length": [
            ("Content-Length", content_length),
            ("CONTENT-LENGTH", str(int(content_length) + 1)),
        ],
        "comma_joined_content_length": [
            ("cOnTeNt-LeNgTh", f"{content_length}, {content_length}"),
        ],
        "duplicate_content_type": [
            ("Content-Type", "application/json"),
            ("content-type", "application/json"),
        ],
        "comma_joined_content_type": [
            ("CONTENT-TYPE", "application/json, application/json"),
        ],
    }[header_case]
    headers = [
        *raw_headers,
        ("Origin", "http://testserver"),
        ("Idempotency-Key", f"ambiguous-{header_case}"),
    ]
    before = store._snapshot_state()

    response = client.post(
        "/api/v1/me/verify/runs",
        content=body,
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY"
    assert response.headers["cache-control"] == "no-store"
    assert calls == []
    assert store._snapshot_state() == before


@pytest.mark.parametrize(
    "content_length",
    ["+1", " 1", "1 ", "-1", "not-a-number", "1,1", "9" * 5000],
)
def test_content_length_requires_a_single_ascii_decimal_value(
    content_length: str,
) -> None:
    adapter = OfflineFixtureAdapter()
    calls: list[str] = []
    original = adapter.get_bff_response

    def counted(case: str) -> dict[str, object]:
        calls.append(case)
        return original(case)

    adapter.get_bff_response = counted  # type: ignore[method-assign]
    store = VerificationRunStore()
    client = client_for(session_mode="active", adapter=adapter, store=store)
    body = '{"date":"2024-01-02","timezone":"UTC","domains":["activity"]}'
    before = store._snapshot_state()

    response = client.post(
        "/api/v1/me/verify/runs",
        content=body,
        headers=[
            ("Content-Length", content_length),
            ("Content-Type", "application/json"),
            ("Origin", "http://testserver"),
            ("Idempotency-Key", "invalid-length-test"),
        ],
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY"
    assert response.json()["error"]["field"] == "Content-Length"
    assert response.headers["cache-control"] == "no-store"
    assert calls == []
    assert store._snapshot_state() == before


def test_single_content_length_and_content_type_are_accepted() -> None:
    client = client_for(session_mode="active")
    body = '{"date":"2024-01-02","timezone":"UTC","domains":["activity"]}'

    response = client.post(
        "/api/v1/me/verify/runs",
        content=body,
        headers=[
            ("Content-Length", str(len(body.encode("utf-8")))),
            ("Content-Type", "application/json; charset=utf-8"),
            ("Origin", "http://testserver"),
            ("Idempotency-Key", "single-content-header"),
        ],
    )

    assert response.status_code == 202
    assert response.json()["data"]["verificationRun"]["state"] == "pending"


def test_duplicate_content_header_is_rejected_before_downstream_receives_body() -> None:
    import bff.main as main_module

    middleware_type = getattr(main_module, "BoundedBodyMiddleware", None)
    assert middleware_type is not None
    downstream_called = False
    receive_called = False
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        nonlocal receive_called
        receive_called = True
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    async def downstream(
        _scope: dict[str, object], receive_fn: object, _send: object
    ) -> None:
        nonlocal downstream_called
        downstream_called = True
        await receive_fn()  # type: ignore[misc]

    middleware = middleware_type(
        downstream,
        max_bytes=main_module.MAX_CREATE_BODY_BYTES,
        catch_errors=True,
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/me/verify/runs",
        "query_string": b"",
        "headers": [
            (b"content-length", b"2"),
            (b"CONTENT-LENGTH", b"2"),
            (b"content-type", b"application/json"),
        ],
    }

    asyncio.run(middleware(scope, receive, send))

    assert sent[0]["status"] == 400
    assert not downstream_called
    assert not receive_called


def test_unlisted_routes_and_wrong_methods_do_not_become_run_not_found() -> None:
    client = client_for(session_mode="active")

    missing = client.get("/api/v1/not-a-route")
    wrong_method = client.post("/api/v1/session")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_unexpected_exceptions_are_generic_and_get_a_synthetic_request_id() -> None:
    client = TestClient(
        create_app(
            environment="test", session_mode="active", adapter=ExplodingAdapter()
        ),
        raise_server_exceptions=False,
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 500
    payload = response.json()
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert payload["error"]["message"] == "The request could not be completed."
    assert payload["error"]["requestId"].startswith("req-demo-")
    assert "provider" not in repr(payload).lower()
    assert "private" not in repr(payload).lower()


def test_api_responses_are_not_cached_on_success_and_error_paths() -> None:
    active = client_for(session_mode="active")
    anonymous = client_for(session_mode="anonymous")
    pending = client_for(session_mode="pending")
    failing = TestClient(
        create_app(
            environment="test", session_mode="active", adapter=ExplodingAdapter()
        ),
        raise_server_exceptions=False,
    )
    responses = [
        active.get("/api/v1/session"),
        active.get(
            "/api/v1/me/verify/overview",
            params={"date": "2024-01-02", "timezone": "UTC"},
        ),
        active.post(
            "/api/v1/me/verify/runs",
            json={
                "date": "2024-01-02",
                "timezone": "UTC",
                "domains": ["activity"],
            },
            headers={
                "Origin": "http://testserver",
                "Idempotency-Key": "no-store-test",
            },
        ),
        active.get(
            "/api/v1/me/verify/overview",
            params={"date": "not-a-date", "timezone": "UTC"},
        ),
        anonymous.get(
            "/api/v1/me/verify/overview",
            params={"date": "2024-01-02", "timezone": "UTC"},
        ),
        pending.get("/api/v1/me/verify/settings"),
        active.get("/api/v1/not-a-route"),
        active.request("HEAD", "/api/v1/session"),
        failing.get(
            "/api/v1/me/verify/overview",
            params={"date": "2024-01-02", "timezone": "UTC"},
        ),
    ]

    assert [response.status_code for response in responses] == [
        200,
        200,
        202,
        400,
        401,
        403,
        404,
        405,
        500,
    ]
    assert all(
        response.headers.get("cache-control") == "no-store" for response in responses
    )


def test_active_synthetic_session_is_allowed_only_in_local_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BFF_ENVIRONMENT", "local")

    client = client_for(session_mode="active")

    assert client.get("/api/v1/session").status_code == 200


@pytest.mark.parametrize("environment", ["production", "staging", "test-server"])
def test_active_synthetic_session_refuses_non_local_environment(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("BFF_ENVIRONMENT", environment)

    with pytest.raises(ValueError, match="local development"):
        create_app(session_mode="active")


@pytest.mark.parametrize(
    "mode", sorted({"active", "anonymous", "pending", "blocked", "expired"})
)
def test_synthetic_sessions_refuse_non_local_allowed_origin(mode: str) -> None:
    with pytest.raises(ValueError, match="local"):
        create_app(
            environment="test",
            session_mode=mode,
            allowed_origin="https://app.example.test",
        )


@pytest.mark.parametrize(
    "field",
    [
        "startedAt",
        "finishedAt",
        "recordsSeen",
        "recordsAccepted",
        "recordsRejected",
        "recordsDuplicated",
        "fieldsUnsupported",
    ],
)
def test_pending_run_rejects_non_null_processing_fields(field: str) -> None:
    def taint_pending(response: dict[str, object]) -> None:
        run = _verification_run(response)
        if field in {
            "recordsSeen",
            "recordsAccepted",
            "recordsRejected",
            "recordsDuplicated",
            "fieldsUnsupported",
        }:
            counts = run["counts"]
            assert isinstance(counts, dict)
            counts["recordsSeen"] = 1
            counts[field] = 1
        else:
            run[field] = "2024-01-02T12:30:00Z"

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("verification_run_create", taint_pending),
    )

    response = client.get("/api/v1/me/verify/runs")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_valid_pending_create_preserves_scope_and_null_processing_fields() -> None:
    client = client_for(session_mode="active")
    body = {
        "date": "2024-01-02",
        "timezone": "UTC",
        "domains": ["activity", "sleep"],
    }

    response = client.post(
        "/api/v1/me/verify/runs",
        json=body,
        headers={
            "Origin": "http://testserver",
            "Idempotency-Key": "pending-shape-test",
        },
    )

    assert response.status_code == 202
    run = response.json()["data"]["verificationRun"]
    assert run["state"] == "pending"
    assert run["startedAt"] is None
    assert run["finishedAt"] is None
    assert run["scope"] == body
    assert run["counts"] == {
        "recordsSeen": None,
        "recordsAccepted": None,
        "recordsRejected": None,
        "recordsDuplicated": None,
        "fieldsUnsupported": None,
    }
    assert run["warnings"] == []


@pytest.mark.parametrize(
    ("warning_index", "domain"),
    [
        (0, None),
        (0, "sleep"),
        (1, None),
        (1, "body"),
        (2, None),
        (2, "activity"),
    ],
)
def test_overview_rejects_wrong_or_missing_semantic_warning_domains(
    warning_index: int, domain: str | None
) -> None:
    def taint_warning_domain(response: dict[str, object]) -> None:
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warning = warnings[warning_index]
        assert isinstance(warning, dict)
        if domain is None:
            warning.pop("domain", None)
        else:
            warning["domain"] = domain

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", taint_warning_domain),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_source_warning_without_declared_domain_remains_valid() -> None:
    client = client_for(session_mode="active")

    response = client.get(
        "/api/v1/me/verify/sources",
        params={"date": "2024-01-03", "timezone": "UTC"},
    )

    assert response.status_code == 200
    assert response.json()["warnings"] == [
        {
            "code": "SOURCE_AMBIGUOUS",
            "severity": "warning",
            "message": "La atribución requiere una regla adicional.",
        }
    ]


def test_sources_require_source_ambiguity_warning() -> None:
    def remove_source_warning(response: dict[str, object]) -> None:
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings.clear()

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("source_ambiguous", remove_source_warning),
    )

    response = client.get(
        "/api/v1/me/verify/sources",
        params={"date": "2024-01-03", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (
            "BODY_RELATIVE_TO_NOW",
            "Body es relativo al momento de consulta.",
        ),
        (
            "CURSOR_EXPIRED",
            "La p\u00e1gina solicitada expir\u00f3; reinicia el listado.",
        ),
        (
            "INCONCLUSIVE",
            "No se pudo cerrar la comparaci\u00f3n porque falt\u00f3 una p\u00e1gina.",
        ),
        (
            "MISMATCH",
            "El hecho observado no coincide con el esperado.",
        ),
        (
            "NOT_VERIFIABLE",
            "La API p\u00fablica no ofrece el schema "
            "necesario para esta afirmaci\u00f3n.",
        ),
        (
            "PARTIAL_COVERAGE",
            "La ventana no se pudo cerrar por completo.",
        ),
        (
            "SOURCE_AMBIGUOUS",
            "La atribuci\u00f3n requiere una regla adicional.",
        ),
        (
            "UNSUPPORTED",
            "La capacidad solicitada no est\u00e1 disponible en el contrato.",
        ),
        (
            "UPSTREAM_LIMITED",
            "La fuente limit\u00f3 el alcance de la consulta.",
        ),
    ],
)
def test_declared_warning_catalog_codes_are_reachable_at_http_boundary(
    code: str, message: str
) -> None:
    def add_warning(response: dict[str, object]) -> None:
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings.append(
            {
                "code": code,
                "severity": "warning",
                "message": message,
            }
        )

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("runs_first_page", add_warning),
    )

    response = client.get("/api/v1/me/verify/runs", params={"limit": 2})

    assert response.status_code == 200
    assert {warning["code"] for warning in response.json()["warnings"]} == {code}


def test_unsupported_warning_accepts_a_contextual_metric_domain() -> None:
    def add_unsupported_warning(response: dict[str, object]) -> None:
        metric = _summary_metric(response, "steps")
        metric.update(
            {
                "state": "unsupported",
                "value": None,
                "unit": None,
                "isDailyTotal": False,
            }
        )
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings.append(
            {
                "code": "UNSUPPORTED",
                "severity": "warning",
                "message": (
                    "La capacidad solicitada no est\u00e1 disponible " "en el contrato."
                ),
                "domain": "activity",
            }
        )

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", add_unsupported_warning),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 200
    warning = next(
        warning
        for warning in response.json()["warnings"]
        if warning["code"] == "UNSUPPORTED"
    )
    assert warning["domain"] == "activity"


def test_unsupported_metric_is_valid_without_the_optional_warning() -> None:
    def make_unsupported(response: dict[str, object]) -> None:
        metric = _summary_metric(response, "steps")
        metric.update(
            {
                "state": "unsupported",
                "value": None,
                "unit": None,
                "isDailyTotal": None,
            }
        )

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", make_unsupported),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["summary"]["steps"]["state"] == "unsupported"
    assert all(
        warning["code"] != "UNSUPPORTED" for warning in response.json()["warnings"]
    )


def test_unsupported_metric_accepts_the_optional_bff_warning() -> None:
    def make_unsupported(response: dict[str, object]) -> None:
        metric = _summary_metric(response, "steps")
        metric.update(
            {
                "state": "unsupported",
                "value": None,
                "unit": None,
                "isDailyTotal": None,
            }
        )
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings.append(
            {
                "code": "UNSUPPORTED",
                "severity": "warning",
                "message": "La capacidad solicitada no está disponible en el contrato.",
                "domain": "activity",
            }
        )

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", make_unsupported),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 200
    assert any(
        warning["code"] == "UNSUPPORTED" for warning in response.json()["warnings"]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda response: response["warnings"].append(
            {
                "code": "UNSUPPORTED",
                "severity": "warning",
                "message": "provider warning details",
                "domain": "activity",
            }
        ),
        lambda response: response["warnings"].append(
            {
                "code": "UNSUPPORTED",
                "severity": "warning",
                "message": "La capacidad solicitada no está disponible en el contrato.",
                "domain": "sleep",
            }
        ),
        lambda response: response["warnings"].append(
            {
                "code": "NOT_VERIFIABLE",
                "severity": "warning",
                "message": "La capacidad solicitada no está disponible en el contrato.",
                "domain": "activity",
            }
        ),
    ],
)
def test_unsupported_warning_rejects_wrong_code_domain_or_copy(
    mutation: object,
) -> None:
    def make_unsupported(response: dict[str, object]) -> None:
        metric = _summary_metric(response, "steps")
        metric.update(
            {
                "state": "unsupported",
                "value": None,
                "unit": None,
                "isDailyTotal": None,
            }
        )
        mutation(response)

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", make_unsupported),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (
            "CURSOR_EXPIRED",
            "La p\u00e1gina solicitada expir\u00f3; reinicia el listado.",
        ),
        (
            "UNSUPPORTED",
            "La capacidad solicitada no est\u00e1 disponible en el contrato.",
        ),
        (
            "UPSTREAM_LIMITED",
            "La fuente limit\u00f3 el alcance de la consulta.",
        ),
    ],
)
def test_warning_catalog_rejects_unknown_copy(code: str, message: str) -> None:
    del message

    def add_unknown_copy(response: dict[str, object]) -> None:
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings.append(
            {
                "code": code,
                "severity": "warning",
                "message": "provider warning details",
            }
        )

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("runs_first_page", add_unknown_copy),
    )

    response = client.get("/api/v1/me/verify/runs", params={"limit": 2})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"
    assert "provider warning details" not in repr(response.json())


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (
            "CURSOR_EXPIRED",
            "La p\u00e1gina solicitada expir\u00f3; reinicia el listado.",
        ),
        (
            "UPSTREAM_LIMITED",
            "La fuente limit\u00f3 el alcance de la consulta.",
        ),
    ],
)
def test_query_level_warning_rejects_a_health_domain(code: str, message: str) -> None:
    def add_wrong_domain(response: dict[str, object]) -> None:
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings.append(
            {
                "code": code,
                "severity": "warning",
                "message": message,
                "domain": "activity",
            }
        )

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("runs_first_page", add_wrong_domain),
    )

    response = client.get("/api/v1/me/verify/runs", params={"limit": 2})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_warning_model_binds_copy_to_its_declared_code() -> None:
    with pytest.raises(ValidationError):
        WarningModel(
            code="CURSOR_EXPIRED",
            severity="warning",
            message="La capacidad solicitada no está disponible en el contrato.",
        )


def test_overview_sources_require_source_ambiguity_warning() -> None:
    def remove_source_warning(response: dict[str, object]) -> None:
        data = response["data"]
        assert isinstance(data, dict)
        data["sources"] = [
            {
                "sourceKey": "source-demo-a",
                "label": "Fuente sintética A",
                "state": "source_ambiguous",
                "capabilities": ["heart_rate"],
            }
        ]
        summary = data["summary"]
        assert isinstance(summary, dict)
        heart_rate = summary["heartRate"]
        assert isinstance(heart_rate, dict)
        heart_rate["state"] = "value"
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings[:] = [
            warning for warning in warnings if warning["code"] != "SOURCE_AMBIGUOUS"
        ]

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", remove_source_warning),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


class AlwaysFailingInstallStore(VerificationRunStore):
    def _install_item(
        self,
        item: dict[str, object],
        owner_session_key: str,
        *,
        owner_key: str,
        listed: bool,
        ow_user_key: str | None = None,
    ) -> None:
        super()._install_item(
            item,
            owner_session_key,
            owner_key=owner_key,
            ow_user_key=ow_user_key,
            listed=listed,
        )
        if item["runKey"] == "verify-demo-02":
            raise error_for("UPSTREAM_INVALID")


def test_seed_install_failure_rolls_back_before_list_and_detail_retry() -> None:
    store = AlwaysFailingInstallStore()
    client = client_for(
        session_mode="active",
        session_key="synthetic-session-seed-install-failure",
        store=store,
    )

    failed_list = client.get("/api/v1/me/verify/runs")
    failed_detail = client.get("/api/v1/me/verify/runs/verify-demo-01")

    assert failed_list.status_code == 502
    assert failed_detail.status_code == 502
    assert failed_list.json()["error"]["code"] == "UPSTREAM_INVALID"
    assert failed_detail.json()["error"]["code"] == "UPSTREAM_INVALID"
    assert store.is_empty
    assert store._idempotency == {}


class FailingIdempotencyMap(dict):
    fail_next = True

    def __setitem__(self, key: object, value: object) -> None:
        super().__setitem__(key, value)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("synthetic idempotency write failure")


class FailingCursorCleanupMap(dict):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fail_next = True

    def pop(self, key: object, default: object = None) -> object:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("synthetic cursor cleanup failure")
        return super().pop(key, default)


def test_rollback_cursor_cleanup_is_atomic_on_cleanup_failure() -> None:
    store = VerificationRunStore()
    owner_session_key = "synthetic-session-rollback-cleanup"
    owner_key = "owner-demo-rollback-cleanup"
    record, created = store.create(
        owner_session_key=owner_session_key,
        owner_key=owner_key,
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("activity",),
        idempotency_key="rollback-cleanup-key",
    )
    assert created is True
    context = CursorContext(
        session_key=owner_session_key,
        from_date=None,
        to_date=None,
        state=None,
        limit=1,
        timezone="UTC",
        owner_key=owner_key,
    )
    cursor = store._register_cursor(context, 0, (record.run_key,))
    store._cursors = FailingCursorCleanupMap(store._cursors)
    before = store._snapshot_state()

    with pytest.raises(RuntimeError, match="cursor cleanup"):
        store.rollback_create(
            owner_session_key=owner_session_key,
            owner_key=owner_key,
            idempotency_key="rollback-cleanup-key",
            scope_date="2024-01-02",
            scope_timezone="UTC",
            domains=("activity",),
            record=record,
        )

    assert store._snapshot_state() == before
    assert store._runs[record.run_key] == record
    assert cursor in store._cursors


def test_preseeded_idempotency_replay_skips_seed_and_adapter_access() -> None:
    store = VerificationRunStore()
    owner_session_key = "synthetic-session-replay-before-seed"
    owner_key = "owner-demo-replay-before-seed"
    record, created = store.create(
        owner_session_key=owner_session_key,
        owner_key=owner_key,
        ow_user_key="ow-link:synthetic-session-replay-before-seed",
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("activity",),
        idempotency_key="replay-before-seed-key",
    )
    assert created is True
    adapter = AlwaysFailingAdapter()
    client = client_for(
        session_mode="active",
        session_key=owner_session_key,
        owner_key=owner_key,
        adapter=adapter,
        store=store,
    )

    response = client.post(
        "/api/v1/me/verify/runs",
        json=_create_body(),
        headers={
            "Origin": "http://testserver",
            "Idempotency-Key": "replay-before-seed-key",
        },
    )

    assert response.status_code == 202
    assert response.json()["data"]["verificationRun"]["runKey"] == record.run_key
    assert adapter.calls == 0
    assert store.is_seeded(owner_session_key, owner_key) is False


def test_commit_failure_rolls_back_record_mapping_and_run_number() -> None:
    store = VerificationRunStore()
    store._idempotency = FailingIdempotencyMap()
    client = TestClient(
        create_app(
            environment="test",
            session_mode="active",
            session_key="synthetic-session-commit-failure",
            store=store,
        ),
        raise_server_exceptions=False,
    )
    body = {
        "date": "2024-01-02",
        "timezone": "UTC",
        "domains": ["activity"],
    }
    headers = {
        "Origin": "http://testserver",
        "Idempotency-Key": "commit-atomicity-test",
    }

    failed = client.post("/api/v1/me/verify/runs", json=body, headers=headers)
    listed = client.get("/api/v1/me/verify/runs", params={"limit": 100})
    missing = client.get("/api/v1/me/verify/runs/verify-demo-09")

    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "INTERNAL_ERROR"
    assert store.get("verify-demo-09", "synthetic-session-commit-failure") is None
    assert store._idempotency == {}
    assert "verify-demo-09" not in {
        item["runKey"] for item in listed.json()["data"]["items"]
    }
    assert missing.status_code == 404

    created = client.post("/api/v1/me/verify/runs", json=body, headers=headers)
    replayed = client.post("/api/v1/me/verify/runs", json=body, headers=headers)

    assert created.status_code == 202
    assert created.json()["data"]["verificationRun"]["runKey"] == "verify-demo-09"
    assert replayed.status_code == 202
    assert replayed.json()["data"] == created.json()["data"]


def _create_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "date": "2024-01-02",
        "timezone": "UTC",
        "domains": ["activity"],
    }
    body.update(overrides)
    return body


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"timezone": "UTC", "domains": ["activity"]}, "date"),
        ({"date": "2024-01-02", "domains": ["activity"]}, "timezone"),
        (_create_body(date=""), "date"),
        (_create_body(timezone=""), "timezone"),
        (_create_body(date="2024-02-30"), "date"),
        (_create_body(date="not-a-date"), "date"),
        (_create_body(timezone="Not/AZone"), "timezone"),
    ],
)
def test_create_classifies_date_and_timezone_errors_as_invalid_query(
    body: dict[str, object], field: str
) -> None:
    client = client_for(session_mode="active")

    response = client.post(
        "/api/v1/me/verify/runs",
        json=body,
        headers={
            "Origin": "http://testserver",
            "Idempotency-Key": f"invalid-{field}-{len(repr(body))}",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY"
    assert response.json()["error"]["field"] == field
    assert "validation" not in repr(response.json()).lower()


@pytest.mark.parametrize(
    "body",
    [
        _create_body(domains=[]),
        _create_body(domains=["not-allowed"]),
        _create_body(domains=[""]),
        _create_body(domains=["activity", "activity"]),
        _create_body(domains="activity"),
    ],
)
def test_create_classifies_invalid_domains_as_invalid_scope(
    body: dict[str, object],
) -> None:
    client = client_for(session_mode="active")

    response = client.post(
        "/api/v1/me/verify/runs",
        json=body,
        headers={
            "Origin": "http://testserver",
            "Idempotency-Key": f"invalid-domains-{len(repr(body))}",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_SCOPE"
    assert response.json()["error"]["field"] == "domains"
    assert "validation" not in repr(response.json()).lower()


class PostSeedInvalidPendingStore(VerificationRunStore):
    def seed_from_adapter(
        self,
        adapter: object,
        owner_session_key: str,
        *,
        owner_key: str,
        ow_user_key: str | None = None,
    ) -> None:
        super().seed_from_adapter(
            adapter,
            owner_session_key,
            owner_key=owner_key,
            ow_user_key=ow_user_key,
        )
        pending = self._runs["verify-demo-03"]
        pending.results = [{"metric": "steps", "state": "match"}]


def test_serializer_rejects_a_pending_record_even_when_the_adapter_was_validated() -> (
    None
):
    store = PostSeedInvalidPendingStore()
    client = client_for(session_mode="active", store=store)

    response = client.get("/api/v1/me/verify/runs/verify-demo-03")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"
    assert "match" not in repr(response.json())


def test_overview_requires_partial_warning_when_a_metric_is_partial() -> None:
    def remove_partial_warning(response: dict[str, object]) -> None:
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings[:] = [
            warning for warning in warnings if warning["code"] != "PARTIAL_COVERAGE"
        ]

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", remove_partial_warning),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_overview_requires_source_ambiguity_warning_when_a_metric_is_ambiguous() -> (
    None
):
    def remove_ambiguity_warning(response: dict[str, object]) -> None:
        warnings = response["warnings"]
        assert isinstance(warnings, list)
        warnings[:] = [
            warning for warning in warnings if warning["code"] != "SOURCE_AMBIGUOUS"
        ]

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("overview_mixed", remove_ambiguity_warning),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


@pytest.mark.parametrize("domain", ["body"])
def test_partial_run_rejects_wrong_warning_domain(domain: str) -> None:
    def taint_partial_warning(response: dict[str, object]) -> None:
        run = _verification_run(response)
        scope = run["scope"]
        assert isinstance(scope, dict)
        scope["domains"] = ["activity", "sleep"]
        warnings = run["warnings"]
        assert isinstance(warnings, list)
        warning = warnings[0]
        assert isinstance(warning, dict)
        warning["domain"] = domain

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("verification_run_partial", taint_partial_warning),
    )

    response = client.get("/api/v1/me/verify/runs/verify-demo-02")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


@pytest.mark.parametrize(
    ("run_key", "warning_code"),
    [
        ("verify-demo-02", "PARTIAL_COVERAGE"),
        ("verify-demo-06", "NOT_VERIFIABLE"),
        ("verify-demo-07", "MISMATCH"),
        ("verify-demo-08", "INCONCLUSIVE"),
    ],
)
def test_current_run_warnings_preserve_omitted_domains(
    run_key: str, warning_code: str
) -> None:
    response = client_for(session_mode="active").get(
        f"/api/v1/me/verify/runs/{run_key}"
    )

    assert response.status_code == 200
    warning = next(
        warning
        for warning in response.json()["data"]["verificationRun"]["warnings"]
        if warning["code"] == warning_code
    )
    assert "domain" not in warning


@pytest.mark.parametrize(
    ("case", "run_key", "domain"),
    [
        ("verification_run_partial", "verify-demo-02", "sleep"),
        ("verification_not_verifiable", "verify-demo-06", "activity"),
        ("verification_run_mismatch", "verify-demo-07", "sleep"),
        ("verification_inconclusive", "verify-demo-08", "sleep"),
    ],
)
def test_run_warning_rejects_an_incorrect_declared_domain(
    case: str, run_key: str, domain: str
) -> None:
    def declare_wrong_domain(response: dict[str, object]) -> None:
        warning = _verification_run(response)["warnings"][0]
        assert isinstance(warning, dict)
        warning["domain"] = domain

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter(case, declare_wrong_domain),
    )

    response = client.get(f"/api/v1/me/verify/runs/{run_key}")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


def test_run_warning_preserves_a_correctly_declared_domain() -> None:
    def declare_activity_domain(response: dict[str, object]) -> None:
        warning = _verification_run(response)["warnings"][0]
        assert isinstance(warning, dict)
        warning["domain"] = "activity"

    client = client_for(
        session_mode="active",
        adapter=RunTaintedAdapter("verification_run_partial", declare_activity_domain),
    )

    response = client.get("/api/v1/me/verify/runs/verify-demo-02")

    assert response.status_code == 200
    assert response.json()["data"]["verificationRun"]["warnings"][0]["domain"] == (
        "activity"
    )


class FailOnceInstallStore(VerificationRunStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_install = True

    def _install_item(
        self,
        item: dict[str, object],
        owner_session_key: str,
        *,
        owner_key: str,
        listed: bool,
        ow_user_key: str | None = None,
    ) -> None:
        super()._install_item(
            item,
            owner_session_key,
            owner_key=owner_key,
            listed=listed,
            ow_user_key=ow_user_key,
        )
        if self.fail_next_install and item["runKey"] == "verify-demo-02":
            self.fail_next_install = False
            raise error_for("UPSTREAM_INVALID")


def test_seed_failure_restores_all_prior_state_and_retry_succeeds() -> None:
    from bff.store import CursorContext

    store = FailOnceInstallStore()
    owner = "synthetic-session-seed-retry"
    store.create(
        owner_session_key=owner,
        owner_key="owner-demo-seed-retry",
        scope_date="2024-01-01",
        scope_timezone="UTC",
        domains=("activity",),
        idempotency_key="existing-a",
    )
    store.create(
        owner_session_key=owner,
        owner_key="owner-demo-seed-retry",
        scope_date="2024-01-02",
        scope_timezone="UTC",
        domains=("sleep",),
        idempotency_key="existing-b",
    )
    context = CursorContext(
        session_key=owner,
        from_date=None,
        to_date=None,
        state=None,
        limit=1,
        timezone="UTC",
        owner_key="owner-demo-seed-retry",
    )
    store.list_page(
        context=context,
        from_date=None,
        to_date=None,
        state=None,
        cursor=None,
    )
    before = store._snapshot_state()

    with pytest.raises(BFFError) as caught:
        store.seed_from_adapter(
            OfflineFixtureAdapter(),
            owner,
            owner_key="owner-demo-seed-retry",
        )

    assert caught.value.code == "UPSTREAM_INVALID"
    after = store._snapshot_state()
    assert after == before

    store.seed_from_adapter(
        OfflineFixtureAdapter(),
        owner,
        owner_key="owner-demo-seed-retry",
    )
    assert "verify-demo-04" in store._runs
    assert store._next_number == 9
    assert store._cursors
    assert (
        store._idempotency[(owner, "owner-demo-seed-retry", None, "existing-a")][1]
        == "verify-demo-01"
    )


class FailOnceFinalizeStore(VerificationRunStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_finalize = True

    def _finalize_create(
        self,
        *,
        owner_session_key: str,
        idempotency_key: str,
        record: object,
    ) -> None:
        del owner_session_key, idempotency_key, record
        if self.fail_next_finalize:
            self.fail_next_finalize = False
            raise RuntimeError("synthetic finalization failure")


def test_commit_finalization_failure_restores_state_and_retry_succeeds() -> None:
    store = FailOnceFinalizeStore()
    client = TestClient(
        create_app(
            environment="test",
            session_mode="active",
            session_key="synthetic-session-commit-finalize",
            store=store,
        ),
        raise_server_exceptions=False,
    )
    body = _create_body()
    headers = {
        "Origin": "http://testserver",
        "Idempotency-Key": "commit-finalize-test",
    }

    failed = client.post("/api/v1/me/verify/runs", json=body, headers=headers)
    listed = client.get("/api/v1/me/verify/runs", params={"limit": 100})
    missing = client.get("/api/v1/me/verify/runs/verify-demo-09")

    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "INTERNAL_ERROR"
    assert store.get("verify-demo-09", "synthetic-session-commit-finalize") is None
    assert store._idempotency == {}
    assert "verify-demo-09" not in {
        item["runKey"] for item in listed.json()["data"]["items"]
    }
    assert missing.status_code == 404

    created = client.post("/api/v1/me/verify/runs", json=body, headers=headers)
    replayed = client.post("/api/v1/me/verify/runs", json=body, headers=headers)

    assert created.status_code == 202
    assert created.json()["data"]["verificationRun"]["runKey"] == "verify-demo-09"
    assert replayed.status_code == 202
    assert replayed.json()["data"] == created.json()["data"]


def test_duplicate_json_body_keys_are_rejected_before_last_value_wins() -> None:
    client = client_for(session_mode="active")
    response = client.post(
        "/api/v1/me/verify/runs",
        content=(
            '{"date":"2024-01-02","date":"2024-01-03",'
            '"timezone":"UTC","domains":["activity"]}'
        ),
        headers={
            "Content-Type": "application/json",
            "Origin": "http://testserver",
            "Idempotency-Key": "duplicate-json-key",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY"
    assert response.json()["error"]["field"] == "body"


def test_duplicate_scalar_query_parameters_are_rejected() -> None:
    client = client_for(session_mode="active")
    response = client.get(
        "/api/v1/me/verify/overview?date=2024-01-02&date=2024-01-03&timezone=UTC"
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY"
    assert response.json()["error"]["field"] == "date"


@pytest.mark.parametrize(
    ("duplicate_header", "field"),
    [("Origin", "Origin"), ("Idempotency-Key", "Idempotency-Key")],
)
def test_duplicate_security_headers_are_rejected(
    duplicate_header: str, field: str
) -> None:
    headers = [
        ("Origin", "http://testserver"),
        ("Idempotency-Key", "duplicate-header-key"),
        (
            duplicate_header,
            "http://testserver" if duplicate_header == "Origin" else "second-key",
        ),
    ]
    client = client_for(session_mode="active")

    response = client.post(
        "/api/v1/me/verify/runs",
        json=_create_body(),
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY"
    assert response.json()["error"]["field"] == field


def test_missing_environment_cannot_enable_an_active_synthetic_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BFF_ENVIRONMENT", raising=False)
    monkeypatch.delenv("BFF_SYNTHETIC_SESSION_MODE", raising=False)

    with pytest.raises(ValueError, match="BFF_ENVIRONMENT"):
        create_app(session_mode="active")


def test_overview_rejects_missing_applicable_adapter_request_window() -> None:
    def remove_requested_window(response: dict[str, object]) -> None:
        coverage = response["coverage"]
        assert isinstance(coverage, dict)
        del coverage["requested"]

    client = client_for(
        session_mode="active",
        adapter=SemanticTaintedAdapter(remove_requested_window),
    )

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "2024-01-02", "timezone": "UTC"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_INVALID"


class FailingRequestCounter:
    def __next__(self) -> int:
        raise RuntimeError("synthetic counter failure")


@pytest.mark.parametrize("counter", [iter(()), FailingRequestCounter()])
def test_request_id_counter_failure_still_returns_json_no_store_error(
    counter: object,
) -> None:
    app = create_app(environment="test", session_mode="active")
    app.state.request_counter = counter
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/api/v1/me/verify/overview",
        params={"date": "not-a-date", "timezone": "UTC"},
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["error"]["code"] == "INVALID_QUERY"
    assert payload["error"]["requestId"] == "req-demo-fallback"
    assert "/api/" not in payload["error"]["requestId"]


def test_request_id_counter_is_non_exhausting_for_repeated_errors() -> None:
    app = create_app(environment="test", session_mode="active")
    client = TestClient(app)

    responses = [
        client.get(
            "/api/v1/me/verify/overview",
            params={"date": "not-a-date", "timezone": "UTC"},
        )
        for _ in range(3)
    ]

    assert [response.status_code for response in responses] == [400, 400, 400]
    request_ids = [response.json()["error"]["requestId"] for response in responses]
    assert len(set(request_ids)) == 3
    assert all(request_id.startswith("req-demo-") for request_id in request_ids)
