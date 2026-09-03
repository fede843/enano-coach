from __future__ import annotations

import ipaddress
from copy import deepcopy
from urllib.parse import urlsplit
from urllib.request import ProxyHandler

import pytest
from fastapi.testclient import TestClient

import adapter.live as live_module
from adapter.live import LiveOWAdapter, LiveOWClient, LiveOWError, _UrllibTransport
from bff.main import create_app
from bff.serializers import (
    serialize_overview,
    serialize_sources,
    validate_adapter_error_response,
)
from bff.session import OwnerContext

OWNER = OwnerContext(
    principal_key="principal-live-demo",
    owner_key="owner-live-demo",
    ow_user_key="00000000-0000-4000-8000-000000000001",
)
BASE_URL = "https://ow.example.test"


def _ipv4(value: int) -> str:
    return str(ipaddress.IPv4Address(value))


RFC1918_HTTP_URLS = (
    f"http://{_ipv4(0x0A000001)}:8000",
    f"http://{_ipv4(0xAC100001)}:8000",
    f"http://{_ipv4(0xC0A80001)}:8000",
)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: object,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {"content-type": "application/json"}

    def json(self) -> object:
        return deepcopy(self._payload)


class FakeTransport:
    def __init__(self, responses: dict[str, FakeResponse | Exception]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: tuple[tuple[str, str], ...],
        timeout: float,
        follow_redirects: bool,
    ) -> FakeResponse:
        path = urlsplit(url).path
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "params": params,
                "timeout": timeout,
                "follow_redirects": follow_redirects,
            }
        )
        result = self.responses[path]
        if isinstance(result, Exception):
            raise result
        return result


def _page(
    items: list[dict[str, object]], *, has_more: bool = False
) -> dict[str, object]:
    return {
        "data": items,
        "pagination": {
            "next_cursor": "cursor-live-demo" if has_more else None,
            "previous_cursor": None,
            "has_more": has_more,
            "total_count": None,
        },
        "metadata": {
            "resolution": None,
            "sample_count": len(items),
            "start_time": None,
            "end_time": None,
        },
    }


def _source(
    *,
    source: str = "source-live-a",
    provider: str = "provider-live",
) -> dict[str, object]:
    return {
        "provider": provider,
        "source": source,
        "device": "watch-live-demo",
        "device_type": "watch",
    }


def _data_sources(*, count: int = 1) -> FakeResponse:
    items = [
        {
            "id": f"source-record-live-{index}",
            "user_id": OWNER.ow_user_key,
            "provider": "provider-live",
            "user_connection_id": None,
            "device_model": "watch-live-demo",
            "software_version": "fixture-live-v1",
            "source": f"source-live-{chr(96 + index)}",
            "device_type": "watch",
            "original_source_name": "private source name must not cross",
            "display_name": "private display name must not cross",
        }
        for index in range(1, count + 1)
    ]
    return FakeResponse(200, {"items": items, "total": count})


def _activity(*, source: str = "source-live-a") -> FakeResponse:
    return FakeResponse(
        200,
        _page(
            [
                {
                    "date": "2024-01-02",
                    "source": _source(source=source),
                    "steps": 8123,
                    "distance_meters": 5300,
                    "floors_climbed": 4,
                    "elevation_meters": 18,
                    "active_calories_kcal": 0,
                    "total_calories_kcal": 1680,
                    "active_minutes": 35,
                    "sedentary_minutes": None,
                    "intensity_minutes": {
                        "light": 20,
                        "moderate": 10,
                        "vigorous": 5,
                    },
                    "heart_rate": {"avg_bpm": 72, "max_bpm": 141, "min_bpm": 51},
                }
            ]
        ),
    )


def _sleep_summary() -> FakeResponse:
    return FakeResponse(
        200,
        _page(
            [
                {
                    "date": "2024-01-02",
                    "source": _source(),
                    "start_time": "2024-01-01T22:30:00Z",
                    "end_time": "2024-01-02T06:30:00Z",
                    "duration_minutes": 420,
                    "total_duration_minutes": 420,
                    "time_in_bed_minutes": 480,
                    "efficiency_percent": 87.5,
                    "stages": {
                        "awake_minutes": 45,
                        "light_minutes": 260,
                        "deep_minutes": 100,
                        "rem_minutes": 60,
                    },
                    "sessions": None,
                    "nap_count": 0,
                    "nap_duration_minutes": 0,
                    "avg_heart_rate_bpm": 60,
                    "avg_hrv_sdnn_ms": None,
                    "avg_hrv_rmssd_ms": None,
                    "avg_respiratory_rate": None,
                    "avg_spo2_percent": None,
                }
            ]
        ),
    )


def _sleep_events() -> FakeResponse:
    return FakeResponse(
        200,
        _page(
            [
                {
                    "id": "sleep-event-live-01",
                    "date": "2024-01-02",
                    "start_time": "2024-01-01T22:30:00Z",
                    "end_time": "2024-01-02T06:30:00Z",
                    "duration_seconds": 28800,
                    "sleep_duration_seconds": 25200,
                    "is_nap": False,
                    "source": _source(),
                    "sleep_stage_intervals": [],
                }
            ]
        ),
    )


def _recovery(*, recovery_score: int | None = None) -> FakeResponse:
    return FakeResponse(
        200,
        _page(
            [
                {
                    "date": "2024-01-02",
                    "source": _source(),
                    "sleep_duration_seconds": None,
                    "sleep_efficiency_percent": None,
                    "resting_heart_rate_bpm": 55,
                    "avg_hrv_sdnn_ms": None,
                    "avg_spo2_percent": None,
                    "recovery_score": recovery_score,
                }
            ]
        ),
    )


def _transport(
    *, source_count: int = 1, recovery_score: int | None = None
) -> FakeTransport:
    return FakeTransport(
        {
            "/api/v1/users/00000000-0000-4000-8000-000000000001/data-sources": _data_sources(
                count=source_count
            ),
            "/api/v1/users/00000000-0000-4000-8000-000000000001/summaries/activity": _activity(),
            "/api/v1/users/00000000-0000-4000-8000-000000000001/summaries/sleep": _sleep_summary(),
            "/api/v1/users/00000000-0000-4000-8000-000000000001/events/sleep": _sleep_events(),
            "/api/v1/users/00000000-0000-4000-8000-000000000001/summaries/recovery": _recovery(
                recovery_score=recovery_score
            ),
        }
    )


def _adapter(transport: FakeTransport, **kwargs: object) -> LiveOWAdapter:
    return LiveOWAdapter(
        base_url=BASE_URL,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=transport,
        **kwargs,
    )


def test_client_uses_fixed_get_paths_server_headers_and_no_redirects() -> None:
    transport = _transport()
    client = LiveOWClient(
        base_url=BASE_URL,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=transport,
        timeout_seconds=3.5,
    )

    client.get_data_sources(owner_context=OWNER)

    call = transport.calls[0]
    assert call["url"] == f"{BASE_URL}/api/v1/users/{OWNER.ow_user_key}/data-sources"
    assert call["headers"] == {
        "Accept": "application/json",
        "X-Open-Wearables-API-Key": "ow-api-key-live-demo",
    }
    assert call["timeout"] == 3.5
    assert call["follow_redirects"] is False
    assert "ow-api-key-live-demo" not in repr(client)


def test_client_prefers_bearer_token_when_both_credentials_are_configured() -> None:
    transport = _transport()
    client = LiveOWClient(
        base_url=BASE_URL,
        bearer_token="bearer-token-live-demo",
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=transport,
    )

    client.get_data_sources(owner_context=OWNER)

    assert transport.calls[0]["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer bearer-token-live-demo",
    }
    assert "bearer-token-live-demo" not in repr(client)


def test_client_rejects_unallowlisted_relative_path() -> None:
    client = LiveOWClient(
        base_url=BASE_URL,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=_transport(),
    )

    with pytest.raises(LiveOWError) as error:
        client.request_json(
            owner_context=OWNER,
            relative_path="/api/v1/users/00000000-0000-4000-8000-000000000001/not-allowlisted",
            params=(),
        )

    assert error.value.code == "UPSTREAM_INVALID"
    assert "not-allowlisted" not in str(error.value)


@pytest.mark.parametrize(
    "params",
    [
        (
            ("start_date", "2024-01-02"),
            ("unexpected", "value"),
        ),
        (("start_date", "not-a-date"),),
        (
            ("start_date", "2024-01-02"),
            ("limit", "401"),
        ),
    ],
)
def test_client_rejects_unexpected_query_keys_and_values_before_transport(
    params: tuple[tuple[str, str], ...],
) -> None:
    transport = _transport()
    client = LiveOWClient(
        base_url=BASE_URL,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=transport,
    )

    with pytest.raises(LiveOWError) as error:
        client.request_json(
            owner_context=OWNER,
            relative_path="/api/v1/users/00000000-0000-4000-8000-000000000001/summaries/activity",
            params=params,
        )

    assert error.value.code == "UPSTREAM_INVALID"
    assert transport.calls == []


def test_client_preserves_allowlisted_read_query_params() -> None:
    transport = _transport()
    client = LiveOWClient(
        base_url=BASE_URL,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=transport,
    )

    client.get_activity_summary(
        owner_context=OWNER,
        start_date="2024-01-02T00:00:00Z",
        end_date="2024-01-03T00:00:00Z",
    )
    client.request_json(
        owner_context=OWNER,
        relative_path="/api/v1/users/00000000-0000-4000-8000-000000000001/events/sleep",
        params=(
            ("start_date", "2024-01-02T00:00:00Z"),
            ("end_date", "2024-01-03T00:00:00Z"),
            ("filter_by_priority", "true"),
            ("limit", "100"),
        ),
    )

    assert transport.calls[0]["params"] == (
        ("start_date", "2024-01-02T00:00:00Z"),
        ("end_date", "2024-01-03T00:00:00Z"),
        ("limit", "400"),
    )
    assert transport.calls[1]["params"] == (
        ("start_date", "2024-01-02T00:00:00Z"),
        ("end_date", "2024-01-03T00:00:00Z"),
        ("filter_by_priority", "true"),
        ("limit", "100"),
    )


def test_client_rejects_cleartext_ow_url_outside_loopback() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        LiveOWClient(
            base_url="http://ow.example.test",
            api_key="ow-api-key-live-demo",
            expected_owner_context=OWNER,
            transport=_transport(),
        )


@pytest.mark.parametrize("base_url", RFC1918_HTTP_URLS)
def test_client_rejects_rfc1918_cleartext_by_default(base_url: str) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        LiveOWClient(
            base_url=base_url,
            api_key="ow-api-key-live-demo",
            expected_owner_context=OWNER,
            transport=_transport(),
        )


@pytest.mark.parametrize(
    "address",
    [
        0x0A000000,
        0x0AFFFFFF,
        0xAC100000,
        0xAC1FFFFF,
        0xC0A80000,
        0xC0A8FFFF,
    ],
)
def test_client_accepts_exact_rfc1918_boundaries_with_opt_in(address: int) -> None:
    client = LiveOWClient(
        base_url=f"http://{_ipv4(address)}:8000",
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=_transport(),
        allow_private_http=True,
    )

    assert "http://" not in repr(client)
    assert _ipv4(address) not in repr(client)


@pytest.mark.parametrize(
    "base_url",
    [f"http://{_ipv4(0x0A000001)}", f"http://{_ipv4(0x0A000001)}:"],
)
def test_client_private_http_opt_in_requires_explicit_port(base_url: str) -> None:
    with pytest.raises(ValueError, match="OW_API_BASE_URL"):
        LiveOWClient(
            base_url=base_url,
            api_key="ow-api-key-live-demo",
            expected_owner_context=OWNER,
            transport=_transport(),
            allow_private_http=True,
        )


def test_client_private_http_opt_in_rejects_zero_port() -> None:
    with pytest.raises(ValueError, match="OW_API_BASE_URL"):
        LiveOWClient(
            base_url=f"http://{_ipv4(0x0A000001)}:0",
            api_key="ow-api-key-live-demo",
            expected_owner_context=OWNER,
            transport=_transport(),
            allow_private_http=True,
        )


@pytest.mark.parametrize("port", [1, 65535])
def test_client_private_http_opt_in_accepts_valid_port_boundaries(port: int) -> None:
    LiveOWClient(
        base_url=f"http://{_ipv4(0x0A000001)}:{port}",
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=_transport(),
        allow_private_http=True,
    )


def test_client_private_http_opt_in_rejects_port_above_range() -> None:
    with pytest.raises(ValueError, match="OW_API_BASE_URL"):
        LiveOWClient(
            base_url=f"http://{_ipv4(0x0A000001)}:65536",
            api_key="ow-api-key-live-demo",
            expected_owner_context=OWNER,
            transport=_transport(),
            allow_private_http=True,
        )


@pytest.mark.parametrize(
    "host",
    [
        _ipv4(0x09FFFFFF),
        _ipv4(0x0B000000),
        _ipv4(0xAC0FFFFF),
        _ipv4(0xAC200000),
        _ipv4(0xC0A7FFFF),
        _ipv4(0xC0A90000),
        _ipv4(0x64400001),
        _ipv4(0xA9FE0001),
        _ipv4(0xE0000001),
        _ipv4(0x00000000),
        _ipv4(0xC0000201),
        "ow.example.test",
        f"[{ipaddress.IPv6Address(0xFD << 120)}]",
    ],
)
def test_client_private_http_opt_in_rejects_non_rfc1918_hosts(host: str) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        LiveOWClient(
            base_url=f"http://{host}:8000",
            api_key="ow-api-key-live-demo",
            expected_owner_context=OWNER,
            transport=_transport(),
            allow_private_http=True,
        )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
    ],
)
def test_client_keeps_loopback_http_accepted_without_private_opt_in(
    base_url: str,
) -> None:
    LiveOWClient(
        base_url=base_url,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=_transport(),
    )


@pytest.mark.parametrize(
    "base_url",
    [BASE_URL, f"https://{_ipv4(0xC0A80001)}:8443"],
)
def test_client_keeps_https_behavior_without_private_opt_in(base_url: str) -> None:
    LiveOWClient(
        base_url=base_url,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=_transport(),
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://user@localhost:8000",
        "http://localhost:8000/api",
        "http://localhost:8000/?query=value",
        "http://localhost:8000/#fragment",
        "ftp://localhost:8000",
        "http://localhost:invalid",
        "http://localhost:70000",
        "http://:8000",
        "http:///",
    ],
)
def test_client_rejects_malformed_or_extended_base_urls(base_url: str) -> None:
    with pytest.raises(ValueError, match="OW_API_BASE_URL"):
        LiveOWClient(
            base_url=base_url,
            api_key="ow-api-key-live-demo",
            expected_owner_context=OWNER,
            transport=_transport(),
            allow_private_http=True,
        )


def test_urllib_transport_explicitly_bypasses_environment_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers: list[object] = []

    class FakeOpener:
        pass

    def capture_build_opener(*selected_handlers: object) -> FakeOpener:
        handlers.extend(selected_handlers)
        return FakeOpener()

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.test:8000")
    monkeypatch.setattr(live_module, "build_opener", capture_build_opener)

    _UrllibTransport()

    proxy_handlers = [
        handler for handler in handlers if isinstance(handler, ProxyHandler)
    ]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}


def test_live_client_and_adapter_repr_redact_base_url() -> None:
    base_url = RFC1918_HTTP_URLS[0]
    client = LiveOWClient(
        base_url=base_url,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=_transport(),
        allow_private_http=True,
    )
    adapter = LiveOWAdapter(
        base_url=base_url,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=_transport(),
        allow_private_http=True,
    )

    assert base_url not in repr(client)
    assert base_url not in repr(adapter)
    assert "base_url" not in repr(client)


def test_client_rejects_owner_context_mismatch_before_transport() -> None:
    transport = _transport()
    client = LiveOWClient(
        base_url=BASE_URL,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=transport,
    )

    with pytest.raises(LiveOWError) as error:
        client.get_data_sources(
            owner_context=OwnerContext(
                principal_key="principal-other-demo",
                owner_key="owner-other-demo",
                ow_user_key="00000000-0000-4000-8000-000000000002",
            )
        )

    assert error.value.code == "UPSTREAM_INVALID"
    assert transport.calls == []


def test_client_maps_timeout_without_exposing_transport_text() -> None:
    transport = FakeTransport(
        {
            "/api/v1/users/00000000-0000-4000-8000-000000000001/data-sources": TimeoutError(
                "private path"
            )
        }
    )
    client = LiveOWClient(
        base_url=BASE_URL,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=transport,
    )

    with pytest.raises(LiveOWError) as error:
        client.get_data_sources(owner_context=OWNER)

    assert error.value.code == "UPSTREAM_TIMEOUT"
    assert "private path" not in str(error.value)


def test_client_sanitizes_unknown_response_fields_and_metadata() -> None:
    response = _data_sources()
    payload = response.json()
    assert isinstance(payload, dict)
    payload["metadata"] = {"untrusted_extra": "raw"}
    assert isinstance(payload["items"], list)
    payload["items"][0]["untrusted_extra"] = "raw"
    transport = FakeTransport(
        {
            "/api/v1/users/00000000-0000-4000-8000-000000000001/data-sources": FakeResponse(
                200, payload
            )
        }
    )
    client = LiveOWClient(
        base_url=BASE_URL,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=transport,
    )

    sources = client.get_data_sources(owner_context=OWNER)

    assert "untrusted_extra" not in repr(sources)
    assert "metadata" not in repr(sources)


def test_client_sanitizes_paginated_metadata_rows_and_optional_pagination_fields() -> (
    None
):
    payload = _activity().json()
    assert isinstance(payload, dict)
    payload["private_wrapper"] = "raw"
    payload["metadata"]["private"] = "raw"
    payload["pagination"].pop("previous_cursor")
    payload["pagination"].pop("total_count")
    payload["data"][0]["private"] = "raw"
    transport = FakeTransport(
        {
            "/api/v1/users/00000000-0000-4000-8000-000000000001/summaries/activity": FakeResponse(
                200, payload
            )
        }
    )
    client = LiveOWClient(
        base_url=BASE_URL,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=transport,
    )

    rows = client.get_activity_summary(
        owner_context=OWNER,
        start_date="2024-01-02T00:00:00Z",
        end_date="2024-01-03T00:00:00Z",
    )

    assert rows[0]["steps"] == 8123
    assert "private" not in repr(rows)
    assert "private_wrapper" not in repr(rows)


def test_client_accepts_absent_optional_source_fields() -> None:
    payload = _data_sources().json()
    assert isinstance(payload, dict)
    assert isinstance(payload["items"], list)
    payload["items"][0].pop("source")
    payload["items"][0].pop("device_type")
    transport = FakeTransport(
        {
            "/api/v1/users/00000000-0000-4000-8000-000000000001/data-sources": FakeResponse(
                200, payload
            )
        }
    )
    client = LiveOWClient(
        base_url=BASE_URL,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=transport,
    )

    sources = client.get_data_sources(owner_context=OWNER)

    assert sources[0]["provider"] == "provider-live"
    assert "source" not in sources[0]
    assert "device_type" not in sources[0]

    projected = _adapter(transport).get_sources_response(
        logical_date="2024-01-02",
        timezone_name="UTC",
        owner_context=OWNER,
    )
    assert projected["data"]["items"][0]["state"] == "ready"


def test_client_accepts_summary_bounds_and_optional_metadata_envelope() -> None:
    transport = _transport()
    client = LiveOWClient(
        base_url=BASE_URL,
        api_key="ow-api-key-live-demo",
        expected_owner_context=OWNER,
        transport=transport,
    )

    with pytest.raises(LiveOWError) as error:
        client.request_json(
            owner_context=OWNER,
            relative_path="/api/v1/users/00000000-0000-4000-8000-000000000001/summaries/activity",
            params=(
                ("start_date", "2024-01-02"),
                ("end_date", "2024-01-03T00:00:00Z"),
            ),
        )

    assert error.value.code == "UPSTREAM_INVALID"
    assert transport.calls == []

    payload = _activity().json()
    assert isinstance(payload, dict)
    del payload["metadata"]
    transport.responses[
        "/api/v1/users/00000000-0000-4000-8000-000000000001/summaries/activity"
    ] = FakeResponse(200, payload)
    rows = client.get_activity_summary(
        owner_context=OWNER,
        start_date="2024-01-02T00:00:00Z",
        end_date="2024-01-03T00:00:00Z",
    )
    assert rows[0]["steps"] == 8123
    assert "metadata" not in repr(rows)

    payload = _activity().json()
    assert isinstance(payload, dict)
    assert isinstance(payload["metadata"], dict)
    payload["metadata"].update(
        {
            "resolution": "5min",
            "sample_count": 1,
            "start_time": "2024-01-02T00:00:00Z",
            "end_time": "2024-01-03T00:00:00Z",
            "untrusted_extra": "raw",
        }
    )
    transport.responses[
        "/api/v1/users/00000000-0000-4000-8000-000000000001/summaries/activity"
    ] = FakeResponse(200, payload)
    rows = client.get_activity_summary(
        owner_context=OWNER,
        start_date="2024-01-02T00:00:00Z",
        end_date="2024-01-03T00:00:00Z",
    )
    assert rows[0]["steps"] == 8123
    assert "metadata" not in repr(rows)
    assert "untrusted_extra" not in repr(rows)


def test_adapter_projects_daily_summary_without_copying_upstream_source_names() -> None:
    transport = _transport()
    adapter = _adapter(transport)

    response = adapter.get_overview_response(
        logical_date="2024-01-02",
        timezone_name="UTC",
        from_utc="2024-01-02T00:00:00Z",
        to_utc="2024-01-03T00:00:00Z",
        owner_context=OWNER,
    )
    projected = serialize_overview(
        response,
        logical_date="2024-01-02",
        timezone_name="UTC",
        from_utc="2024-01-02T00:00:00Z",
        to_utc="2024-01-03T00:00:00Z",
    )

    summary = projected["data"]["summary"]
    assert summary["steps"] == {
        "state": "value",
        "value": 8123,
        "unit": "count",
        "isDailyTotal": True,
        "sourceKey": "source-live-01",
    }
    assert summary["activeCaloriesKcal"]["state"] == "zero"
    assert summary["sleepDurationSeconds"]["value"] == 25200
    assert summary["recoveryScore"]["state"] == "null"
    assert "private source name" not in repr(projected)
    assert "ow-api-key-live-demo" not in repr(projected)


def test_adapter_preserves_source_ambiguity_in_daily_summary_and_sources() -> None:
    transport = _transport(source_count=2)
    adapter = _adapter(transport)

    overview = adapter.get_overview_response(
        logical_date="2024-01-02",
        timezone_name="UTC",
        from_utc="2024-01-02T00:00:00Z",
        to_utc="2024-01-03T00:00:00Z",
        owner_context=OWNER,
    )
    sources = adapter.get_sources_response(
        logical_date="2024-01-02",
        timezone_name="UTC",
        owner_context=OWNER,
    )

    assert any(
        warning["code"] == "SOURCE_AMBIGUOUS" for warning in overview["warnings"]
    )
    assert overview["data"]["summary"]["steps"]["state"] == "source_ambiguous"
    assert all(item["state"] == "source_ambiguous" for item in sources["data"]["items"])
    serialize_sources(sources, timezone_name="UTC")


def test_adapter_preserves_non_daily_semantics_for_zero_recovery_score() -> None:
    response = _adapter(_transport(recovery_score=0)).get_overview_response(
        logical_date="2024-01-02",
        timezone_name="UTC",
        from_utc="2024-01-02T00:00:00Z",
        to_utc="2024-01-03T00:00:00Z",
        owner_context=OWNER,
    )

    assert response["data"]["summary"]["recoveryScore"] == {
        "state": "zero",
        "value": 0,
        "unit": None,
        "isDailyTotal": False,
    }


def test_adapter_sanitizes_http_errors_to_bff_owned_error_envelope() -> None:
    transport = FakeTransport(
        {
            "/api/v1/users/00000000-0000-4000-8000-000000000001/data-sources": FakeResponse(
                500,
                {"message": "provider secret /private/path", "error": "raw"},
            )
        }
    )
    adapter = _adapter(transport)

    response = adapter.get_sources_response(
        logical_date="2024-01-02",
        timezone_name="UTC",
        owner_context=OWNER,
    )

    assert response["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert response["data"] is None
    assert "provider secret" not in repr(response)
    assert "/private/path" not in repr(response)
    validate_adapter_error_response(response)


def test_live_mode_requires_loopback_dev_access_and_server_ow_configuration() -> None:
    with pytest.raises(ValueError, match="BFF_DEV_ACCESS_ENABLED"):
        create_app(
            environment="test",
            session_mode="active",
            live_ow_enabled=True,
            owner_key="owner-live-demo",
            ow_user_key=OWNER.ow_user_key,
            ow_api_base_url=BASE_URL,
            ow_api_key="ow-api-key-live-demo",
        )

    with pytest.raises(ValueError, match="OW_API_BASE_URL"):
        create_app(
            environment="test",
            session_mode="active",
            dev_access_enabled=True,
            live_ow_enabled=True,
            owner_key="owner-live-demo",
            ow_user_key=OWNER.ow_user_key,
            ow_api_key="ow-api-key-live-demo",
        )


def test_live_mode_requires_uuid_and_accepts_bearer_token_without_api_key() -> None:
    with pytest.raises(ValueError, match="UUID"):
        create_app(
            environment="test",
            session_mode="active",
            dev_access_enabled=True,
            live_ow_enabled=True,
            owner_key="owner-live-demo",
            ow_user_key="ow-user-live-demo",
            ow_api_base_url=BASE_URL,
            ow_bearer_token="bearer-token-live-demo",
        )

    app = create_app(
        environment="test",
        session_mode="active",
        dev_access_enabled=True,
        live_ow_enabled=True,
        owner_key=OWNER.owner_key,
        ow_user_key=OWNER.ow_user_key,
        principal_key=OWNER.principal_key,
        ow_api_base_url=BASE_URL,
        ow_bearer_token="bearer-token-live-demo",
    )
    assert app.state.service.settings.ow_bearer_token == "bearer-token-live-demo"


def test_live_mode_fails_closed_without_bearer_or_api_key() -> None:
    with pytest.raises(ValueError, match="OW_BEARER_TOKEN or OW_API_KEY"):
        create_app(
            environment="test",
            session_mode="active",
            dev_access_enabled=True,
            live_ow_enabled=True,
            owner_key=OWNER.owner_key,
            ow_user_key=OWNER.ow_user_key,
            ow_api_base_url=BASE_URL,
        )


def test_live_app_reads_overview_only_from_live_adapter_and_keeps_post_bff_owned() -> (
    None
):
    transport = _transport()
    app = create_app(
        environment="test",
        session_mode="active",
        dev_access_enabled=True,
        owner_key=OWNER.owner_key,
        ow_user_key=OWNER.ow_user_key,
        principal_key=OWNER.principal_key,
        live_ow_enabled=True,
        ow_api_base_url=BASE_URL,
        ow_api_key="ow-api-key-live-demo",
        live_transport=transport,
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get(
            "/api/v1/me/verify/overview",
            params={"date": "2024-01-02", "timezone": "America/New_York"},
            headers={
                "X-BFF-Owner": "browser-owner-demo",
                "X-OW-User-Key": "browser-ow-user-demo",
            },
        )
        assert response.status_code == 200
        assert response.json()["data"]["summary"]["steps"]["value"] == 8123
        assert "/browser-ow-user-demo/" not in repr(transport.calls)
        summary_calls = [
            call["params"]
            for call in transport.calls
            if any(key == "start_date" for key, _value in call["params"])
        ]
        assert len(summary_calls) == 4
        assert all(
            params[:2]
            == (
                ("start_date", "2024-01-02T05:00:00Z"),
                ("end_date", "2024-01-03T05:00:00Z"),
            )
            for params in summary_calls
        )

        sources = client.get(
            "/api/v1/me/verify/sources",
            params={"date": "2024-01-02", "timezone": "UTC"},
            headers={
                "X-BFF-Owner": "browser-owner-demo",
                "X-OW-User-Key": "browser-ow-user-demo",
            },
        )
        assert sources.status_code == 200
        assert sources.json()["data"]["items"][0]["label"] == "Fuente conectada"
        assert "/browser-ow-user-demo/" not in repr(transport.calls)

        before_post = len(transport.calls)
        created = client.post(
            "/api/v1/me/verify/runs",
            json={"date": "2024-01-02", "timezone": "UTC", "domains": ["activity"]},
            headers={
                "Origin": "http://testserver",
                "Idempotency-Key": "live-post-demo",
            },
        )
        assert created.status_code == 202
        assert len(transport.calls) == before_post


def test_live_http_overview_projects_multi_source_ambiguity_without_502() -> None:
    transport = _transport(source_count=2)
    app = create_app(
        environment="test",
        session_mode="active",
        dev_access_enabled=True,
        owner_key=OWNER.owner_key,
        ow_user_key=OWNER.ow_user_key,
        principal_key=OWNER.principal_key,
        live_ow_enabled=True,
        ow_api_base_url=BASE_URL,
        ow_api_key="ow-api-key-live-demo",
        live_transport=transport,
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get(
            "/api/v1/me/verify/overview",
            params={"date": "2024-01-02", "timezone": "UTC"},
            headers={
                "X-BFF-Owner": "browser-owner-demo",
                "X-OW-User-Key": "browser-ow-user-demo",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["summary"]["steps"]["state"] == "source_ambiguous"
    assert {
        warning["domain"]
        for warning in payload["warnings"]
        if warning["code"] == "SOURCE_AMBIGUOUS"
    } == {"activity", "heart_rate", "sleep"}
