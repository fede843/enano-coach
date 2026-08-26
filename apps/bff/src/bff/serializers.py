from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from functools import wraps
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ValidationError

from .errors import SAFE_MESSAGES, BFFError, error_for
from .models import (
    WARNING_COPY_BY_CODE,
    WARNING_DOMAIN_RULES,
    AccessState,
    ActivityTrendData,
    CapabilityExtension,
    Coverage,
    DomainCoverage,
    DomainCoverageMap,
    Envelope,
    ErrorBody,
    Extensions,
    FixtureExtension,
    HeartRateMetric,
    Metric,
    MetricCoverage,
    OverviewData,
    OverviewSummary,
    RequestedCoverage,
    RunCounts,
    RunDetailData,
    RunListData,
    RunListItem,
    RunPage,
    RunScope,
    SessionData,
    SettingsCapabilities,
    SettingsData,
    SettingsVersions,
    SourceData,
    SourceItem,
    VerificationResult,
    VerificationRun,
    WarningModel,
)
from .ranges import trend_date_scope

_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_SAFE_SOURCE_LABELS = {
    "source-demo-a": "Fuente sintética A",
    "source-demo-b": "Fuente sintética B",
}
_SAFE_SOURCE_KEYS = frozenset(_SAFE_SOURCE_LABELS)
_LIVE_SOURCE_KEY_PATTERN = re.compile(r"^source-live-[0-9]{2}$")
_LIVE_SOURCE_LABEL = "Fuente conectada"
_OVERVIEW_METRIC_UNITS: dict[str, str | None] = {
    "steps": "count",
    "distanceMeters": "meters",
    "activeCaloriesKcal": "kcal",
    "sleepDurationSeconds": "seconds",
    "recoveryScore": None,
    "stress": None,
}
_OVERVIEW_METRIC_DOMAINS = {
    "steps": "activity",
    "distanceMeters": "activity",
    "activeCaloriesKcal": "activity",
    "sleepDurationSeconds": "sleep",
    "recoveryScore": "recovery",
    "heartRate": "activity",
}
_OVERVIEW_WARNING_DOMAINS = {
    **_OVERVIEW_METRIC_DOMAINS,
    "heartRate": "heart_rate",
}
_UNITLESS_METRICS = frozenset({"recoveryScore"})
_ALLOWED_CAPABILITIES = frozenset({"activity", "body", "heart_rate", "sleep"})
_ALLOWED_SESSION_STATES = frozenset({"active", "anonymous", "pending", "blocked"})
_ALLOWED_DOMAINS = frozenset(
    {"activity", "sleep", "recovery", "body", "workouts", "sources"}
)
_ALLOWED_WARNING_CODES = frozenset(
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
_ALLOWED_WARNING_SEVERITIES = frozenset({"info", "warning"})
_ALLOWED_WARNING_DOMAINS = frozenset(
    {"activity", "body", "heart_rate", "recovery", "sleep", "workouts"}
)
_SAFE_WARNING_VARIANTS = WARNING_COPY_BY_CODE
_SAFE_FIXTURE_CASES = frozenset(
    {
        "access_blocked_403",
        "access_pending_403",
        "auth_401",
        "auth_403",
        "cursor_context_mismatch_400",
        "cursor_expired_410",
        "idempotency_conflict_409",
        "internal_error_500",
        "invalid_cursor_400",
        "invalid_scope_422",
        "invalid_query_400",
        "overview_empty",
        "overview_mixed",
        "overview_error",
        "rate_limited_429",
        "run_not_found_404",
        "runs_first_page",
        "runs_second_page",
        "session_active",
        "session_anonymous_200",
        "settings_capabilities",
        "source_ambiguous",
        "source_ready",
        "verification_inconclusive",
        "verification_not_verifiable",
        "verification_run_create",
        "verification_run_mismatch",
        "verification_run_partial",
        "upstream_invalid_502",
        "upstream_timeout_504",
        "upstream_unavailable_503",
    }
)
_SAFE_RESULT_REASONS = frozenset({"CURSOR_EXPIRED", "NO_PUBLIC_WORKOUT_DETAIL"})
_SAFE_RESULT_METRICS = frozenset({"extended_workout_detail", "steps"})
_SAFE_RESULT_STATES = frozenset({"inconclusive", "match", "mismatch", "not_verifiable"})
_SAFE_UNITS = frozenset(
    {
        "bpm",
        "celsius",
        "cm",
        "count",
        "kcal",
        "kg",
        "m_per_s",
        "meters",
        "ms",
        "percent",
        "rpm",
        "seconds",
        "watts",
    }
)
_SAFE_STATE_VALUES = frozenset(
    {
        "empty",
        "error",
        "inconclusive",
        "not_verifiable",
        "null",
        "partial",
        "pending",
        "source_ambiguous",
        "unsupported",
        "value",
        "zero",
    }
)
_SAFE_RUN_STATES = frozenset(
    {
        "cancelled",
        "completed_with_findings",
        "failed",
        "inconclusive",
        "not_verifiable",
        "partial",
        "pending",
        "persisted",
        "skipped",
    }
)
_TERMINAL_RUN_STATES = frozenset(
    {
        "cancelled",
        "completed_with_findings",
        "failed",
        "inconclusive",
        "not_verifiable",
        "partial",
        "persisted",
        "skipped",
    }
)
_RESULT_UNIT_BY_METRIC = {"steps": "count"}
_PERSISTED_CONFLICTING_WARNINGS = frozenset(
    {"INCONCLUSIVE", "MISMATCH", "NOT_VERIFIABLE", "PARTIAL_COVERAGE"}
)
_PENDING_COUNT_FIELDS = (
    "recordsSeen",
    "recordsAccepted",
    "recordsRejected",
    "recordsDuplicated",
    "fieldsUnsupported",
)
_COVERAGE_FIELDS = frozenset(
    {"requested", "expectedDays", "availableDays", "isPartial", "byDomain"}
)
_DOMAIN_COVERAGE_FIELDS = frozenset({"expectedDays", "availableDays", "state"})
_METRIC_COVERAGE_FIELDS = frozenset(
    {"expectedDays", "availableDays", "observedFraction"}
)
_RAW_CURSOR_PATTERN = re.compile(r"^bff-cursor-demo-[a-z0-9-]+$")
_BFF_CURSOR_TOKEN_PATTERN = re.compile(r"^c_[A-Za-z0-9_-]{8,64}$")
_RAW_ENVELOPE_FIELDS = frozenset(
    {"schemaVersion", "asOf", "timezone", "data", "coverage", "warnings", "extensions"}
)
_RAW_ERROR_ENVELOPE_FIELDS = _RAW_ENVELOPE_FIELDS | {"error"}
_SAFE_ERROR_CODES = frozenset(
    {
        "ACCESS_BLOCKED",
        "ACCESS_PENDING",
        "CURSOR_CONTEXT_MISMATCH",
        "CURSOR_EXPIRED",
        "FORBIDDEN",
        "IDEMPOTENCY_CONFLICT",
        "INTERNAL_ERROR",
        "INVALID_CURSOR",
        "INVALID_QUERY",
        "INVALID_SCOPE",
        "METHOD_NOT_ALLOWED",
        "NOT_FOUND",
        "RATE_LIMITED",
        "RUN_NOT_FOUND",
        "SESSION_REQUIRED",
        "UPSTREAM_INVALID",
        "UPSTREAM_TIMEOUT",
        "UPSTREAM_UNAVAILABLE",
    }
)
_SAFE_ERROR_FIELDS = frozenset(
    {
        None,
        "Content-Length",
        "Content-Type",
        "Idempotency-Key",
        "Origin",
        "body",
        "cursor",
        "date",
        "domains",
        "from",
        "limit",
        "state",
        "timezone",
        "to",
    }
)
_SAFE_ERROR_MESSAGE_FALLBACKS = {
    "ACCESS_BLOCKED": frozenset({"El acceso a esta consulta está bloqueado."}),
    "ACCESS_PENDING": frozenset({"La cuenta todavía no tiene acceso a esta consulta."}),
    "CURSOR_CONTEXT_MISMATCH": frozenset(
        {"The cursor does not match the current list context."}
    ),
    "CURSOR_EXPIRED": frozenset({"La página solicitada expiró; reinicia el listado."}),
    "FORBIDDEN": frozenset({"The request is not allowed."}),
    "IDEMPOTENCY_CONFLICT": frozenset(
        {"La solicitud entra en conflicto con una operación existente."}
    ),
    "INTERNAL_ERROR": frozenset({"No se pudo completar la solicitud."}),
    "INVALID_CURSOR": frozenset({"El cursor no es válido para este listado."}),
    "INVALID_QUERY": frozenset({"La fecha o zona horaria no es válida."}),
    "INVALID_SCOPE": frozenset({"El alcance de la verificación no es válido."}),
    "METHOD_NOT_ALLOWED": frozenset({"This method is not allowed."}),
    "NOT_FOUND": frozenset({"The requested resource was not found."}),
    "RATE_LIMITED": frozenset({"Se alcanzó el límite de solicitudes."}),
    "RUN_NOT_FOUND": frozenset({"No se encontró la verificación solicitada."}),
    "SESSION_REQUIRED": frozenset({"La sesión es necesaria para consultar."}),
    "UPSTREAM_INVALID": frozenset({"La fuente devolvió una respuesta no válida."}),
    "UPSTREAM_TIMEOUT": frozenset(
        {
            "La fuente tardó demasiado en responder.",
            "No se pudo completar la consulta del resumen.",
        }
    ),
    "UPSTREAM_UNAVAILABLE": frozenset(
        {"La fuente no está disponible; vuelve a consultar manualmente."}
    ),
}
_REQUEST_ID_PATTERN = re.compile(r"^req-demo-[a-z0-9-]+$")


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise error_for("UPSTREAM_INVALID")
    return value


def _reject_non_finite(value: Any) -> None:
    stack: list[tuple[Any, int | None, bool]] = [(value, None, False)]
    active: set[int] = set()
    while stack:
        current, identity, exiting = stack.pop()
        if exiting:
            if identity is not None:
                active.remove(identity)
            continue
        if isinstance(current, Mapping):
            identity = id(current)
            if identity in active:
                raise error_for("UPSTREAM_INVALID")
            active.add(identity)
            stack.append((current, identity, True))
            stack.extend((item, None, False) for item in current.values())
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            identity = id(current)
            if identity in active:
                raise error_for("UPSTREAM_INVALID")
            active.add(identity)
            stack.append((current, identity, True))
            stack.extend((item, None, False) for item in current)
        elif type(current) is float and not isfinite(current):
            raise error_for("UPSTREAM_INVALID")


def _reject_unknown_fields(raw: Mapping[str, Any], allowed: frozenset[str]) -> None:
    if any(key not in allowed for key in raw):
        raise error_for("UPSTREAM_INVALID")


def _model(model_type: type[BaseModel], value: Mapping[str, Any]) -> BaseModel:
    try:
        return model_type.model_validate(dict(value))
    except ValidationError as exc:
        raise error_for("UPSTREAM_INVALID") from exc


def _dump(model: BaseModel) -> dict[str, Any]:
    value = model.model_dump(by_alias=True, exclude_unset=True)
    _reject_non_finite(value)
    return value


def _serializer_boundary(function: Any) -> Any:
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return function(*args, **kwargs)
        except BFFError:
            raise
        except Exception as exc:
            raise error_for("UPSTREAM_INVALID") from exc

    return wrapped


def _as_of_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _timestamp(value: Any, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not _TIMESTAMP_PATTERN.fullmatch(value):
        raise error_for("UPSTREAM_INVALID")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise error_for("UPSTREAM_INVALID") from exc
    return value


def _logical_date(value: Any) -> str:
    if not isinstance(value, str):
        raise error_for("UPSTREAM_INVALID")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise error_for("UPSTREAM_INVALID") from exc
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise error_for("UPSTREAM_INVALID")
    return value


def _safe_timezone(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise error_for("UPSTREAM_INVALID")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise error_for("UPSTREAM_INVALID") from exc
    return value


def _safe_source_key(value: Any) -> str:
    if not isinstance(value, str) or (
        value not in _SAFE_SOURCE_KEYS and not _LIVE_SOURCE_KEY_PATTERN.fullmatch(value)
    ):
        raise error_for("UPSTREAM_INVALID")
    return value


def _safe_run_key(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"verify-demo-\d{2,8}", value):
        raise error_for("UPSTREAM_INVALID")
    return value


def _safe_cursor(value: Any, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not _BFF_CURSOR_TOKEN_PATTERN.fullmatch(value):
        raise error_for("UPSTREAM_INVALID")
    return value


def _safe_int(value: Any, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if type(value) is not int or value < 0:
        raise error_for("UPSTREAM_INVALID")
    return value


def _safe_number(value: Any, *, optional: bool = False) -> int | float | None:
    if value is None and optional:
        return None
    if type(value) not in (int, float) or isinstance(value, bool):
        raise error_for("UPSTREAM_INVALID")
    if type(value) is float and not isfinite(value):
        raise error_for("UPSTREAM_INVALID")
    return value


def _validate_metric_value(value: int | float, unit: str | None) -> None:
    if unit == "count":
        if type(value) is not int or value < 0:
            raise error_for("UPSTREAM_INVALID")
        return
    if unit == "percent" and not 0 <= value <= 100:
        raise error_for("UPSTREAM_INVALID")
    if unit not in {None, "celsius"} and value < 0:
        raise error_for("UPSTREAM_INVALID")


def _validate_run_counts(value: RunCounts) -> None:
    counts = _dump(value)
    seen = counts["recordsSeen"]
    if seen is None:
        if any(
            count is not None for key, count in counts.items() if key != "recordsSeen"
        ):
            raise error_for("UPSTREAM_INVALID")
        return
    for key in (
        "recordsAccepted",
        "recordsRejected",
        "recordsDuplicated",
        "fieldsUnsupported",
    ):
        count = counts[key]
        if count is not None and count > seen:
            raise error_for("UPSTREAM_INVALID")
    breakdown = [
        counts["recordsAccepted"],
        counts["recordsRejected"],
        counts["recordsDuplicated"],
    ]
    if all(count is not None for count in breakdown) and sum(breakdown) > seen:
        raise error_for("UPSTREAM_INVALID")


def _validate_pending_run_fields(raw: Mapping[str, Any]) -> None:
    if raw["startedAt"] is not None or raw["finishedAt"] is not None:
        raise error_for("UPSTREAM_INVALID")
    counts = _mapping(raw["counts"])
    if any(counts[field] is not None for field in _PENDING_COUNT_FIELDS):
        raise error_for("UPSTREAM_INVALID")
    results = raw.get("results")
    if results not in (None, []):
        raise error_for("UPSTREAM_INVALID")


def _allowed_string(value: Any, allowed: frozenset[str]) -> str | None:
    if not isinstance(value, str) or value not in allowed:
        return None
    return value


def _safe_text(
    value: Any,
    *,
    allowed: frozenset[str],
    fallback: str | None = None,
) -> str:
    """Return only BFF-owned copy; never relay provider-controlled prose."""

    if isinstance(value, str) and value in allowed:
        return value
    if fallback is not None and fallback in allowed:
        return fallback
    raise error_for("UPSTREAM_INVALID")


@_serializer_boundary
def validate_adapter_error_response(value: Any) -> None:
    """Validate an adapter error envelope without forwarding its copy."""

    raw = _mapping(value)
    _reject_non_finite(raw)
    _reject_unknown_fields(raw, _RAW_ERROR_ENVELOPE_FIELDS)
    if set(raw) != _RAW_ERROR_ENVELOPE_FIELDS or raw.get("data") is not None:
        raise error_for("UPSTREAM_INVALID")
    if raw.get("schemaVersion") != "1":
        raise error_for("UPSTREAM_INVALID")
    _timestamp(raw.get("asOf"))
    _safe_timezone(raw.get("timezone"))
    _project_coverage(raw.get("coverage"))
    _project_warnings(raw.get("warnings"))
    _project_extensions(raw.get("extensions"))
    if raw.get("coverage") != {} or raw.get("warnings") != []:
        raise error_for("UPSTREAM_INVALID")
    error = _mapping(raw.get("error"))
    _reject_unknown_fields(
        error, frozenset({"code", "message", "requestId", "retryable", "field"})
    )
    if set(error) != {"code", "message", "requestId", "retryable", "field"}:
        raise error_for("UPSTREAM_INVALID")
    code = error.get("code")
    if not isinstance(code, str) or code not in _SAFE_ERROR_CODES:
        raise error_for("UPSTREAM_INVALID")
    _safe_text(
        error.get("message"),
        allowed=_SAFE_ERROR_MESSAGE_FALLBACKS.get(code, frozenset()),
    )
    request_id = error.get("requestId")
    if not isinstance(request_id, str) or not _REQUEST_ID_PATTERN.fullmatch(request_id):
        raise error_for("UPSTREAM_INVALID")
    if type(error.get("retryable")) is not bool:
        raise error_for("UPSTREAM_INVALID")
    if error.get("field") not in _SAFE_ERROR_FIELDS:
        raise error_for("UPSTREAM_INVALID")


def _validate_error_model(error: ErrorBody) -> None:
    code = error.code
    if code not in SAFE_MESSAGES:
        raise error_for("UPSTREAM_INVALID")
    if error.message != SAFE_MESSAGES[code]:
        raise error_for("UPSTREAM_INVALID")
    if not _REQUEST_ID_PATTERN.fullmatch(error.requestId):
        raise error_for("UPSTREAM_INVALID")
    if error.field not in _SAFE_ERROR_FIELDS:
        raise error_for("UPSTREAM_INVALID")


def _project_warning(value: Any) -> WarningModel | None:
    raw = _mapping(value)
    _reject_unknown_fields(raw, frozenset({"code", "severity", "message", "domain"}))
    code = _allowed_string(raw.get("code"), _ALLOWED_WARNING_CODES)
    if code is None:
        raise error_for("UPSTREAM_INVALID")
    severity = _allowed_string(raw.get("severity"), _ALLOWED_WARNING_SEVERITIES)
    if severity is None:
        raise error_for("UPSTREAM_INVALID")
    message = _safe_text(raw.get("message"), allowed=_SAFE_WARNING_VARIANTS[code])
    values: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    domain = raw.get("domain")
    if domain is not None:
        domain = _allowed_string(domain, _ALLOWED_WARNING_DOMAINS)
        if domain is None:
            raise error_for("UPSTREAM_INVALID")
        allowed_domains = WARNING_DOMAIN_RULES[code]
        if allowed_domains is not None and domain not in allowed_domains:
            raise error_for("UPSTREAM_INVALID")
        values["domain"] = domain
    return _model(WarningModel, values)  # type: ignore[return-value]


def _project_warnings(value: Any) -> list[WarningModel]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise error_for("UPSTREAM_INVALID")
    if len(value) > 100:
        raise error_for("UPSTREAM_INVALID")
    result: list[WarningModel] = []
    for item in value:
        warning = _project_warning(item)
        if warning is None:
            raise error_for("UPSTREAM_INVALID")
        result.append(warning)
    return result


def _validate_warning_domains(
    warnings: Sequence[WarningModel],
    expected_domains: Mapping[str, frozenset[str]],
) -> None:
    for code, domains in expected_domains.items():
        matching = [warning for warning in warnings if warning.code == code]
        observed_domains = {warning.domain for warning in matching}
        if (
            not matching
            or any(warning.domain not in domains for warning in matching)
            or not domains.issubset(observed_domains)
        ):
            raise error_for("UPSTREAM_INVALID")


def _project_extensions(value: Any) -> Extensions:
    raw = _mapping(value) if value is not None else {}
    _reject_unknown_fields(raw, frozenset({"fixture", "capabilities"}))
    values: dict[str, Any] = {}
    fixture = raw.get("fixture")
    if fixture is not None:
        fixture_raw = _mapping(fixture)
        _reject_unknown_fields(fixture_raw, frozenset({"synthetic", "case"}))
        case = fixture_raw.get("case")
        if (
            fixture_raw.get("synthetic") is not True
            or not isinstance(case, str)
            or case not in _SAFE_FIXTURE_CASES
        ):
            raise error_for("UPSTREAM_INVALID")
        values["fixture"] = _dump(
            _model(FixtureExtension, {"synthetic": True, "case": case})
        )
    capabilities = raw.get("capabilities")
    if capabilities is not None:
        capabilities_raw = _mapping(capabilities)
        _reject_unknown_fields(
            capabilities_raw,
            frozenset({"gps", "workoutDetails", "segments", "hrZones"}),
        )
        capability_values: dict[str, str] = {}
        for key in ("gps", "workoutDetails", "segments", "hrZones"):
            if key in capabilities_raw:
                candidate = capabilities_raw[key]
                if not isinstance(candidate, str) or candidate not in {
                    "aggregate_only",
                    "not_verifiable",
                }:
                    raise error_for("UPSTREAM_INVALID")
                capability_values[key] = candidate
        values["capabilities"] = _dump(_model(CapabilityExtension, capability_values))
    return _model(Extensions, values)  # type: ignore[return-value]


def _project_domain_coverage(
    value: Any, *, daily_overview: bool = False
) -> DomainCoverage:
    raw = _mapping(value)
    _reject_unknown_fields(raw, _DOMAIN_COVERAGE_FIELDS)
    fields = {
        key: raw[key]
        for key in ("expectedDays", "availableDays", "state")
        if key in raw
    }
    for key in ("expectedDays", "availableDays"):
        if key in fields:
            _safe_int(fields[key], optional=True)
    if (
        _allowed_string(
            fields.get("state"),
            frozenset(
                {
                    "complete",
                    "empty",
                    "inconclusive",
                    "not_verifiable",
                    "partial",
                    "relative_to_now",
                    "unsupported",
                }
            ),
        )
        is None
    ):
        raise error_for("UPSTREAM_INVALID")
    expected_days = fields.get("expectedDays")
    available_days = fields.get("availableDays")
    if (expected_days is None) != (available_days is None):
        raise error_for("UPSTREAM_INVALID")
    if (
        expected_days is not None
        and available_days is not None
        and available_days > expected_days
    ):
        raise error_for("UPSTREAM_INVALID")
    state = fields["state"]
    if state == "relative_to_now" and (
        expected_days is not None or available_days is not None
    ):
        raise error_for("UPSTREAM_INVALID")
    if state == "complete" and (
        expected_days is None
        or available_days is None
        or available_days != expected_days
    ):
        raise error_for("UPSTREAM_INVALID")
    if state == "empty" and (
        expected_days is None or available_days is None or available_days != 0
    ):
        raise error_for("UPSTREAM_INVALID")
    if state == "partial" and (
        expected_days is None
        or available_days is None
        or available_days == 0
        or available_days >= expected_days
    ):
        raise error_for("UPSTREAM_INVALID")
    if state == "complete" and (
        expected_days is None
        or available_days is None
        or expected_days == 0
        or available_days != expected_days
    ):
        raise error_for("UPSTREAM_INVALID")
    if daily_overview and (
        expected_days is not None
        and (
            expected_days != 1 or available_days is None or available_days not in {0, 1}
        )
    ):
        raise error_for("UPSTREAM_INVALID")
    return _model(DomainCoverage, fields)  # type: ignore[return-value]


def _project_coverage(
    value: Any,
    *,
    requested: Mapping[str, Any] | None = None,
    daily_overview: bool = False,
    replace_requested_context: bool = False,
) -> Coverage:
    raw = _mapping(value) if value is not None else {}
    _reject_unknown_fields(raw, _COVERAGE_FIELDS)
    values: dict[str, Any] = {}
    raw_requested = raw.get("requested")
    if raw_requested is not None and not isinstance(raw_requested, Mapping):
        raise error_for("UPSTREAM_INVALID")
    if raw_requested is not None:
        _reject_unknown_fields(
            raw_requested, frozenset({"logicalDate", "from", "to", "timezone"})
        )
        _logical_date(raw_requested.get("logicalDate"))
        _timestamp(raw_requested.get("from"))
        _timestamp(raw_requested.get("to"))
        _safe_timezone(raw_requested.get("timezone"))
        if datetime.fromisoformat(
            raw_requested["from"].replace("Z", "+00:00")
        ) >= datetime.fromisoformat(raw_requested["to"].replace("Z", "+00:00")):
            raise error_for("UPSTREAM_INVALID")
    if requested is not None:
        if raw_requested is None and daily_overview:
            raise error_for("UPSTREAM_INVALID")
        if raw_requested is not None:
            expected_requested = {
                "logicalDate": _logical_date(requested["logicalDate"]),
                "from": _timestamp(requested["from"]),
                "to": _timestamp(requested["to"]),
                "timezone": _safe_timezone(requested["timezone"]),
            }
            if (
                not replace_requested_context
                and {
                    key: raw_requested[key]
                    for key in ("logicalDate", "from", "to", "timezone")
                }
                != expected_requested
            ):
                raise error_for("UPSTREAM_INVALID")
    requested_value = requested or raw_requested
    if requested_value is not None:
        requested_raw = _mapping(requested_value)
        _reject_unknown_fields(
            requested_raw, frozenset({"logicalDate", "from", "to", "timezone"})
        )
        requested_fields = {
            "logicalDate": requested_raw.get("logicalDate"),
            "from": requested_raw.get("from"),
            "to": requested_raw.get("to"),
            "timezone": requested_raw.get("timezone"),
        }
        requested_fields["logicalDate"] = _logical_date(requested_fields["logicalDate"])
        requested_fields["from"] = _timestamp(requested_fields["from"])
        requested_fields["to"] = _timestamp(requested_fields["to"])
        requested_fields["timezone"] = _safe_timezone(requested_fields["timezone"])
        values["requested"] = _dump(_model(RequestedCoverage, requested_fields))
    for key in ("expectedDays", "availableDays"):
        if key in raw:
            values[key] = _safe_int(raw[key], optional=True)
    expected_days = values.get("expectedDays")
    available_days = values.get("availableDays")
    if (expected_days is None) != (available_days is None):
        raise error_for("UPSTREAM_INVALID")
    if (
        expected_days is not None
        and available_days is not None
        and available_days > expected_days
    ):
        raise error_for("UPSTREAM_INVALID")
    if "isPartial" in raw:
        if type(raw["isPartial"]) is not bool:
            raise error_for("UPSTREAM_INVALID")
        values["isPartial"] = raw["isPartial"]
        if raw["isPartial"] is False and (
            expected_days is not None
            and available_days is not None
            and available_days not in {0, expected_days}
        ):
            raise error_for("UPSTREAM_INVALID")
    if raw.get("isPartial") is True and (
        expected_days is None
        or available_days is None
        or expected_days == 0
        or available_days == 0
    ):
        raise error_for("UPSTREAM_INVALID")
    if daily_overview and (
        "expectedDays" not in raw
        or "availableDays" not in raw
        or "isPartial" not in raw
        or values.get("expectedDays") != 1
        or values.get("availableDays") not in {0, 1}
        or type(values.get("isPartial")) is not bool
    ):
        raise error_for("UPSTREAM_INVALID")
    by_domain = raw.get("byDomain")
    if by_domain is not None:
        if not isinstance(by_domain, Mapping):
            raise error_for("UPSTREAM_INVALID")
        _reject_unknown_fields(
            by_domain,
            frozenset({"activity", "body", "recovery", "sleep", "workouts"}),
        )
        projected_domains: dict[str, Any] = {}
        for domain in (
            "activity",
            "body",
            "recovery",
            "sleep",
            "workouts",
        ):
            if domain in by_domain:
                projected_domains[domain] = _dump(
                    _project_domain_coverage(
                        by_domain[domain], daily_overview=daily_overview
                    )
                )
        values["byDomain"] = _dump(_model(DomainCoverageMap, projected_domains))
    return _model(Coverage, values)  # type: ignore[return-value]


def _project_metric_coverage(
    value: Any, *, daily_overview: bool = False
) -> MetricCoverage:
    raw = _mapping(value)
    _reject_unknown_fields(raw, _METRIC_COVERAGE_FIELDS)
    values = {
        "expectedDays": _safe_int(raw.get("expectedDays")),
        "availableDays": _safe_int(raw.get("availableDays")),
        "observedFraction": _safe_number(raw.get("observedFraction")),
    }
    expected_days = values["expectedDays"]
    available_days = values["availableDays"]
    fraction = values["observedFraction"]
    if expected_days <= 0 or available_days > expected_days:
        raise error_for("UPSTREAM_INVALID")
    if daily_overview and (expected_days != 1 or available_days not in {0, 1}):
        raise error_for("UPSTREAM_INVALID")
    if not 0 <= fraction <= 1:
        raise error_for("UPSTREAM_INVALID")
    if fraction == 0 and available_days != 0:
        raise error_for("UPSTREAM_INVALID")
    if fraction == 1 and available_days != expected_days:
        raise error_for("UPSTREAM_INVALID")
    if 0 < fraction < 1 and available_days == 0:
        raise error_for("UPSTREAM_INVALID")
    return _model(MetricCoverage, values)  # type: ignore[return-value]


def _project_metric(
    value: Any,
    *,
    metric_name: str | None = None,
    daily_overview: bool = False,
) -> Metric:
    raw = _mapping(value)
    _reject_unknown_fields(
        raw,
        frozenset({"state", "value", "unit", "isDailyTotal", "sourceKey", "coverage"}),
    )
    values: dict[str, Any] = {}
    for key in ("state", "value", "unit", "isDailyTotal", "sourceKey", "coverage"):
        if key in raw:
            values[key] = raw[key]
    if _allowed_string(values.get("state"), _SAFE_STATE_VALUES) is None:
        raise error_for("UPSTREAM_INVALID")
    state = values["state"]
    values["value"] = _safe_number(values.get("value"), optional=True)
    unit = values.get("unit")
    if unit is not None and _allowed_string(unit, _SAFE_UNITS) is None:
        raise error_for("UPSTREAM_INVALID")
    if (
        metric_name in _OVERVIEW_METRIC_UNITS
        and not (
            unit is None
            and state
            in {
                "empty",
                "error",
                "inconclusive",
                "pending",
                "unsupported",
                "not_verifiable",
                "null",
            }
        )
        and unit != _OVERVIEW_METRIC_UNITS[metric_name]
    ):
        raise error_for("UPSTREAM_INVALID")
    if metric_name in _UNITLESS_METRICS and unit is not None:
        raise error_for("UPSTREAM_INVALID")
    if type(values.get("isDailyTotal")) not in (bool, type(None)):
        raise error_for("UPSTREAM_INVALID")
    metric_value = values["value"]
    if state in {
        "empty",
        "error",
        "inconclusive",
        "pending",
        "unsupported",
        "not_verifiable",
        "null",
    } and (metric_value is not None or unit is not None):
        raise error_for("UPSTREAM_INVALID")
    if state in {"value", "partial", "source_ambiguous"} and (
        metric_value is None
        or metric_value == 0
        or (unit is None and metric_name not in _UNITLESS_METRICS)
    ):
        raise error_for("UPSTREAM_INVALID")
    if metric_value is not None:
        _validate_metric_value(metric_value, unit)
    if (
        metric_name == "recoveryScore"
        and metric_value is not None
        and not (type(metric_value) is int and 0 <= metric_value <= 100)
    ):
        raise error_for("UPSTREAM_INVALID")
    if metric_name == "stress" and state not in {
        "unsupported",
        "not_verifiable",
        "null",
    }:
        raise error_for("UPSTREAM_INVALID")
    if state == "zero" and (
        metric_value != 0
        or (metric_name not in _UNITLESS_METRICS and values["isDailyTotal"] is not True)
    ):
        raise error_for("UPSTREAM_INVALID")
    source_key = values.get("sourceKey")
    if source_key is not None:
        values["sourceKey"] = _safe_source_key(source_key)
    if "coverage" in values:
        values["coverage"] = _dump(
            _project_metric_coverage(values["coverage"], daily_overview=daily_overview)
        )
    if state == "partial" and "coverage" not in values:
        raise error_for("UPSTREAM_INVALID")
    if state == "partial" and not (0 < values["coverage"]["observedFraction"] < 1):
        raise error_for("UPSTREAM_INVALID")
    if "coverage" in values:
        fraction = values["coverage"]["observedFraction"]
        if state in {"value", "zero", "source_ambiguous"} and fraction != 1:
            raise error_for("UPSTREAM_INVALID")
        if state in {"empty", "null"} and fraction != 0:
            raise error_for("UPSTREAM_INVALID")
        if (
            state
            not in {
                "partial",
                "value",
                "zero",
                "source_ambiguous",
                "empty",
            }
            and 0 < fraction < 1
        ):
            raise error_for("UPSTREAM_INVALID")
    return _model(Metric, values)  # type: ignore[return-value]


def _project_heart_rate(value: Any) -> HeartRateMetric:
    raw = _mapping(value)
    _reject_unknown_fields(raw, frozenset({"state", "value", "unit", "isDailyTotal"}))
    values = {
        key: raw[key]
        for key in ("state", "value", "unit", "isDailyTotal")
        if key in raw
    }
    if _allowed_string(values.get("state"), _SAFE_STATE_VALUES) is None:
        raise error_for("UPSTREAM_INVALID")
    values["value"] = _safe_number(values.get("value"), optional=True)
    state = values["state"]
    if state in {
        "empty",
        "error",
        "inconclusive",
        "pending",
        "unsupported",
        "not_verifiable",
        "null",
    }:
        if values.get("unit") is not None:
            raise error_for("UPSTREAM_INVALID")
    elif values.get("unit") != "bpm":
        raise error_for("UPSTREAM_INVALID")
    if type(values.get("isDailyTotal")) not in (bool, type(None)):
        raise error_for("UPSTREAM_INVALID")
    metric_value = values["value"]
    if (
        state
        in {
            "empty",
            "error",
            "inconclusive",
            "pending",
            "unsupported",
            "not_verifiable",
            "null",
        }
        and metric_value is not None
    ):
        raise error_for("UPSTREAM_INVALID")
    if state in {"value", "source_ambiguous"} and (
        metric_value is None or metric_value == 0
    ):
        raise error_for("UPSTREAM_INVALID")
    if state == "zero" and (metric_value != 0 or values["isDailyTotal"] is not True):
        raise error_for("UPSTREAM_INVALID")
    if state == "partial":
        raise error_for("UPSTREAM_INVALID")
    if metric_value is not None and metric_value < 0:
        raise error_for("UPSTREAM_INVALID")
    return _model(HeartRateMetric, values)  # type: ignore[return-value]


def _project_overview_summary(
    value: Any, *, daily_overview: bool = False
) -> OverviewSummary:
    raw = _mapping(value)
    _reject_unknown_fields(
        raw,
        frozenset(
            {
                "steps",
                "distanceMeters",
                "activeCaloriesKcal",
                "sleepDurationSeconds",
                "recoveryScore",
                "stress",
                "heartRate",
            }
        ),
    )
    values: dict[str, Any] = {}
    for metric_name in (
        "steps",
        "distanceMeters",
        "activeCaloriesKcal",
        "sleepDurationSeconds",
        "recoveryScore",
        "stress",
        "heartRate",
    ):
        if metric_name in raw:
            values[metric_name] = _dump(
                _project_heart_rate(raw[metric_name])
                if metric_name == "heartRate"
                else _project_metric(
                    raw[metric_name],
                    metric_name=metric_name,
                    daily_overview=daily_overview,
                )
            )
    return _model(OverviewSummary, values)  # type: ignore[return-value]


def _project_source_item(value: Any) -> SourceItem:
    raw = _mapping(value)
    _reject_unknown_fields(
        raw,
        frozenset({"sourceKey", "label", "state", "capabilities", "lastObservedAt"}),
    )
    source_key = _safe_source_key(raw.get("sourceKey"))
    label = _safe_text(
        _SAFE_SOURCE_LABELS.get(source_key, _LIVE_SOURCE_LABEL),
        allowed=frozenset((*_SAFE_SOURCE_LABELS.values(), _LIVE_SOURCE_LABEL)),
    )
    state = raw.get("state")
    if _allowed_string(state, frozenset({"ready", "source_ambiguous"})) is None:
        raise error_for("UPSTREAM_INVALID")
    capabilities_raw = raw.get("capabilities")
    if not isinstance(capabilities_raw, Sequence) or isinstance(
        capabilities_raw, (str, bytes)
    ):
        raise error_for("UPSTREAM_INVALID")
    capabilities = [
        _allowed_string(capability, _ALLOWED_CAPABILITIES)
        for capability in capabilities_raw
    ]
    values: dict[str, Any] = {
        "sourceKey": source_key,
        "label": label,
        "state": state,
        "capabilities": capabilities,
    }
    if "lastObservedAt" in raw:
        values["lastObservedAt"] = _timestamp(raw["lastObservedAt"], optional=True)
    return _model(SourceItem, values)  # type: ignore[return-value]


def _project_source_items(value: Any) -> list[SourceItem]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise error_for("UPSTREAM_INVALID")
    if len(value) > 100:
        raise error_for("UPSTREAM_INVALID")
    return [_project_source_item(item) for item in value]


def _project_counts(value: Any) -> RunCounts:
    raw = _mapping(value)
    required_fields = frozenset(
        {
            "recordsSeen",
            "recordsAccepted",
            "recordsRejected",
            "recordsDuplicated",
            "fieldsUnsupported",
        }
    )
    _reject_unknown_fields(raw, required_fields)
    if set(raw) != required_fields:
        raise error_for("UPSTREAM_INVALID")
    values = {
        key: _safe_int(raw.get(key), optional=True)
        for key in (
            "recordsSeen",
            "recordsAccepted",
            "recordsRejected",
            "recordsDuplicated",
            "fieldsUnsupported",
        )
    }
    result = _model(RunCounts, values)
    _validate_run_counts(result)  # type: ignore[arg-type]
    return result  # type: ignore[return-value]


def _project_result(value: Any) -> VerificationResult:
    raw = _mapping(value)
    _reject_unknown_fields(
        raw,
        frozenset(
            {
                "metric",
                "state",
                "reasonCode",
                "expected",
                "observed",
                "unit",
                "expectedIsDailyTotal",
                "observedIsDailyTotal",
            }
        ),
    )
    metric = raw.get("metric")
    state = raw.get("state")
    if (
        _allowed_string(metric, _SAFE_RESULT_METRICS) is None
        or _allowed_string(state, _SAFE_RESULT_STATES) is None
    ):
        raise error_for("UPSTREAM_INVALID")
    values: dict[str, Any] = {"metric": metric, "state": state}
    if state == "mismatch":
        if set(raw) != {
            "metric",
            "state",
            "expected",
            "observed",
            "unit",
            "expectedIsDailyTotal",
            "observedIsDailyTotal",
        }:
            raise error_for("UPSTREAM_INVALID")
        for key in (
            "expected",
            "observed",
            "unit",
            "expectedIsDailyTotal",
            "observedIsDailyTotal",
        ):
            if key in raw:
                values[key] = raw[key]
        values["expected"] = _safe_number(values.get("expected"))
        values["observed"] = _safe_number(values.get("observed"))
        if values.get("unit") not in _SAFE_UNITS:
            raise error_for("UPSTREAM_INVALID")
        if metric not in _RESULT_UNIT_BY_METRIC:
            raise error_for("UPSTREAM_INVALID")
        if values["unit"] != _RESULT_UNIT_BY_METRIC[metric]:
            raise error_for("UPSTREAM_INVALID")
        _validate_metric_value(values["expected"], values["unit"])
        _validate_metric_value(values["observed"], values["unit"])
        if type(values.get("expectedIsDailyTotal")) is not bool:
            raise error_for("UPSTREAM_INVALID")
        if type(values.get("observedIsDailyTotal")) is not bool:
            raise error_for("UPSTREAM_INVALID")
        if values["expected"] == values["observed"]:
            raise error_for("UPSTREAM_INVALID")
        if values["expectedIsDailyTotal"] != values["observedIsDailyTotal"]:
            raise error_for("UPSTREAM_INVALID")
    elif state == "match":
        if set(raw) != {"metric", "state"}:
            raise error_for("UPSTREAM_INVALID")
    else:
        if set(raw) != {"metric", "state", "reasonCode"}:
            raise error_for("UPSTREAM_INVALID")
        reason = raw.get("reasonCode")
        if _allowed_string(reason, _SAFE_RESULT_REASONS) is None:
            raise error_for("UPSTREAM_INVALID")
        values["reasonCode"] = reason
    return _model(VerificationResult, values)  # type: ignore[return-value]


def _project_run_list_item(record: Any) -> RunListItem:
    try:
        state = record.state
        run_key = record.run_key
        requested_at = record.requested_at
        started_at = record.started_at
        finished_at = record.finished_at
        counts = record.counts
        results = record.results
    except Exception as exc:
        raise error_for("UPSTREAM_INVALID") from exc
    if state not in _SAFE_RUN_STATES:
        raise error_for("UPSTREAM_INVALID")
    values = {
        "runKey": _safe_run_key(run_key),
        "state": state,
        "requestedAt": _record_timestamp(requested_at),
        "startedAt": _record_timestamp(started_at),
        "finishedAt": _record_timestamp(finished_at),
        "counts": _dump(_project_counts(counts)),
    }
    if values["requestedAt"] is None:
        raise error_for("UPSTREAM_INVALID")
    if state == "pending" and results not in (None, []):
        raise error_for("UPSTREAM_INVALID")
    _validate_raw_run_item(values)
    return _model(RunListItem, values)  # type: ignore[return-value]


def _validate_raw_run_item(value: Any) -> None:
    raw = _mapping(value)
    _reject_unknown_fields(
        raw,
        frozenset(
            {"runKey", "state", "requestedAt", "startedAt", "finishedAt", "counts"}
        ),
    )
    required = {"runKey", "state", "requestedAt", "startedAt", "finishedAt", "counts"}
    if set(raw) != required:
        raise error_for("UPSTREAM_INVALID")
    state = _allowed_string(raw["state"], _SAFE_RUN_STATES)
    if state is None:
        raise error_for("UPSTREAM_INVALID")
    _safe_run_key(raw["runKey"])
    _timestamp(raw["requestedAt"])
    _timestamp(raw["startedAt"], optional=True)
    _timestamp(raw["finishedAt"], optional=True)
    counts = _project_counts(raw["counts"])
    _validate_run_counts(counts)
    if state == "pending":
        _validate_pending_run_fields(raw)
    if state in _TERMINAL_RUN_STATES:
        _validate_terminal_timestamps(raw)


def _validate_raw_run_page(value: Any) -> None:
    raw = _mapping(value)
    _reject_unknown_fields(raw, frozenset({"nextCursor", "hasNext", "totalCount"}))
    if set(raw) != {"nextCursor", "hasNext", "totalCount"}:
        raise error_for("UPSTREAM_INVALID")
    cursor = raw["nextCursor"]
    if cursor is not None and (
        not isinstance(cursor, str) or not _RAW_CURSOR_PATTERN.fullmatch(cursor)
    ):
        raise error_for("UPSTREAM_INVALID")
    if type(raw["hasNext"]) is not bool:
        raise error_for("UPSTREAM_INVALID")
    if raw["hasNext"] != (cursor is not None):
        raise error_for("UPSTREAM_INVALID")
    _safe_int(raw["totalCount"], optional=True)


def _validate_raw_scope(value: Any) -> None:
    raw = _mapping(value)
    _reject_unknown_fields(raw, frozenset({"date", "timezone", "domains"}))
    if set(raw) != {"date", "timezone", "domains"}:
        raise error_for("UPSTREAM_INVALID")
    _logical_date(raw["date"])
    _safe_timezone(raw["timezone"])
    domains = raw["domains"]
    if (
        not isinstance(domains, Sequence)
        or isinstance(domains, (str, bytes))
        or not domains
        or len(domains) > 6
        or any(_allowed_string(domain, _ALLOWED_DOMAINS) is None for domain in domains)
    ):
        raise error_for("UPSTREAM_INVALID")


def _validate_terminal_timestamps(raw: Mapping[str, Any]) -> None:
    started_at = raw.get("startedAt")
    finished_at = raw.get("finishedAt")
    if started_at is None or finished_at is None:
        raise error_for("UPSTREAM_INVALID")
    requested = datetime.fromisoformat(raw["requestedAt"].replace("Z", "+00:00"))
    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    if requested > started or started > finished:
        raise error_for("UPSTREAM_INVALID")


def _validate_run_state_invariants(
    raw: Mapping[str, Any],
    *,
    warnings: Sequence[WarningModel],
    results: Sequence[VerificationResult],
    results_provided: bool,
) -> None:
    state = raw["state"]
    warning_codes = {warning.code for warning in warnings}
    result_states = {result.state for result in results}

    if state == "pending":
        _validate_pending_run_fields(raw)
        if results_provided and results:
            raise error_for("UPSTREAM_INVALID")
        return

    if state == "persisted":
        _validate_terminal_timestamps(raw)
        if warning_codes & _PERSISTED_CONFLICTING_WARNINGS:
            raise error_for("UPSTREAM_INVALID")
        if any(result_state != "match" for result_state in result_states):
            raise error_for("UPSTREAM_INVALID")
        return

    if state == "partial":
        _validate_terminal_timestamps(raw)
        if "PARTIAL_COVERAGE" not in warning_codes or result_states - {"match"}:
            raise error_for("UPSTREAM_INVALID")
        return

    if state == "completed_with_findings":
        _validate_terminal_timestamps(raw)
        if (
            "mismatch" not in result_states
            or result_states - {"match", "mismatch"}
            or "MISMATCH" not in warning_codes
        ):
            raise error_for("UPSTREAM_INVALID")
        return

    if state == "not_verifiable":
        if (
            not results_provided
            or not results
            or result_states != {"not_verifiable"}
            or "NOT_VERIFIABLE" not in warning_codes
        ):
            raise error_for("UPSTREAM_INVALID")
        _validate_terminal_timestamps(raw)
        return

    if state == "inconclusive":
        if (
            not results_provided
            or not results
            or result_states != {"inconclusive"}
            or "INCONCLUSIVE" not in warning_codes
        ):
            raise error_for("UPSTREAM_INVALID")
        _validate_terminal_timestamps(raw)
        return

    if state in {"failed", "cancelled", "skipped"}:
        _validate_terminal_timestamps(raw)


_RESULT_WARNING_DOMAINS = {
    "steps": frozenset({"activity"}),
    "extended_workout_detail": frozenset({"workouts"}),
}


def _run_warning_domains(
    raw: Mapping[str, Any],
    *,
    warnings: Sequence[WarningModel],
    results: Sequence[VerificationResult],
) -> dict[str, frozenset[str]]:
    scope = _mapping(raw["scope"])
    scope_domains = frozenset(
        domain for domain in scope["domains"] if domain in _ALLOWED_WARNING_DOMAINS
    )
    expected: dict[str, frozenset[str]] = {}
    if raw["state"] == "partial":
        expected["PARTIAL_COVERAGE"] = scope_domains

    result_domains = frozenset(
        domain
        for result in results
        for domain in _RESULT_WARNING_DOMAINS.get(result.metric, ())
    )
    for code in ("MISMATCH", "NOT_VERIFIABLE", "INCONCLUSIVE"):
        if any(warning.code == code for warning in warnings):
            expected[code] = result_domains or scope_domains
    if any(warning.code == "BODY_RELATIVE_TO_NOW" for warning in warnings):
        expected["BODY_RELATIVE_TO_NOW"] = frozenset({"body"})
    if any(warning.code == "SOURCE_AMBIGUOUS" for warning in warnings):
        expected["SOURCE_AMBIGUOUS"] = scope_domains
    return expected


def _validate_run_warning_semantics(
    raw: Mapping[str, Any],
    *,
    warnings: Sequence[WarningModel],
    results: Sequence[VerificationResult],
) -> None:
    expected = _run_warning_domains(raw, warnings=warnings, results=results)
    for code, domains in expected.items():
        matching = [warning for warning in warnings if warning.code == code]
        if not matching:
            raise error_for("UPSTREAM_INVALID")
        if domains and any(
            warning.domain is not None and warning.domain not in domains
            for warning in matching
        ):
            raise error_for("UPSTREAM_INVALID")


def _validate_raw_verification_run(value: Any) -> None:
    raw = _mapping(value)
    allowed = frozenset(
        {
            "runKey",
            "state",
            "requestedAt",
            "startedAt",
            "finishedAt",
            "scope",
            "counts",
            "warnings",
            "results",
        }
    )
    _reject_unknown_fields(raw, allowed)
    required = {
        "runKey",
        "state",
        "requestedAt",
        "startedAt",
        "finishedAt",
        "scope",
        "counts",
        "warnings",
    }
    if not required.issubset(raw):
        raise error_for("UPSTREAM_INVALID")
    item_fields = {
        "runKey",
        "state",
        "requestedAt",
        "startedAt",
        "finishedAt",
        "counts",
    }
    _validate_raw_run_item({key: raw[key] for key in item_fields})
    _validate_raw_scope(raw["scope"])
    if not isinstance(raw["warnings"], Sequence) or isinstance(
        raw["warnings"], (str, bytes)
    ):
        raise error_for("UPSTREAM_INVALID")
    warnings = _project_warnings(raw["warnings"])
    results: list[VerificationResult] = []
    results_value = raw.get("results")
    results_provided = results_value is not None
    if results_provided:
        results = results_value
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
            raise error_for("UPSTREAM_INVALID")
        if len(results) > 100:
            raise error_for("UPSTREAM_INVALID")
        results = [_project_result(result) for result in results]
    _validate_run_warning_semantics(
        raw,
        warnings=warnings,
        results=results,
    )
    _validate_run_state_invariants(
        raw,
        warnings=warnings,
        results=results,
        results_provided=results_provided,
    )


def _record_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise error_for("UPSTREAM_INVALID")
    if value.tzinfo is None:
        raise error_for("UPSTREAM_INVALID")
    return _timestamp(
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _project_verification_run(record: Any) -> VerificationRun:
    item = _dump(_project_run_list_item(record))
    try:
        record_domains = record.domains
        scope_date = record.scope_date
        scope_timezone = record.scope_timezone
        record_warnings = record.warnings
        record_results = record.results
    except Exception as exc:
        raise error_for("UPSTREAM_INVALID") from exc
    if not isinstance(record_domains, (tuple, list)):
        raise error_for("UPSTREAM_INVALID")
    domains = [domain for domain in record_domains if domain in _ALLOWED_DOMAINS]
    if len(domains) != len(record_domains) or not domains:
        raise error_for("UPSTREAM_INVALID")
    item["scope"] = _dump(
        _model(
            RunScope,
            {
                "date": _logical_date(scope_date),
                "timezone": _safe_timezone(scope_timezone),
                "domains": domains,
            },
        )
    )
    item["warnings"] = _dump_warning_list(record_warnings)
    if record_results is not None:
        if not isinstance(record_results, (tuple, list)):
            raise error_for("UPSTREAM_INVALID")
        item["results"] = [_dump(_project_result(result)) for result in record_results]
    _validate_raw_verification_run(item)
    return _model(VerificationRun, item)  # type: ignore[return-value]


def _dump_warning_list(value: Any) -> list[dict[str, Any]]:
    return [_dump(warning) for warning in _project_warnings(value)]


def _envelope(
    data: BaseModel | None,
    *,
    raw: Mapping[str, Any],
    timezone_name: str,
    requested: Mapping[str, Any] | None = None,
    daily_overview: bool = False,
    replace_requested_context: bool = False,
) -> dict[str, Any]:
    raw = _mapping(raw)
    _reject_non_finite(raw)
    if raw:
        _reject_unknown_fields(raw, _RAW_ENVELOPE_FIELDS)
        if set(raw) != _RAW_ENVELOPE_FIELDS:
            raise error_for("UPSTREAM_INVALID")
        if raw.get("schemaVersion") != "1":
            raise error_for("UPSTREAM_INVALID")
        _timestamp(raw.get("asOf"))
        _safe_timezone(raw.get("timezone"))
    envelope = Envelope(
        schemaVersion="1",
        asOf=_as_of_now(),
        timezone=timezone_name,
        data=data,
        coverage=_project_coverage(
            raw.get("coverage", {}),
            requested=requested,
            daily_overview=daily_overview,
            replace_requested_context=replace_requested_context,
        ),
        warnings=_project_warnings(raw.get("warnings", [])),
        extensions=_project_extensions(raw.get("extensions", {})),
    )
    return _dump(envelope)


def serialize_error(error: ErrorBody, *, timezone_name: str) -> dict[str, Any]:
    _validate_error_model(error)
    envelope = Envelope(
        schemaVersion="1",
        asOf=_as_of_now(),
        timezone=_safe_timezone(timezone_name),
        data=None,
        coverage=Coverage(),
        warnings=[],
        extensions=Extensions(),
        error=error,
    )
    return _dump(envelope)


def _raw_data(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(raw.get("data", {}))


def _validate_raw_session_data(value: Any) -> None:
    raw = _mapping(value)
    allowed = frozenset({"authenticated", "accessState", "canReadVerification"})
    _reject_unknown_fields(raw, allowed)
    if set(raw) != allowed:
        raise error_for("UPSTREAM_INVALID")
    if (
        type(raw["authenticated"]) is not bool
        or type(raw["canReadVerification"]) is not bool
    ):
        raise error_for("UPSTREAM_INVALID")
    if _allowed_string(raw["accessState"], _ALLOWED_SESSION_STATES) is None:
        raise error_for("UPSTREAM_INVALID")


def _validate_raw_settings_data(value: Any) -> None:
    raw = _mapping(value)
    _reject_unknown_fields(
        raw, frozenset({"contract", "versions", "capabilities", "technicalState"})
    )
    if set(raw) != {"contract", "versions", "capabilities", "technicalState"}:
        raise error_for("UPSTREAM_INVALID")
    versions = _mapping(raw.get("versions"))
    _reject_unknown_fields(versions, frozenset({"bffSchema", "owReference"}))
    if versions != {"bffSchema": "1", "owReference": "not_pinned"}:
        raise error_for("UPSTREAM_INVALID")
    capabilities = _mapping(raw.get("capabilities"))
    _reject_unknown_fields(
        capabilities, frozenset({"gps", "workoutDetails", "segments", "hrZones"})
    )
    if set(capabilities) != {"gps", "workoutDetails", "segments", "hrZones"}:
        raise error_for("UPSTREAM_INVALID")
    if any(
        value not in {"aggregate_only", "not_verifiable"}
        for value in capabilities.values()
    ):
        raise error_for("UPSTREAM_INVALID")
    if raw.get("contract") != "bff-ui-v1" or raw.get("technicalState") != "ready":
        raise error_for("UPSTREAM_INVALID")


def _validate_raw_run_list_data(value: Any) -> None:
    raw = _mapping(value)
    _reject_unknown_fields(raw, frozenset({"items", "page"}))
    if set(raw) != {"items", "page"}:
        raise error_for("UPSTREAM_INVALID")
    items = raw["items"]
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise error_for("UPSTREAM_INVALID")
    if len(items) > 100:
        raise error_for("UPSTREAM_INVALID")
    for item in items:
        _validate_raw_run_item(item)
    _validate_raw_run_page(raw.get("page"))


def _validate_raw_run_detail_data(value: Any) -> None:
    raw = _mapping(value)
    _reject_unknown_fields(raw, frozenset({"verificationRun"}))
    _validate_raw_verification_run(raw.get("verificationRun"))


def _validate_raw_overview_data(value: Any) -> None:
    raw = _mapping(value)
    _reject_unknown_fields(raw, frozenset({"logicalDate", "summary", "sources"}))
    if not {"logicalDate", "summary"}.issubset(raw):
        raise error_for("UPSTREAM_INVALID")
    _logical_date(raw["logicalDate"])
    _project_overview_summary(raw["summary"])
    if "sources" in raw:
        _project_source_items(raw["sources"])


def _validate_overview_warning_semantics(raw: Mapping[str, Any]) -> None:
    data = _mapping(raw.get("data"))
    coverage = _mapping(raw.get("coverage"))
    summary = _mapping(data.get("summary"))
    warnings = _project_warnings(raw.get("warnings"))
    expected_domains: dict[str, frozenset[str]] = {}
    metric_domains = _OVERVIEW_WARNING_DOMAINS
    source_items = _project_source_items(data["sources"]) if "sources" in data else []
    source_ambiguity = any(item.state == "source_ambiguous" for item in source_items)
    if source_ambiguity and not any(
        warning.code == "SOURCE_AMBIGUOUS" for warning in warnings
    ):
        raise error_for("UPSTREAM_INVALID")
    partial_domains = {
        metric_domains[name]
        for name, metric in summary.items()
        if name in metric_domains and _mapping(metric).get("state") == "partial"
    }
    ambiguous_domains = {
        metric_domains[name]
        for name, metric in summary.items()
        if name in metric_domains
        and _mapping(metric).get("state") == "source_ambiguous"
    }
    by_domain = coverage.get("byDomain")
    if isinstance(by_domain, Mapping):
        partial_domains.update(
            domain
            for domain, value in by_domain.items()
            if isinstance(value, Mapping) and value.get("state") == "partial"
        )
    body = _mapping(by_domain).get("body") if by_domain is not None else None
    if isinstance(body, Mapping) and body.get("state") == "relative_to_now":
        if not any(warning.code == "BODY_RELATIVE_TO_NOW" for warning in warnings):
            raise error_for("UPSTREAM_INVALID")
        expected_domains["BODY_RELATIVE_TO_NOW"] = frozenset({"body"})
    elif any(warning.code == "BODY_RELATIVE_TO_NOW" for warning in warnings):
        raise error_for("UPSTREAM_INVALID")
    if partial_domains:
        expected_domains["PARTIAL_COVERAGE"] = frozenset(partial_domains)
    elif any(warning.code == "PARTIAL_COVERAGE" for warning in warnings):
        raise error_for("UPSTREAM_INVALID")
    if ambiguous_domains:
        expected_domains["SOURCE_AMBIGUOUS"] = frozenset(ambiguous_domains)
    elif not source_ambiguity and any(
        warning.code == "SOURCE_AMBIGUOUS" for warning in warnings
    ):
        raise error_for("UPSTREAM_INVALID")
    unsupported_metric_domains = {
        metric_domains[name]
        for name, metric in summary.items()
        if name in metric_domains and _mapping(metric).get("state") == "unsupported"
    }
    unsupported_warnings = [
        warning for warning in warnings if warning.code == "UNSUPPORTED"
    ]
    if unsupported_warnings and not any(
        _mapping(metric).get("state") == "unsupported" for metric in summary.values()
    ):
        raise error_for("UPSTREAM_INVALID")
    if unsupported_warnings and unsupported_metric_domains:
        if any(
            warning.domain is not None
            and warning.domain not in unsupported_metric_domains
            for warning in unsupported_warnings
        ):
            raise error_for("UPSTREAM_INVALID")
    _validate_warning_domains(warnings, expected_domains)
    if "body" in data and data["body"] is not None:
        raise error_for("UPSTREAM_INVALID")


def _validate_overview_coverage_semantics(raw: Mapping[str, Any]) -> None:
    data = _mapping(raw.get("data"))
    summary = _mapping(data.get("summary"))
    coverage = _mapping(raw.get("coverage"))
    expected_days = coverage.get("expectedDays")
    available_days = coverage.get("availableDays")
    if (
        expected_days != 1
        or type(available_days) is not int
        or available_days not in {0, 1}
        or available_days > expected_days
        or type(coverage.get("isPartial")) is not bool
    ):
        raise error_for("UPSTREAM_INVALID")

    observed_states = {"value", "zero", "partial", "source_ambiguous"}
    observed_metric_domains = {
        _OVERVIEW_METRIC_DOMAINS[metric_name]
        for metric_name, metric in summary.items()
        if metric_name in _OVERVIEW_METRIC_DOMAINS
        and _mapping(metric).get("state") in observed_states
    }
    if available_days == 0 and observed_metric_domains:
        raise error_for("UPSTREAM_INVALID")

    by_domain = coverage.get("byDomain")
    if observed_metric_domains and (
        not isinstance(by_domain, Mapping) or not by_domain
    ):
        raise error_for("UPSTREAM_INVALID")
    if isinstance(by_domain, Mapping):
        domain_values = {
            domain: _mapping(domain_value) for domain, domain_value in by_domain.items()
        }
        if not summary and any(
            value.get("state") == "complete" for value in domain_values.values()
        ):
            raise error_for("UPSTREAM_INVALID")
        for domain in observed_metric_domains:
            domain_value = domain_values.get(domain)
            if domain_value is None or (
                domain_value.get("state") not in {"complete", "partial"}
                or domain_value.get("availableDays") is None
                or domain_value.get("availableDays") == 0
            ):
                raise error_for("UPSTREAM_INVALID")
        partial_observation = any(
            value.get("state") == "partial" for value in domain_values.values()
        )
    else:
        partial_observation = False
    if not summary and data.get("sources") == [] and available_days != 0:
        raise error_for("UPSTREAM_INVALID")

    for metric in summary.values():
        if _mapping(metric).get("state") == "partial":
            partial_observation = True
            break
    if coverage["isPartial"] is not partial_observation:
        raise error_for("UPSTREAM_INVALID")
    if coverage["isPartial"] and available_days != 1:
        raise error_for("UPSTREAM_INVALID")


def _validate_raw_success_response(
    value: Any,
    data_validator: Any,
) -> None:
    raw = _mapping(value)
    _reject_non_finite(raw)
    _reject_unknown_fields(raw, _RAW_ENVELOPE_FIELDS)
    if set(raw) != _RAW_ENVELOPE_FIELDS or raw.get("schemaVersion") != "1":
        raise error_for("UPSTREAM_INVALID")
    _timestamp(raw.get("asOf"))
    _safe_timezone(raw.get("timezone"))
    _project_coverage(raw.get("coverage"))
    _project_warnings(raw.get("warnings"))
    _project_extensions(raw.get("extensions"))
    data_validator(raw.get("data"))


@_serializer_boundary
def validate_adapter_run_list_response(value: Any) -> None:
    _validate_raw_success_response(value, _validate_raw_run_list_data)


@_serializer_boundary
def validate_adapter_run_detail_response(value: Any) -> None:
    _validate_raw_success_response(value, _validate_raw_run_detail_data)


def project_seed_run_item(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize an adapter run before storing control state."""

    try:
        _reject_non_finite(value)
        _validate_raw_run_item(value)
        return _dump(_model(RunListItem, value))
    except BFFError:
        raise
    except Exception as exc:
        raise error_for("UPSTREAM_INVALID") from exc


def project_seed_verification_run(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a complete adapter run before storing it."""

    try:
        _reject_non_finite(value)
        _validate_raw_verification_run(value)
        return _dump(_model(VerificationRun, value))
    except BFFError:
        raise
    except Exception as exc:
        raise error_for("UPSTREAM_INVALID") from exc


@_serializer_boundary
def serialize_session(
    raw: Mapping[str, Any],
    *,
    authenticated: bool,
    access_state: AccessState,
    can_read_verification: bool,
) -> dict[str, Any]:
    raw_data = _raw_data(raw)
    if raw_data:
        _validate_raw_session_data(raw_data)
    data = _model(
        SessionData,
        {
            "authenticated": authenticated,
            "accessState": access_state,
            "canReadVerification": can_read_verification,
        },
    )
    return _envelope(data, raw=raw, timezone_name="UTC")


@_serializer_boundary
def serialize_overview(
    raw: Mapping[str, Any],
    *,
    logical_date: str,
    timezone_name: str,
    from_utc: str,
    to_utc: str,
    allow_empty_date_projection: bool = False,
) -> dict[str, Any]:
    raw_data = _raw_data(raw)
    _validate_raw_overview_data(raw_data)
    _validate_overview_warning_semantics(raw)
    _validate_overview_coverage_semantics(raw)
    if allow_empty_date_projection:
        if (
            raw_data.get("summary") != {}
            or raw_data.get("sources") != []
            or raw.get("warnings") != []
            or _mapping(raw.get("coverage")).get("byDomain") != {}
        ):
            raise error_for("UPSTREAM_INVALID")
    elif raw_data["logicalDate"] != logical_date:
        raise error_for("UPSTREAM_INVALID")
    values: dict[str, Any] = {
        "logicalDate": logical_date,
        "summary": _dump(
            _project_overview_summary(raw_data.get("summary", {}), daily_overview=True)
        ),
    }
    if "sources" in raw_data:
        values["sources"] = [
            _dump(item) for item in _project_source_items(raw_data["sources"])
        ]
    data = _model(OverviewData, values)
    requested = {
        "logicalDate": logical_date,
        "from": from_utc,
        "to": to_utc,
        "timezone": timezone_name,
    }
    return _envelope(
        data,
        raw=raw,
        timezone_name=timezone_name,
        requested=requested,
        daily_overview=True,
        replace_requested_context=True,
    )


@_serializer_boundary
def serialize_activity_trend(
    raw: Mapping[str, Any],
    *,
    logical_date: str,
    timezone_name: str,
    from_utc: str,
    to_utc: str,
) -> dict[str, Any]:
    raw_data = _mapping(raw.get("data"))
    if set(raw_data) != {
        "logicalDate",
        "range",
        "steps",
        "distanceMeters",
        "points",
        "bucketMode",
    }:
        raise error_for("UPSTREAM_INVALID")
    range_name = raw_data["range"]
    if range_name not in {"daily", "7d", "monthly", "180d", "annual"}:
        raise error_for("UPSTREAM_INVALID")
    if raw_data["bucketMode"] not in {"daily", "calendar-month"}:
        raise error_for("UPSTREAM_INVALID")
    points = raw_data["points"]
    if not isinstance(points, Sequence) or not points:
        raise error_for("UPSTREAM_INVALID")
    point_values = []
    _, _, expected_dates = trend_date_scope(
        date.fromisoformat(logical_date), range_name
    )
    if raw_data["logicalDate"] != logical_date:
        raise error_for("UPSTREAM_INVALID")
    seen_dates: list[str] = []
    for point in points:
        point_raw = _mapping(point)
        if set(point_raw) != {"date", "steps", "distanceMeters"}:
            raise error_for("UPSTREAM_INVALID")
        point_date = _logical_date(point_raw["date"])
        seen_dates.append(point_date)
        values: dict[str, Any] = {"date": point_date}
        for key in ("steps", "distanceMeters"):
            metric = _mapping(point_raw[key])
            if set(metric) != {"state", "value", "unit"} or metric["state"] not in {
                "empty",
                "inconclusive",
                "null",
                "partial",
                "zero",
                "value",
                "source_ambiguous",
            }:
                raise error_for("UPSTREAM_INVALID")
            value = _safe_number(metric.get("value"), optional=True)
            if (
                metric["state"] in {"empty", "null", "inconclusive"}
                and value is not None
            ):
                raise error_for("UPSTREAM_INVALID")
            expected_unit = "count" if key == "steps" else "meters"
            if (
                metric["state"] in {"value", "partial", "zero"}
                and metric.get("unit") != expected_unit
            ):
                raise error_for("UPSTREAM_INVALID")
            if metric["state"] in {
                "empty",
                "null",
                "inconclusive",
                "source_ambiguous",
            } and metric.get("unit") not in {None, expected_unit}:
                raise error_for("UPSTREAM_INVALID")
            if metric["state"] == "zero" and value != 0:
                raise error_for("UPSTREAM_INVALID")
            if metric["state"] == "value" and value is None:
                raise error_for("UPSTREAM_INVALID")
            values[key] = {
                "state": metric["state"],
                "value": value,
                "unit": metric.get("unit"),
            }
        point_values.append(values)
    if seen_dates != expected_dates or len(set(seen_dates)) != len(expected_dates):
        raise error_for("UPSTREAM_INVALID")
    for metric_name in ("steps", "distanceMeters"):
        metric = _mapping(raw_data[metric_name])
        if set(metric) != {
            "unit",
            "totalObserved",
            "averageObserved",
            "observedDays",
            "expectedDays",
        }:
            raise error_for("UPSTREAM_INVALID")
        if (
            metric["unit"] not in {"count", "meters"}
            or _safe_int(metric["observedDays"]) < 0
            or _safe_int(metric["expectedDays"]) < 1
        ):
            raise error_for("UPSTREAM_INVALID")
        total = _safe_number(metric["totalObserved"], optional=True)
        average = _safe_number(metric["averageObserved"], optional=True)
        if (_safe_int(metric["observedDays"]) == 0) != (
            total is None and average is None
        ):
            raise error_for("UPSTREAM_INVALID")
    data = _model(
        ActivityTrendData,
        {
            "logicalDate": logical_date,
            "range": range_name,
            "steps": raw_data["steps"],
            "distanceMeters": raw_data["distanceMeters"],
            "points": point_values,
            "bucketMode": raw_data["bucketMode"],
        },
    )
    requested = {
        "logicalDate": logical_date,
        "from": from_utc,
        "to": to_utc,
        "timezone": timezone_name,
    }
    return _envelope(
        data,
        raw=raw,
        timezone_name=timezone_name,
        requested=requested,
        replace_requested_context=True,
    )


def _validate_source_warning_semantics(
    raw: Mapping[str, Any], items: Sequence[SourceItem]
) -> None:
    warnings = _project_warnings(raw.get("warnings"))
    has_ambiguous_source = any(item.state == "source_ambiguous" for item in items)
    has_ambiguity_warning = any(
        warning.code == "SOURCE_AMBIGUOUS" for warning in warnings
    )
    if has_ambiguous_source != has_ambiguity_warning:
        raise error_for("UPSTREAM_INVALID")


@_serializer_boundary
def serialize_sources(raw: Mapping[str, Any], *, timezone_name: str) -> dict[str, Any]:
    raw_data = _raw_data(raw)
    _reject_unknown_fields(raw_data, frozenset({"items"}))
    if set(raw_data) != {"items"}:
        raise error_for("UPSTREAM_INVALID")
    items = _project_source_items(raw_data.get("items", []))
    _validate_source_warning_semantics(raw, items)
    data = _model(
        SourceData,
        {"items": items},
    )
    return _envelope(data, raw=raw, timezone_name=timezone_name)


@_serializer_boundary
def serialize_settings(raw: Mapping[str, Any]) -> dict[str, Any]:
    _validate_raw_settings_data(_raw_data(raw))
    data = _model(
        SettingsData,
        {
            "contract": "bff-ui-v1",
            "versions": _model(
                SettingsVersions,
                {"bffSchema": "1", "owReference": "not_pinned"},
            ),
            "capabilities": _model(
                SettingsCapabilities,
                {
                    "gps": "not_verifiable",
                    "workoutDetails": "aggregate_only",
                    "segments": "not_verifiable",
                    "hrZones": "not_verifiable",
                },
            ),
            "technicalState": "ready",
        },
    )
    return _envelope(data, raw=raw, timezone_name="UTC")


@_serializer_boundary
def serialize_run_list(
    raw: Mapping[str, Any],
    *,
    records: Sequence[Any],
    next_cursor: str | None,
    has_next: bool,
    timezone_name: str,
) -> dict[str, Any]:
    _validate_raw_run_list_data(_raw_data(raw))
    page = _model(
        RunPage,
        {
            "nextCursor": _safe_cursor(next_cursor, optional=True),
            "hasNext": has_next,
            "totalCount": None,
        },
    )
    data = _model(
        RunListData,
        {
            "items": [_project_run_list_item(record) for record in records],
            "page": page,
        },
    )
    return _envelope(data, raw=raw, timezone_name=timezone_name)


@_serializer_boundary
def serialize_run_detail(
    raw: Mapping[str, Any], *, record: Any, timezone_name: str
) -> dict[str, Any]:
    _validate_raw_run_detail_data(_raw_data(raw))
    data = _model(
        RunDetailData,
        {"verificationRun": _project_verification_run(record)},
    )
    return _envelope(data, raw=raw, timezone_name=timezone_name)


@_serializer_boundary
def serialize_run_create(
    raw: Mapping[str, Any], *, record: Any, timezone_name: str
) -> dict[str, Any]:
    return serialize_run_detail(raw, record=record, timezone_name=timezone_name)


@_serializer_boundary
def serialize_stored_run_create(*, record: Any, timezone_name: str) -> dict[str, Any]:
    data = _model(
        RunDetailData,
        {"verificationRun": _project_verification_run(record)},
    )
    return _envelope(data, raw={}, timezone_name=timezone_name)
