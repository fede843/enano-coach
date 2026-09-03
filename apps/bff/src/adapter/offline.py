"""Deterministic, offline access to the two public synthetic fixtures.

The adapter has no network, persistence, or browser-facing path input.  Its
small server-side interface is:

``OfflineFixtureAdapter.get_ow_response(case)``
    Return one validated, allowlisted OW-shaped response in ``snake_case``.
``OfflineFixtureAdapter.get_ow_case(case)``
    Return one validated OW assertion case for adapter-side verification.
``OfflineFixtureAdapter.get_bff_response(case)``
    Return one validated BFF/UI response in ``camelCase``.  Server-side
    ``adapterMappings`` are never part of this result.

The default constructor reads only the repository fixtures selected by this
module.  ``from_documents`` exists for local contract tests and still applies
the same validation; it does not accept a filesystem path or URL.
"""

from __future__ import annotations

import ipaddress
import json
import math
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

JsonObject = dict[str, Any]


class FixtureContractError(RuntimeError):
    """Raised when a synthetic fixture cannot be trusted by the adapter."""


_OW_RESPONSE_CASES = frozenset(
    {
        "data_sources",
        "coverage",
        "timeseries_match",
        "timeseries_value_null",
        "timeseries_is_daily_total_null",
        "activity_summary",
        "sleep_summary",
        "events_sleep",
        "recovery_summary",
        "summaries_data",
        "body_summary_relative_now",
        "workouts_aggregate",
        "sync_runs_terminal",
        "sync_recent",
        "sync_stream",
    }
)

_OW_ASSERTION_CASES = frozenset(
    {
        "match",
        "summaries_data",
        "events_sleep",
        "sync_stream",
        "value_null",
        "is_daily_total_null",
        "empty",
        "zero",
        "null",
        "partial",
        "unsupported",
        "source_ready",
        "source_ambiguous",
        "pending",
        "inconclusive",
        "mismatch",
    }
)

_BFF_SUCCESS_CASES = frozenset(
    {
        "session_active",
        "session_anonymous_200",
        "overview_mixed",
        "overview_empty",
        "overview_error",
        "settings_capabilities",
        "source_ready",
        "source_ambiguous",
        "runs_first_page",
        "runs_second_page",
        "verification_run_create",
        "verification_run_partial",
        "verification_not_verifiable",
        "verification_run_mismatch",
        "verification_inconclusive",
    }
)

_BFF_ERROR_CASES = frozenset(
    {
        "session_required_401",
        "session_anonymous_401",
        "access_pending_403",
        "run_not_found_404",
        "upstream_invalid_502",
        "upstream_unavailable_503",
        "upstream_timeout_504",
        "invalid_query_400",
        "invalid_cursor_400",
        "cursor_context_mismatch_400",
        "invalid_scope_422",
        "cursor_expired_410",
        "access_blocked_403",
        "idempotency_conflict_409",
        "rate_limited_429",
        "internal_error_500",
    }
)

_BFF_OVERVIEW_SUMMARY_FIELDS = frozenset(
    {
        "steps",
        "distanceMeters",
        "activeCaloriesKcal",
        "sleepDurationSeconds",
        "recoveryScore",
        "stress",
        "heartRate",
    }
)
_BFF_SOURCE_CAPABILITIES = frozenset({"activity", "body", "heart_rate", "sleep"})
_BFF_SOURCE_STATES = frozenset({"ready", "source_ambiguous"})
_BFF_WARNING_SEVERITIES = frozenset({"info", "warning"})
_BFF_WARNING_DOMAINS = frozenset(
    {"activity", "body", "heart_rate", "recovery", "sleep", "workouts"}
)
_BFF_METRIC_UNITS = frozenset(
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
_BFF_OVERVIEW_METRIC_UNITS: dict[str, str | None] = {
    "steps": "count",
    "distanceMeters": "meters",
    "activeCaloriesKcal": "kcal",
    "sleepDurationSeconds": "seconds",
    "recoveryScore": None,
    "stress": None,
    "heartRate": "bpm",
}
_BFF_UNITLESS_VALUE_METRICS = frozenset({"recoveryScore"})
_OW_TIMESERIES_UNIT_BY_TYPE: dict[str, str] = {
    "heart_rate": "bpm",
    "resting_heart_rate": "bpm",
    "heart_rate_variability_sdnn": "ms",
    "heart_rate_variability_rmssd": "ms",
    "oxygen_saturation": "percent",
    "body_fat_percentage": "percent",
    "steps": "count",
    "flights_climbed": "count",
    "swimming_stroke_count": "count",
    "energy": "kcal",
    "basal_energy": "kcal",
    "distance": "meters",
    "six_minute_walk_test_distance": "meters",
    "elevation": "meters",
    "underwater_depth": "meters",
    "weight": "kg",
    "lean_body_mass": "kg",
    "body_fat_mass": "kg",
    "height": "cm",
    "walking_step_length": "cm",
    "body_temperature": "celsius",
    "skin_temperature": "celsius",
    "speed": "m_per_s",
    "running_speed": "m_per_s",
    "walking_speed": "m_per_s",
    "cadence": "rpm",
    "power": "watts",
    "running_power": "watts",
}
_BFF_RESULT_METRICS = frozenset({"extended_workout_detail", "steps"})
_BFF_RESULT_STATES = frozenset({"inconclusive", "match", "mismatch", "not_verifiable"})
_BFF_RESULT_REASON_CODES = frozenset({"CURSOR_EXPIRED", "NO_PUBLIC_WORKOUT_DETAIL"})
_BFF_ERROR_FIELDS = frozenset({"cursor", "date", "domains", None})
_BFF_ERROR_EXPECTATIONS: dict[str, tuple[str, str | None, bool]] = {
    "overview_error": ("UPSTREAM_TIMEOUT", None, True),
    "session_required_401": ("SESSION_REQUIRED", None, False),
    "session_anonymous_401": ("SESSION_REQUIRED", None, False),
    "access_pending_403": ("ACCESS_PENDING", None, False),
    "run_not_found_404": ("RUN_NOT_FOUND", None, False),
    "upstream_invalid_502": ("UPSTREAM_INVALID", None, False),
    "upstream_unavailable_503": ("UPSTREAM_UNAVAILABLE", None, True),
    "upstream_timeout_504": ("UPSTREAM_TIMEOUT", None, True),
    "invalid_query_400": ("INVALID_QUERY", "date", False),
    "invalid_cursor_400": ("INVALID_CURSOR", "cursor", False),
    "cursor_context_mismatch_400": ("CURSOR_CONTEXT_MISMATCH", "cursor", False),
    "invalid_scope_422": ("INVALID_SCOPE", "domains", False),
    "cursor_expired_410": ("CURSOR_EXPIRED", "cursor", True),
    "access_blocked_403": ("ACCESS_BLOCKED", None, False),
    "idempotency_conflict_409": ("IDEMPOTENCY_CONFLICT", None, False),
    "rate_limited_429": ("RATE_LIMITED", None, True),
    "internal_error_500": ("INTERNAL_ERROR", None, False),
}

_BASE_BFF_FIELDS = frozenset(
    {"schemaVersion", "asOf", "timezone", "data", "coverage", "warnings", "extensions"}
)
_FORBIDDEN_RAW_KEYS = frozenset(
    {
        "apikey",
        "authorization",
        "cookie",
        "credentials",
        "headers",
        "metadata",
        "password",
        "payload",
        "raw",
        "rawerror",
        "rawmessage",
        "rawpayload",
        "secret",
        "sql",
        "stack",
        "token",
        "providererror",
        "providermessage",
    }
)
_FORBIDDEN_BFF_KEYS = frozenset({"adaptermappings", "owrunid", "owstage", "owstatus"})
_OW_RAW_KEYS = frozenset({"metadata", "message", "error"})
_BFF_ALLOWED_IDENTIFIER_FIELDS = frozenset(
    {"sourceKey", "runKey", "requestId", "workoutKey", "sleepKey", "eventKey"}
)
_OW_ALLOWED_IDENTIFIER_FIELDS = frozenset(
    {
        "id",
        "user_id",
        "user_connection_id",
        "run_id",
        "event_id",
        "owRunId",
        "runKey",
    }
)
_NULL_ONLY_IDENTIFIER_FIELDS = frozenset({"user_connection_id"})
_DEMO_ID_PATTERNS = {
    "id": re.compile(
        r"^(?:source-record-demo|sleep-event-demo|workout-demo)-[a-z0-9-]+$"
    ),
    "run_id": re.compile(r"^ow-run-demo-[a-z0-9-]+$"),
    "event_id": re.compile(r"^sync-event-demo-[a-z0-9-]+$"),
    "user_id": re.compile(r"^user-demo-[a-z0-9-]+$"),
    "user_connection_id": None,
    "source": re.compile(r"^(?:source-demo|sdk-demo)(?:-[a-z0-9-]+)?$"),
    "sourceKey": re.compile(r"^(?:source-demo|synthetic-source)-[a-z0-9-]+$"),
    "runKey": re.compile(r"^verify-demo-[a-z0-9-]+$"),
    "owRunId": re.compile(r"^ow-run-demo-[a-z0-9-]+$"),
    "requestId": re.compile(r"^req-demo-[a-z0-9-]+$"),
}
_DEMO_ID_PATTERNS_BY_NORMALIZED_KEY = {
    key.replace("_", "").casefold(): pattern
    for key, pattern in _DEMO_ID_PATTERNS.items()
}
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_EMAIL_LIKE_PATTERN = re.compile(r"(?<![\w.+-])[^\s@]+@[^\s@]+\.[^\s@]+(?![\w.-])")
_URL_PATTERN = re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_HOST_PATTERN = re.compile(
    r"^(?:localhost|(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}|(?:\d{1,3}\.){3}\d{1,3})(?::\d{1,5})?(?:[/?#].*)?$",
    re.IGNORECASE,
)
_HOST_WITH_PORT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}:\d{1,5}$", re.IGNORECASE)
_HOST_IN_TEXT_PATTERN = re.compile(
    r"(?<![a-z0-9._-])(?:localhost|(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}|(?:\d{1,3}\.){3}\d{1,3})(?::\d{1,5})?"
    r"(?:[/?#][^\s]*)?(?![a-z0-9._-])",
    re.IGNORECASE,
)
_ALLOWED_DOTTED_STRINGS = frozenset({"sync.status"})
_WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^[a-z]:[\\/]", re.IGNORECASE)
_ABSOLUTE_PATH_IN_TEXT_PATTERN = re.compile(
    r"(?<!\S)(?:[a-z]:[\\/]|/|\\\\)", re.IGNORECASE
)
_UUID_PATTERN = re.compile(
    r"(?<![0-9a-f])(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})(?![0-9a-f])",
    re.IGNORECASE,
)
_HEX_UUID_PATTERN = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])", re.IGNORECASE)
_MAC_PATTERN = re.compile(
    r"(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])",
    re.IGNORECASE,
)
_RAW_UPSTREAM_STRING_PATTERN = re.compile(
    r"(?:\btraceback\b|\bstack\s+trace\b|\bexception\b|\bcaused\s+by\b|"
    r"\b(?:provider|raw|upstream)[\s_-]*(?:detail|message|error|exception|"
    r"response|failure|payload|body|data)\b|"
    r"\b[a-z][a-z0-9_]*(?:error|exception)\s*:)",
    re.IGNORECASE,
)
_CREDENTIAL_TEXT_PATTERN = re.compile(
    r"(?:\b(?:api[\s_-]*key|access[\s_-]*token|refresh[\s_-]*token|"
    r"bearer|token|secret|password|credential|authorization|cookie|"
    r"private[\s_-]*key)\b|-----begin\s+[^\r\n]*private\s+key-----)",
    re.IGNORECASE,
)
_INTERNAL_IDENTIFIER_TEXT_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:"
    r"(?:ow[\s_-]*)?user[\s_-]*(?:id|uid|key|identifier|connection"
    r"[\s_-]*(?:id|uid|key|identifier)?)|"
    r"(?:primary|local|app)[\s_-]*user[\s_-]*(?:id|uid|key|identifier)|"
    r"(?:ow[\s_-]*)?(?:owner|connection|source|provider|device|run|batch|manifest|"
    r"event|workout|sleep)[\s_-]*(?:id|uid|key|identifier)"
    r")",
    re.IGNORECASE,
)
_RFC3339_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WARNING_CODES = frozenset(
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
_ERROR_CODES = frozenset(
    {
        "ACCESS_BLOCKED",
        "ACCESS_PENDING",
        "CURSOR_CONTEXT_MISMATCH",
        "CURSOR_EXPIRED",
        "IDEMPOTENCY_CONFLICT",
        "INTERNAL_ERROR",
        "INVALID_CURSOR",
        "INVALID_QUERY",
        "INVALID_SCOPE",
        "RATE_LIMITED",
        "RUN_NOT_FOUND",
        "SESSION_REQUIRED",
        "UPSTREAM_INVALID",
        "UPSTREAM_TIMEOUT",
        "UPSTREAM_UNAVAILABLE",
    }
)
_BFF_WARNING_MESSAGES = {
    "PARTIAL_COVERAGE": frozenset(
        {
            "La distancia solo cubre parte de la ventana.",
            "La ventana no se pudo cerrar por completo.",
        }
    ),
    "SOURCE_AMBIGUOUS": frozenset(
        {
            "No hay una fuente \u00fanica para frecuencia card\u00edaca.",
            "La atribuci\u00f3n requiere una regla adicional.",
        }
    ),
    "BODY_RELATIVE_TO_NOW": frozenset({"Body es relativo al momento de consulta."}),
    "NOT_VERIFIABLE": frozenset(
        {"La API p\u00fablica no ofrece el schema necesario para esta afirmaci\u00f3n."}
    ),
    "MISMATCH": frozenset({"El hecho observado no coincide con el esperado."}),
    "INCONCLUSIVE": frozenset(
        {"No se pudo cerrar la comparaci\u00f3n porque falt\u00f3 una p\u00e1gina."}
    ),
}
_BFF_ERROR_MESSAGES = {
    "SESSION_REQUIRED": frozenset({"La sesi\u00f3n es necesaria para consultar."}),
    "ACCESS_PENDING": frozenset(
        {"La cuenta todav\u00eda no tiene acceso a esta consulta."}
    ),
    "RUN_NOT_FOUND": frozenset(
        {"No se encontr\u00f3 la verificaci\u00f3n solicitada."}
    ),
    "UPSTREAM_INVALID": frozenset(
        {"La fuente devolvi\u00f3 una respuesta no v\u00e1lida."}
    ),
    "UPSTREAM_UNAVAILABLE": frozenset(
        {"La fuente no est\u00e1 disponible; vuelve a consultar manualmente."}
    ),
    "UPSTREAM_TIMEOUT": frozenset(
        {
            "La fuente tard\u00f3 demasiado en responder.",
            "No se pudo completar la consulta del resumen.",
        }
    ),
    "INVALID_QUERY": frozenset({"La fecha o zona horaria no es v\u00e1lida."}),
    "INVALID_CURSOR": frozenset({"El cursor no es v\u00e1lido para este listado."}),
    "CURSOR_CONTEXT_MISMATCH": frozenset(
        {"The cursor does not match the current list context."}
    ),
    "INVALID_SCOPE": frozenset(
        {"El alcance de la verificaci\u00f3n no es v\u00e1lido."}
    ),
    "CURSOR_EXPIRED": frozenset(
        {"La p\u00e1gina solicitada expir\u00f3; reinicia el listado."}
    ),
    "ACCESS_BLOCKED": frozenset({"El acceso a esta consulta est\u00e1 bloqueado."}),
    "IDEMPOTENCY_CONFLICT": frozenset(
        {"La solicitud entra en conflicto con una operaci\u00f3n existente."}
    ),
    "RATE_LIMITED": frozenset({"Se alcanz\u00f3 el l\u00edmite de solicitudes."}),
    "INTERNAL_ERROR": frozenset({"No se pudo completar la solicitud."}),
}
_BFF_FIXTURE_CASE_BY_RESPONSE_CASE = {
    **{case: case for case in _BFF_SUCCESS_CASES},
    **{case: case for case in _BFF_ERROR_CASES},
    "session_required_401": "auth_401",
    "access_pending_403": "auth_403",
    "invalid_query_400": "validation_400_query",
    "invalid_cursor_400": "validation_400_cursor",
    "invalid_scope_422": "validation_422_scope",
}
_OW_EXPECTED_RESULTS = {
    "match": "match",
    "summaries_data": "aggregate_inventory_without_pagination",
    "events_sleep": "sleep_event_with_specific_stages",
    "sync_stream": "sse_frames_not_pagination",
    "value_null": "null_not_zero",
    "is_daily_total_null": "unknown_daily_total_semantics",
    "empty": "empty_not_zero",
    "zero": "zero",
    "null": "null_not_zero",
    "partial": "partial_until_next_page",
    "unsupported": "unsupported",
    "source_ready": "ready",
    "source_ambiguous": "source_ambiguous",
    "pending": "pending",
    "inconclusive": "inconclusive",
    "mismatch": "mismatch",
}
_BFF_DATA_STATES = frozenset(
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
_BFF_RUN_STATES = frozenset(
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
_OW_SYNC_STATES = frozenset(
    {
        "accepted",
        "cancelled",
        "completed",
        "failed",
        "fetching",
        "in_progress",
        "partial",
        "pending",
        "processing",
        "queued",
        "saving",
        "skipped",
        "started",
        "success",
    }
)
_BFF_COVERAGE_STATES = frozenset(
    {
        "complete",
        "empty",
        "inconclusive",
        "not_verifiable",
        "partial",
        "relative_to_now",
        "unsupported",
    }
)
_DEVICE_TYPES = frozenset(
    {"band", "other", "phone", "ring", "scale", "unknown", "watch"}
)
_SLEEP_STAGES = frozenset(
    {"awake", "deep", "in_bed", "light", "rem", "sleeping", "unknown"}
)
_SAFE_METRIC_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_PROVIDER_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_OW_CURSOR_PATTERN = re.compile(r"^ow-cursor-demo-[a-z0-9-]+$")
_BFF_CURSOR_PATTERN = re.compile(r"^bff-cursor-demo-[a-z0-9-]+$")
_ZONE_OFFSET_PATTERN = re.compile(r"^(?:Z|[+-](?:0\d|1\d|2[0-3]):[0-5]\d)$")
_SCHEME_IN_TEXT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9+.-]*:(?=\S)", re.IGNORECASE
)
_KNOWN_SCHEME_IN_TEXT_PATTERN = re.compile(
    r"(?:blob|data|file|ftp|http|https|javascript|mailto|ssh|tel|ws|wss):",
    re.IGNORECASE,
)
_IPV6_IN_TEXT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[\[0-9A-Fa-f:]{2,}(?:%[A-Za-z0-9_.-]+)?\]?(?![A-Za-z0-9])"
)
_COORDINATE_PAIR_PATTERN = re.compile(
    r"(?<![A-Za-z0-9.])[+-]?\d{1,3}(?:\.\d+)?\s*[,;]\s*"
    r"[+-]?\d{1,3}(?:\.\d+)?(?![A-Za-z0-9.])"
)
_WINDOWS_PATH_IN_TEXT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]", re.IGNORECASE
)
_INTERNAL_IDENTIFIER_VALUE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:user-demo|ow-run-demo|verify-demo|batch-demo|"
    r"connection-demo|source-record-demo|sleep-event-demo|workout-demo)-"
    r"[A-Za-z0-9-]+(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_MAX_PERCENT_DECODE_ROUNDS = 16
_MAX_DOCUMENT_DEPTH = 128
_MAX_DOCUMENT_NODES = 10_000
_MAX_CONTAINER_ITEMS = 5_000
_MAX_STRING_LENGTH = 100_000
_MAX_TOTAL_STRING_LENGTH = 1_000_000
_FREE_FORM_FIELDS = frozenset(
    {
        "device",
        "deviceName",
        "deviceModel",
        "device_name",
        "device_model",
        "displayName",
        "display_name",
        "label",
        "name",
        "originalSourceName",
        "original_source_name",
    }
)
_SYNTHETIC_FREE_FORM_VALUES = frozenset(
    {
        "Activity - Basic",
        "Heart - Basic",
        "Dispositivo sint\u00e9tico A",
        "Fuente sint\u00e9tica A",
        "Fuente sint\u00e9tica B",
        "Modelo sint\u00e9tico A",
        "device-demo-a",
    }
)
_OW_SYNTHETIC_NOTES = frozenset(
    {
        "Todos los valores, nombres e identificadores son sint\u00e9ticos.",
        "Los run_id de OW usan el namespace ow-run-demo-*; run_id de OW y runKey del BFF siguen siendo campos distintos y el primero es solo server-side.",
        "El fixture representa respuestas server-side de lectura y no autoriza a consultar ning\u00fan usuario.",
        "No incluye detalle extendido de workout ni datos geogr\u00e1ficos.",
        "La proyecci\u00f3n p\u00fablica de sync es responsabilidad del BFF y no afirma que OW ya sanitice sus respuestas.",
    }
)
_BFF_SYNTHETIC_NOTES = frozenset(
    {
        "Todas las respuestas son sint\u00e9ticas y est\u00e1n pensadas para un adapter local.",
        "Los runKey sint\u00e9ticos usan el namespace verify-demo-* y no representan cuentas reales; los run_id OW relacionados usan el namespace separado ow-run-demo-*.",
        "adapterMappings es metadata server-side del fixture y no forma parte de las respuestas que recibe el navegador.",
        "Las respuestas no incluyen mapas, rutas, datos raw ni identificadores internos de OW; adapterMappings s\u00f3lo contiene referencias OW sint\u00e9ticas para el adapter.",
        "Los campos message y error de este fixture son copy/codigos BFF_sanitized allowlisted; no son payloads raw de OW.",
    }
)
_TIMESTAMP_FIELDS = frozenset(
    {
        "asOf",
        "blood_pressure_measured_at",
        "bodyTemperatureMeasuredAt",
        "body_temperature_measured_at",
        "ended_at",
        "end_time",
        "endTime",
        "finishedAt",
        "lastUpdate",
        "lastObservedAt",
        "last_update",
        "period_end",
        "period_start",
        "requestedAt",
        "skinTemperatureMeasuredAt",
        "skin_temperature_measured_at",
        "start_time",
        "started_at",
        "startedAt",
        "startTime",
        "timestamp",
    }
)
_LOGICAL_DATE_FIELDS = frozenset({"date", "logicalDate"})
_TIMEZONE_FIELDS = frozenset({"timezone"})
_ZONE_OFFSET_FIELDS = frozenset({"zone_offset", "zoneOffset"})
_METRIC_KEY_FIELDS = frozenset({"metric", "type"})
_PROVIDER_KEY_FIELDS = frozenset({"provider"})
_BFF_INTEGER_METRIC_FIELDS = frozenset({"steps", "sleepDurationSeconds"})
_MATCH_EXPECTED_SCOPE = (
    ("timestamp", "2024-01-02T08:00:00Z"),
    ("zone_offset", "+00:00"),
    ("provider", "provider-demo"),
    ("source", "source-demo-a"),
)
_ADAPTER_ASSERTION_MAPPING = {
    **{
        (stage, status): "pending"
        for stage in ("queued", "started", "fetching", "processing", "saving")
        for status in (None, "in_progress", "accepted")
    },
    **{
        (stage, "failed"): "failed"
        for stage in (
            "queued",
            "started",
            "fetching",
            "processing",
            "saving",
            "completed",
            "failed",
            "cancelled",
        )
    },
    **{
        (stage, "cancelled"): "cancelled"
        for stage in (
            "queued",
            "started",
            "fetching",
            "processing",
            "saving",
            "completed",
            "failed",
            "cancelled",
        )
    },
    ("completed", "success"): "persisted",
    ("completed", "in_progress"): "inconclusive",
    ("completed", "partial"): "partial",
    ("completed", "failed"): "failed",
    ("completed", "cancelled"): "cancelled",
    ("failed", "failed"): "failed",
    ("failed", "success"): "failed",
    ("failed", "partial"): "failed",
    ("failed", "cancelled"): "failed",
    ("cancelled", "cancelled"): "cancelled",
    ("cancelled", "success"): "cancelled",
    ("cancelled", "partial"): "cancelled",
    ("completed", "skipped"): "skipped",
}
for _status in (
    None,
    "in_progress",
    "accepted",
    "success",
    "partial",
    "failed",
    "cancelled",
    "skipped",
):
    _ADAPTER_ASSERTION_MAPPING[("failed", _status)] = "failed"
    _ADAPTER_ASSERTION_MAPPING[("cancelled", _status)] = "cancelled"

_SYNTHETIC_SOFTWARE_VERSIONS = frozenset({"fixture-v1"})
_OW_REQUESTED_CAPABILITIES = frozenset({"extended_workout_detail"})
_SYNTHETIC_METRIC_KEYS = frozenset(
    {
        "steps",
        "heart_rate",
        "oxygen_saturation",
        "distance_walking",
        "distance",
        "sleep_stages",
        "recovery",
        "running",
        "extended_workout_detail",
    }
)
_SYNTHETIC_PROVIDER_PATTERN = re.compile(
    r"^(?:provider-demo|sdk-demo)(?:-[a-z0-9-]+)?$"
)
_OW_STAGE_VALUES = frozenset(
    {
        "queued",
        "started",
        "fetching",
        "processing",
        "saving",
        "completed",
        "failed",
        "cancelled",
        "unknown-demo-stage",
        "new-demo-stage",
    }
)
_OW_STATUS_VALUES = frozenset(
    {
        "in_progress",
        "accepted",
        "success",
        "partial",
        "failed",
        "cancelled",
        "skipped",
        "unknown-demo-status",
        "new-demo-status",
    }
)
_ADAPTER_UI_STATES = frozenset(
    {
        "pending",
        "persisted",
        "inconclusive",
        "partial",
        "failed",
        "cancelled",
        "skipped",
    }
)
_FIXTURE_CASE_NAMES = frozenset(_BFF_FIXTURE_CASE_BY_RESPONSE_CASE.values())
_OW_EXPECTED_RESULT_VALUES = frozenset(_OW_EXPECTED_RESULTS.values())
_KNOWN_STATE_VALUES = frozenset().union(
    _OW_SYNC_STATES,
    _BFF_DATA_STATES,
    _BFF_RUN_STATES,
    _BFF_SOURCE_STATES,
    _BFF_COVERAGE_STATES,
    _BFF_RESULT_STATES,
    {"inconclusive"},
)
_PUBLIC_STRING_ALLOWLISTS: dict[str, frozenset[str]] = {
    "software_version": _SYNTHETIC_SOFTWARE_VERSIONS,
    "softwareVersion": _SYNTHETIC_SOFTWARE_VERSIONS,
    "requested_capability": _OW_REQUESTED_CAPABILITIES,
    "owStage": _OW_STAGE_VALUES,
    "ow_stage": _OW_STAGE_VALUES,
    "owStatus": _OW_STATUS_VALUES,
    "ow_status": _OW_STATUS_VALUES,
    "ui_state": _ADAPTER_UI_STATES,
    "case": _FIXTURE_CASE_NAMES,
    "expected_result": _OW_EXPECTED_RESULT_VALUES,
    "expected_run_state": frozenset({"completed_with_findings"}),
    "reason_code": frozenset({"INCONSISTENT_TERMINAL_SIGNALS"}),
    "reasonCode": _BFF_RESULT_REASON_CODES,
    "implementation_status": frozenset({"pending"}),
    "owner": frozenset({"bff"}),
    "classification": frozenset({"BFF_sanitized"}),
    "upstream_payload": frozenset({"raw_not_public"}),
    "content_type": frozenset({"text/event-stream"}),
    "comment": frozenset({"connected", "heartbeat"}),
    "event": _ALLOWED_DOTTED_STRINGS,
    "accessState": frozenset({"active", "anonymous"}),
    "technicalState": frozenset({"ready"}),
    "severity": _BFF_WARNING_SEVERITIES,
    "domain": _BFF_WARNING_DOMAINS,
    "state": _KNOWN_STATE_VALUES,
    "stage": _OW_STAGE_VALUES | _SLEEP_STAGES,
    "status": _OW_STATUS_VALUES,
    "unit": _BFF_METRIC_UNITS,
    "type": _SYNTHETIC_METRIC_KEYS,
    "metric": _SYNTHETIC_METRIC_KEYS,
    "code": _WARNING_CODES | _ERROR_CODES | _SYNTHETIC_METRIC_KEYS,
    "device_type": _DEVICE_TYPES,
    "deviceType": _DEVICE_TYPES,
}
_PUBLIC_STRING_PATTERNS: dict[str, re.Pattern[str]] = {
    "provider": _SYNTHETIC_PROVIDER_PATTERN,
    "providers": _SYNTHETIC_PROVIDER_PATTERN,
}


def _fail() -> None:
    raise FixtureContractError("synthetic fixture contract rejected")


_VALIDATION_ERRORS = (
    TypeError,
    ValueError,
    KeyError,
    IndexError,
    AttributeError,
    RecursionError,
    OverflowError,
    MemoryError,
)


def _safe_validate(function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    try:
        function(*args, **kwargs)
    except FixtureContractError:
        raise
    except _VALIDATION_ERRORS:
        _fail()


def _scan_privacy(value: Any, *, bff: bool, ow_response: bool = False) -> None:
    _safe_validate(
        _check_keys_recursively,
        value,
        bff=bff,
        ow_response=ow_response,
    )


def _validate_privacy_first(
    value: Any,
    validator: Callable[..., Any],
    *validator_args: Any,
    bff: bool,
    ow_response: bool = False,
) -> None:
    """Scan selected content before applying its semantic validator."""

    _scan_privacy(value, bff=bff, ow_response=ow_response)
    _safe_validate(validator, *validator_args)


def _object(value: Any) -> JsonObject:
    if type(value) is not dict:
        _fail()
    return value


def _list(value: Any) -> list[Any]:
    if type(value) is not list:
        _fail()
    return value


def _string(value: Any) -> str:
    if type(value) is not str or not value or "\x00" in value:
        _fail()
    return value


def _optional_string(value: Any) -> None | str:
    if value is not None:
        return _string(value)
    return None


def _boolean(value: Any) -> bool:
    if type(value) is not bool:
        _fail()
    return value


def _number(value: Any, *, allow_none: bool = False) -> int | float | None:
    if value is None and allow_none:
        return None
    if type(value) not in (int, float) or type(value) is bool:
        _fail()
    if type(value) is float and not math.isfinite(value):
        _fail()
    return value


def _non_negative_number(value: Any, *, allow_none: bool = False) -> int | float | None:
    number = _number(value, allow_none=allow_none)
    if number is not None and number < 0:
        _fail()
    return number


def _percentage(value: Any, *, allow_none: bool = False) -> int | float | None:
    number = _number(value, allow_none=allow_none)
    if number is not None and not 0 <= number <= 100:
        _fail()
    return number


def _measurement(value: Any, unit: str, *, allow_none: bool = False) -> None:
    if unit == "count":
        _integer(value, allow_none=allow_none)
        return
    number = _number(value, allow_none=allow_none)
    if number is None:
        return
    if unit == "percent":
        _percentage(number)
    elif unit != "celsius" and number < 0:
        _fail()


def _integer(value: Any, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if type(value) is not int or type(value) is bool or value < 0:
        _fail()
    return value


def _bounded_integer(
    value: Any, lower: int, upper: int, *, allow_none: bool = False
) -> int | None:
    integer = _integer(value, allow_none=allow_none)
    if integer is not None and not lower <= integer <= upper:
        _fail()
    return integer


def _fraction(value: Any, *, allow_none: bool = False) -> float | int | None:
    number = _number(value, allow_none=allow_none)
    if number is not None and (number < 0 or number > 1):
        _fail()
    return number


def _sync_mapping(stage: Any, status: Any) -> str:
    stage = _allowlisted_string(stage, _OW_STAGE_VALUES)
    if status is not None:
        status = _allowlisted_string(status, _OW_STATUS_VALUES)
    return _ADAPTER_ASSERTION_MAPPING.get((stage, status), "inconclusive")


def _keys(value: JsonObject, required: set[str], allowed: set[str]) -> None:
    if not required.issubset(value) or not set(value).issubset(allowed):
        _fail()


def _guard_document(value: Any) -> None:
    """Bound and cycle-check caller-owned JSON before copying or walking it."""

    if type(value) is not dict:
        _fail()

    stack: list[tuple[Any, int, bool]] = [(value, 0, False)]
    active: set[int] = set()
    node_count = 0
    total_string_length = 0

    while stack:
        current, depth, exiting = stack.pop()
        if type(current) in (dict, list):
            identity = id(current)
            if exiting:
                active.remove(identity)
                continue
            if identity in active or depth > _MAX_DOCUMENT_DEPTH:
                _fail()
            active.add(identity)
            node_count += 1
            if node_count > _MAX_DOCUMENT_NODES:
                _fail()
            if len(current) > _MAX_CONTAINER_ITEMS:
                _fail()
            stack.append((current, depth, True))
            if type(current) is dict:
                items = list(current.items())
                for key, item in reversed(items):
                    if type(key) is not str:
                        _fail()
                    if len(key) > _MAX_STRING_LENGTH:
                        _fail()
                    total_string_length += len(key)
                    if total_string_length > _MAX_TOTAL_STRING_LENGTH:
                        _fail()
                    stack.append((item, depth + 1, False))
            else:
                for item in reversed(current):
                    stack.append((item, depth + 1, False))
            continue

        if current is None or type(current) is bool or type(current) is int:
            continue
        if type(current) is float:
            if not math.isfinite(current):
                _fail()
            continue
        if type(current) is str:
            if "\x00" in current or len(current) > _MAX_STRING_LENGTH:
                _fail()
            total_string_length += len(current)
            if total_string_length > _MAX_TOTAL_STRING_LENGTH:
                _fail()
            continue
        _fail()


def _all_json_values(value: Any) -> None:
    _guard_document(value)


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _is_internal_identifier_key(key: str) -> bool:
    normalized = _normalized_key(key)
    if normalized in {
        "id",
        "userid",
        "userconnectionid",
        "userconnection",
        "userconnectionkey",
        "connectionid",
        "connectionkey",
        "connectionuid",
        "sourceconnection",
        "providerconnection",
        "ownerid",
        "ownerkey",
        "subjectid",
        "identityid",
        "owuserid",
        "owuid",
        "owuserconnection",
        "owconnection",
        "owconnectionkey",
        "owconnectionid",
        "primaryuserid",
        "localuserid",
        "appuserid",
        "sourceid",
        "providerid",
        "deviceid",
        "runid",
        "owrunid",
        "batchid",
        "manifestid",
        "eventid",
        "workoutid",
        "sleepid",
        "seriesid",
        "metricid",
        "externalid",
        "uid",
        "useruid",
        "batchkey",
        "manifestkey",
        "sourcerunkey",
        "uuid",
        "identifier",
        "userkey",
        "owuserkey",
    }:
        return True
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).replace("-", "_")
    return any(
        word.casefold() in {"id", "identifier", "key", "uid", "uuid"}
        for word in words.split("_")
    )


def _percent_decoded_forms(value: str) -> tuple[str, ...]:
    forms = [value]
    for _ in range(_MAX_PERCENT_DECODE_ROUNDS):
        decoded = unquote(forms[-1])
        if decoded == forms[-1]:
            return tuple(forms)
        forms.append(decoded)
    if unquote(forms[-1]) != forms[-1]:
        _fail()
    return tuple(forms)


def _is_ipv6_host(value: str) -> bool:
    candidate = value
    if candidate.startswith("["):
        closing = candidate.find("]")
        if closing < 0:
            return False
        host = candidate[1:closing]
        suffix = candidate[closing + 1 :]
        if suffix and not re.fullmatch(r":\d{1,5}(?:[/?#].*)?", suffix):
            return False
    else:
        host = re.split(r"[/?#]", candidate, maxsplit=1)[0]
    try:
        return ipaddress.ip_address(host).version == 6
    except ValueError:
        return False


def _contains_ipv6_host(value: str) -> bool:
    return any(
        _is_ipv6_host(match.group(0)) for match in _IPV6_IN_TEXT_PATTERN.finditer(value)
    )


def _metric_key(value: Any) -> str:
    string = _string(value)
    if not _SAFE_METRIC_KEY_PATTERN.fullmatch(string):
        _fail()
    if string not in _SYNTHETIC_METRIC_KEYS:
        _fail()
    if _CREDENTIAL_TEXT_PATTERN.search(string):
        _fail()
    return string


def _expected_ow_timeseries_unit(metric_type: str) -> str | None:
    if metric_type.startswith("distance_"):
        return "meters"
    return _OW_TIMESERIES_UNIT_BY_TYPE.get(metric_type)


def _validate_ow_metric_unit(metric_type: str, unit: str) -> None:
    expected_unit = _expected_ow_timeseries_unit(metric_type)
    if expected_unit is not None and unit != expected_unit:
        _fail()


def _validate_bff_overview_unit(metric_name: str | None, unit: str | None) -> None:
    if metric_name not in _BFF_OVERVIEW_METRIC_UNITS:
        return
    if metric_name in _BFF_UNITLESS_VALUE_METRICS:
        if unit is not None:
            _fail()
        return
    if unit != _BFF_OVERVIEW_METRIC_UNITS[metric_name]:
        _fail()


def _provider_key(value: Any) -> str:
    string = _string(value)
    if not (
        _SAFE_PROVIDER_KEY_PATTERN.fullmatch(string)
        and _SYNTHETIC_PROVIDER_PATTERN.fullmatch(string)
    ):
        _fail()
    if _CREDENTIAL_TEXT_PATTERN.search(string):
        _fail()
    return string


def _allowlisted_string(value: Any, allowed: frozenset[str]) -> str:
    string = _string(value)
    if string not in allowed:
        _fail()
    return string


def _zone_offset(value: Any, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if type(value) is not str or not _ZONE_OFFSET_PATTERN.fullmatch(value):
        _fail()


def _check_public_string(
    value: str,
    *,
    bff: bool = False,
    field: str | None = None,
    reject_internal: bool = False,
    check_reserved: bool = True,
) -> None:
    if type(value) is not str:
        _fail()
    if field in _FREE_FORM_FIELDS and value not in _SYNTHETIC_FREE_FORM_VALUES:
        _fail()
    allowlisted_free_form = (
        field in _FREE_FORM_FIELDS and value in _SYNTHETIC_FREE_FORM_VALUES
    )
    allowlisted_note = field is None and value in (
        _BFF_SYNTHETIC_NOTES if bff else _OW_SYNTHETIC_NOTES
    )
    allowed_identifier_fields = (
        _BFF_ALLOWED_IDENTIFIER_FIELDS if bff else _OW_ALLOWED_IDENTIFIER_FIELDS
    )

    if check_reserved and not allowlisted_free_form and not allowlisted_note:
        for candidate in _percent_decoded_forms(value):
            if (
                "\x00" in candidate
                or _CREDENTIAL_TEXT_PATTERN.search(candidate)
                or _EMAIL_PATTERN.fullmatch(candidate)
                or _EMAIL_LIKE_PATTERN.search(candidate)
                or _SCHEME_IN_TEXT_PATTERN.search(candidate)
                or _KNOWN_SCHEME_IN_TEXT_PATTERN.search(candidate)
                or _URL_PATTERN.search(candidate)
                or "//" in candidate
                or (
                    candidate not in _ALLOWED_DOTTED_STRINGS
                    and (
                        _HOST_PATTERN.fullmatch(candidate)
                        or _HOST_WITH_PORT_PATTERN.fullmatch(candidate)
                        or _HOST_IN_TEXT_PATTERN.search(candidate)
                        or _is_ipv6_host(candidate)
                        or _contains_ipv6_host(candidate)
                    )
                )
                or _UUID_PATTERN.search(candidate)
                or _HEX_UUID_PATTERN.search(candidate)
                or _MAC_PATTERN.search(candidate)
                or _COORDINATE_PAIR_PATTERN.search(candidate)
                or _RAW_UPSTREAM_STRING_PATTERN.search(candidate)
                or _WINDOWS_PATH_IN_TEXT_PATTERN.search(candidate)
                or (
                    (reject_internal or field not in allowed_identifier_fields)
                    and (
                        _INTERNAL_IDENTIFIER_TEXT_PATTERN.search(candidate)
                        or _INTERNAL_IDENTIFIER_VALUE_PATTERN.search(candidate)
                    )
                )
                or candidate.startswith(("/", "\\", "~"))
                or _WINDOWS_ABSOLUTE_PATH_PATTERN.match(candidate)
                or _ABSOLUTE_PATH_IN_TEXT_PATTERN.search(candidate)
                or any(part == ".." for part in re.split(r"[\\/]", candidate))
            ):
                _fail()

    allowed_values = _PUBLIC_STRING_ALLOWLISTS.get(field or "")
    if allowed_values is not None and value not in allowed_values:
        _fail()
    pattern = _PUBLIC_STRING_PATTERNS.get(field or "")
    if pattern is not None and not pattern.fullmatch(value):
        _fail()

    if field in _TIMESTAMP_FIELDS:
        _rfc3339(value)
        return
    if field in _LOGICAL_DATE_FIELDS:
        _logical_date(value)
        return
    if field in _TIMEZONE_FIELDS:
        _timezone(value)
        return
    if field in _ZONE_OFFSET_FIELDS:
        _zone_offset(value)
        return
    if field in _METRIC_KEY_FIELDS:
        _metric_key(value)
        return
    if field in _PROVIDER_KEY_FIELDS:
        _provider_key(value)
        return
    if field == "code" and value not in _WARNING_CODES | _ERROR_CODES:
        _metric_key(value)
        return
    if field == "event" and value in _ALLOWED_DOTTED_STRINGS:
        return


def _check_keys_recursively(
    value: Any, *, bff: bool, ow_response: bool = False
) -> None:
    guard_root = value if type(value) is dict else {"value": value}
    _guard_document(guard_root)
    stack: list[tuple[Any, str | None]] = [(value, None)]

    while stack:
        current, parent_field = stack.pop()
        if type(current) is str:
            _check_public_string(
                current,
                bff=bff,
                field=parent_field,
                reject_internal=parent_field in _FREE_FORM_FIELDS,
            )
            continue
        if type(current) is list:
            for item in reversed(current):
                stack.append((item, parent_field))
            continue
        if type(current) is not dict:
            continue
        for key, item in reversed(list(current.items())):
            if type(key) is not str:
                _fail()
            _check_public_string(key, check_reserved=False)
            normalized_key = _normalized_key(key)
            if normalized_key in _FORBIDDEN_RAW_KEYS:
                _fail()
            if ow_response and normalized_key in _OW_RAW_KEYS:
                _fail()
            if bff and normalized_key in _FORBIDDEN_BFF_KEYS:
                _fail()
            if bff:
                if (
                    _is_internal_identifier_key(key)
                    and key not in _BFF_ALLOWED_IDENTIFIER_FIELDS
                ):
                    _fail()
            elif (
                _is_internal_identifier_key(key)
                and key not in _OW_ALLOWED_IDENTIFIER_FIELDS
            ):
                _fail()
            if key in _NULL_ONLY_IDENTIFIER_FIELDS and item is not None:
                _fail()
            if bff and key in {"message", "error"}:
                if key == "message" and type(item) is not str:
                    _fail()
                if key == "error" and type(item) is not dict:
                    _fail()
            if type(item) is str:
                pattern = _DEMO_ID_PATTERNS_BY_NORMALIZED_KEY.get(normalized_key)
                if pattern is not None and not pattern.fullmatch(item):
                    _fail()
                _check_public_string(
                    item,
                    bff=bff,
                    field=key,
                    reject_internal=key in _FREE_FORM_FIELDS,
                )
            else:
                stack.append((item, key))


def _rfc3339(value: Any, *, allow_none: bool = False) -> None:
    _rfc3339_datetime(value, allow_none=allow_none)


def _rfc3339_datetime(value: Any, *, allow_none: bool = False) -> datetime | None:
    if value is None and allow_none:
        return None
    if type(value) is not str or not _RFC3339_PATTERN.fullmatch(value):
        _fail()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail()
    if parsed.tzinfo is None:
        _fail()
    return parsed


def _ordered_interval(start: Any, end: Any) -> None:
    start_value = _rfc3339_datetime(start)
    end_value = _rfc3339_datetime(end)
    if start_value >= end_value:
        _fail()


def _ordered_optional_timestamps(
    start: Any, end: Any, *, last: Any | None = None
) -> None:
    start_value = _rfc3339_datetime(start, allow_none=True)
    end_value = _rfc3339_datetime(end, allow_none=True)
    last_value = _rfc3339_datetime(last, allow_none=True) if last is not None else None
    if start_value is not None and end_value is not None and start_value > end_value:
        _fail()
    if end_value is not None and last_value is not None and end_value > last_value:
        _fail()
    if start_value is not None and last_value is not None and start_value > last_value:
        _fail()


def _expected_window(logical_date: str, timezone: str) -> tuple[str, str]:
    local_date = date.fromisoformat(logical_date)
    zone = ZoneInfo(timezone)
    start = datetime.combine(local_date, time.min, tzinfo=zone)
    end = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=zone)
    return (
        start.astimezone(dt_timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        end.astimezone(dt_timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    )


def _requested_window(value: Any) -> None:
    requested = _object(value)
    fields = {"logicalDate", "from", "to", "timezone"}
    _keys(requested, fields, fields)
    _logical_date(requested["logicalDate"])
    _timezone(requested["timezone"])
    _rfc3339(requested["from"])
    _rfc3339(requested["to"])
    if _rfc3339_datetime(requested["from"]) >= _rfc3339_datetime(requested["to"]):
        _fail()
    expected_from, expected_to = _expected_window(
        requested["logicalDate"], requested["timezone"]
    )
    if requested["from"] != expected_from or requested["to"] != expected_to:
        _fail()


def _logical_date(value: Any) -> None:
    if type(value) is not str or not _DATE_PATTERN.fullmatch(value):
        _fail()
    try:
        date.fromisoformat(value)
    except ValueError:
        _fail()


def _timezone(value: Any) -> str:
    timezone = _string(value)
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        _fail()
    return timezone


def _source(value: Any, *, required: set[str] | None = None) -> None:
    source = _object(value)
    allowed = {
        "provider",
        "source",
        "device",
        "device_type",
        "device_name",
        "device_model",
        "software_version",
        "original_source_name",
        "display_name",
    }
    _keys(source, required or {"provider", "source", "device_type"}, allowed)
    _provider_key(source["provider"])
    source_key = _string(source["source"])
    if not _DEMO_ID_PATTERNS["source"].fullmatch(source_key):
        _fail()
    device_type = _string(source["device_type"])
    if device_type not in _DEVICE_TYPES:
        _fail()
    for field in allowed - {"provider", "source", "device_type"}:
        if field in source:
            if field == "software_version" and source[field] is not None:
                _allowlisted_string(source[field], _SYNTHETIC_SOFTWARE_VERSIONS)
            else:
                _optional_string(source[field])


def _pagination(value: Any, *, cursor_prefix: str = "ow-cursor-demo-") -> None:
    pagination = _object(value)
    allowed = {"next_cursor", "previous_cursor", "has_more", "total_count"}
    _keys(pagination, allowed, allowed)
    cursor_pattern = (
        _OW_CURSOR_PATTERN
        if cursor_prefix == "ow-cursor-demo-"
        else re.compile(r"^" + re.escape(cursor_prefix) + r"[a-z0-9-]+$")
    )
    for field in ("next_cursor", "previous_cursor"):
        cursor = pagination[field]
        if cursor is not None and (
            type(cursor) is not str or not cursor_pattern.fullmatch(cursor)
        ):
            _fail()
    _boolean(pagination["has_more"])
    if pagination["has_more"] is False and pagination["next_cursor"] is not None:
        _fail()
    if pagination["has_more"] is True and pagination["next_cursor"] is None:
        _fail()
    _integer(pagination["total_count"], allow_none=True)


def _paginated(value: Any, item_validator: Callable[[Any], None]) -> None:
    response = _object(value)
    _keys(response, {"data", "pagination"}, {"data", "pagination"})
    items = _list(response["data"])
    for item in items:
        item_validator(item)
    _pagination(response["pagination"])


def _timeseries_sample(value: Any) -> None:
    sample = _object(value)
    allowed = {
        "timestamp",
        "zone_offset",
        "type",
        "value",
        "unit",
        "source",
        "is_daily_total",
    }
    _keys(sample, allowed, allowed)
    _rfc3339(sample["timestamp"])
    _zone_offset(sample["zone_offset"], allow_none=True)
    metric_type = _metric_key(sample["type"])
    unit = _string(sample["unit"])
    if unit not in _BFF_METRIC_UNITS:
        _fail()
    _validate_ow_metric_unit(metric_type, unit)
    _measurement(sample["value"], unit, allow_none=True)
    _source(sample["source"])
    if sample["is_daily_total"] is not None:
        _boolean(sample["is_daily_total"])


def _activity_summary(value: Any) -> None:
    item = _object(value)
    allowed = {
        "date",
        "source",
        "steps",
        "distance_meters",
        "floors_climbed",
        "elevation_meters",
        "active_calories_kcal",
        "total_calories_kcal",
        "active_minutes",
        "sedentary_minutes",
        "intensity_minutes",
        "heart_rate",
    }
    _keys(item, allowed, allowed)
    _logical_date(item["date"])
    _source(item["source"])
    for field in ("steps", "floors_climbed", "active_minutes", "sedentary_minutes"):
        _integer(item[field], allow_none=True)
    for field in (
        "distance_meters",
        "elevation_meters",
        "active_calories_kcal",
        "total_calories_kcal",
    ):
        _non_negative_number(item[field], allow_none=True)
    intensity = _object(item["intensity_minutes"])
    _keys(
        intensity, {"light", "moderate", "vigorous"}, {"light", "moderate", "vigorous"}
    )
    for level in intensity.values():
        _integer(level, allow_none=True)
    heart_rate = _object(item["heart_rate"])
    _keys(
        heart_rate, {"avg_bpm", "max_bpm", "min_bpm"}, {"avg_bpm", "max_bpm", "min_bpm"}
    )
    for heart_rate_value in heart_rate.values():
        _non_negative_number(heart_rate_value, allow_none=True)


def _sleep_stages(value: Any) -> None:
    stages = _object(value)
    fields = {"awake_minutes", "light_minutes", "deep_minutes", "rem_minutes"}
    _keys(stages, fields, fields)
    for item in stages.values():
        _integer(item, allow_none=True)


def _sleep_summary(value: Any) -> None:
    item = _object(value)
    fields = {
        "date",
        "source",
        "start_time",
        "end_time",
        "duration_minutes",
        "total_duration_minutes",
        "time_in_bed_minutes",
        "efficiency_percent",
        "stages",
        "sessions",
        "nap_count",
        "nap_duration_minutes",
        "avg_heart_rate_bpm",
        "avg_hrv_sdnn_ms",
        "avg_hrv_rmssd_ms",
        "avg_respiratory_rate",
        "avg_spo2_percent",
    }
    _keys(item, fields, fields)
    _logical_date(item["date"])
    _source(item["source"])
    _rfc3339(item["start_time"], allow_none=True)
    _rfc3339(item["end_time"], allow_none=True)
    if item["start_time"] is not None and item["end_time"] is not None:
        _ordered_interval(item["start_time"], item["end_time"])
    for field in (
        "duration_minutes",
        "total_duration_minutes",
        "time_in_bed_minutes",
        "nap_count",
        "nap_duration_minutes",
    ):
        _integer(item[field], allow_none=True)
    for field in (
        "avg_heart_rate_bpm",
        "avg_hrv_sdnn_ms",
        "avg_hrv_rmssd_ms",
        "avg_respiratory_rate",
    ):
        _non_negative_number(item[field], allow_none=True)
    _percentage(item["efficiency_percent"], allow_none=True)
    _percentage(item["avg_spo2_percent"], allow_none=True)
    _sleep_stages(item["stages"])
    sessions = item["sessions"]
    if sessions is not None:
        _fail()


def _sleep_event(value: Any) -> None:
    item = _object(value)
    fields = {
        "id",
        "date",
        "start_time",
        "end_time",
        "duration_seconds",
        "sleep_duration_seconds",
        "is_nap",
        "source",
        "sleep_stage_intervals",
    }
    _keys(item, fields, fields)
    _string(item["id"])
    _logical_date(item["date"])
    _rfc3339(item["start_time"])
    _rfc3339(item["end_time"])
    _ordered_interval(item["start_time"], item["end_time"])
    duration = _integer(item["duration_seconds"], allow_none=True)
    sleep_duration = _integer(item["sleep_duration_seconds"], allow_none=True)
    if (
        duration is not None
        and sleep_duration is not None
        and sleep_duration > duration
    ):
        _fail()
    _boolean(item["is_nap"])
    _source(item["source"])
    intervals = _list(item["sleep_stage_intervals"])
    for interval in intervals:
        interval_object = _object(interval)
        interval_fields = {"start_time", "end_time", "stage"}
        _keys(interval_object, interval_fields, interval_fields)
        _rfc3339(interval_object["start_time"])
        _rfc3339(interval_object["end_time"])
        _ordered_interval(interval_object["start_time"], interval_object["end_time"])
        if interval_object["stage"] not in _SLEEP_STAGES:
            _fail()
        _string(interval_object["stage"])


def _recovery_summary(value: Any) -> None:
    item = _object(value)
    fields = {
        "date",
        "source",
        "sleep_duration_seconds",
        "sleep_efficiency_percent",
        "resting_heart_rate_bpm",
        "avg_hrv_sdnn_ms",
        "avg_spo2_percent",
        "recovery_score",
    }
    _keys(item, fields, fields)
    _logical_date(item["date"])
    _source(item["source"])
    _integer(item["sleep_duration_seconds"], allow_none=True)
    _percentage(item["sleep_efficiency_percent"], allow_none=True)
    _non_negative_number(item["resting_heart_rate_bpm"], allow_none=True)
    _non_negative_number(item["avg_hrv_sdnn_ms"], allow_none=True)
    _percentage(item["avg_spo2_percent"], allow_none=True)
    _bounded_integer(item["recovery_score"], 0, 100, allow_none=True)


def _summary_inventory(value: Any) -> None:
    inventory = _object(value)
    fields = {
        "total_data_points",
        "total_workouts",
        "total_sleep_events",
        "series_type_counts",
        "workout_type_counts",
        "by_provider",
        "data_points",
        "series_counts",
        "workout_count",
        "sleep_count",
        "has_womens_health_data",
    }
    _keys(inventory, fields, fields)
    for field in (
        "total_data_points",
        "total_workouts",
        "total_sleep_events",
        "data_points",
        "workout_count",
        "sleep_count",
    ):
        _integer(inventory[field])
    for field in ("series_type_counts", "workout_type_counts", "series_counts"):
        counts = _object(inventory[field])
        for key, count in counts.items():
            _metric_key(key)
            _integer(count)
    by_provider = _object(inventory["by_provider"])
    for provider, counts_value in by_provider.items():
        _provider_key(provider)
        if not (provider == "provider-demo" or provider.startswith("provider-demo-")):
            _fail()
        counts = _object(counts_value)
        _keys(
            counts,
            {"data_points", "workout_count", "sleep_count"},
            {"data_points", "workout_count", "sleep_count"},
        )
        for count in counts.values():
            _integer(count)
    _boolean(inventory["has_womens_health_data"])


def _body_summary(value: Any) -> None:
    body = _object(value)
    _keys(
        body,
        {"request", "slow_changing", "averaged", "latest"},
        {"request", "slow_changing", "averaged", "latest"},
    )
    request = _object(body["request"])
    _keys(
        request,
        {"average_period", "latest_window_hours"},
        {"average_period", "latest_window_hours"},
    )
    average_period = _integer(request["average_period"])
    latest_window_hours = _integer(request["latest_window_hours"])
    if not 1 <= average_period <= 7 or not 1 <= latest_window_hours <= 24:
        _fail()
    slow = _object(body["slow_changing"])
    slow_fields = {
        "weight_kg",
        "height_cm",
        "body_fat_percent",
        "muscle_mass_kg",
        "bmi",
        "age",
    }
    _keys(slow, slow_fields, slow_fields)
    _non_negative_number(slow["weight_kg"], allow_none=True)
    _non_negative_number(slow["height_cm"], allow_none=True)
    _percentage(slow["body_fat_percent"], allow_none=True)
    _non_negative_number(slow["muscle_mass_kg"], allow_none=True)
    _non_negative_number(slow["bmi"], allow_none=True)
    _non_negative_number(slow["age"], allow_none=True)
    averaged = _object(body["averaged"])
    averaged_fields = {
        "period_days",
        "resting_heart_rate_bpm",
        "avg_hrv_sdnn_ms",
        "avg_hrv_rmssd_ms",
        "period_start",
        "period_end",
    }
    _keys(averaged, averaged_fields, averaged_fields)
    _integer(averaged["period_days"])
    if averaged["period_days"] < 1:
        _fail()
    for field in ("resting_heart_rate_bpm", "avg_hrv_sdnn_ms", "avg_hrv_rmssd_ms"):
        _non_negative_number(averaged[field], allow_none=True)
    _rfc3339(averaged["period_start"])
    _rfc3339(averaged["period_end"])
    _ordered_interval(averaged["period_start"], averaged["period_end"])
    latest = _object(body["latest"])
    latest_fields = {
        "body_temperature_celsius",
        "body_temperature_measured_at",
        "skin_temperature_celsius",
        "skin_temperature_measured_at",
        "blood_pressure",
        "blood_pressure_measured_at",
    }
    _keys(latest, latest_fields, latest_fields)
    for field in ("body_temperature_celsius", "skin_temperature_celsius"):
        _number(latest[field], allow_none=True)
    for field in (
        "body_temperature_measured_at",
        "skin_temperature_measured_at",
        "blood_pressure_measured_at",
    ):
        _rfc3339(latest[field], allow_none=True)
    if latest["blood_pressure"] is not None:
        blood_pressure = _object(latest["blood_pressure"])
        blood_pressure_fields = {"systolic_mmhg", "diastolic_mmhg", "reading_count"}
        _keys(blood_pressure, blood_pressure_fields, blood_pressure_fields)
        _non_negative_number(blood_pressure["systolic_mmhg"], allow_none=True)
        _non_negative_number(blood_pressure["diastolic_mmhg"], allow_none=True)
        _integer(blood_pressure["reading_count"])


def _workout(value: Any) -> None:
    item = _object(value)
    fields = {
        "id",
        "type",
        "name",
        "start_time",
        "end_time",
        "duration_seconds",
        "zone_offset",
        "source",
        "calories_kcal",
        "distance_meters",
        "avg_heart_rate_bpm",
        "max_heart_rate_bpm",
        "avg_pace_sec_per_km",
        "elevation_gain_meters",
    }
    _keys(item, fields, fields)
    _string(item["id"])
    _metric_key(item["type"])
    _optional_string(item["name"])
    _rfc3339(item["start_time"])
    _rfc3339(item["end_time"])
    _ordered_interval(item["start_time"], item["end_time"])
    _integer(item["duration_seconds"], allow_none=True)
    _zone_offset(item["zone_offset"], allow_none=True)
    _source(item["source"])
    for field in (
        "calories_kcal",
        "distance_meters",
        "avg_heart_rate_bpm",
        "max_heart_rate_bpm",
        "avg_pace_sec_per_km",
        "elevation_gain_meters",
    ):
        _non_negative_number(item[field], allow_none=True)


def _sync_run(value: Any) -> None:
    item = _object(value)
    fields = {
        "run_id",
        "user_id",
        "provider",
        "source",
        "state",
        "progress",
        "items_processed",
        "items_total",
        "warning_codes",
        "counts",
        "started_at",
        "ended_at",
        "last_update",
    }
    _keys(item, fields, fields)
    _string(item["run_id"])
    _string(item["user_id"])
    _provider_key(item["provider"])
    source = _string(item["source"])
    if not _DEMO_ID_PATTERNS["source"].fullmatch(source):
        _fail()
    state = _string(item["state"])
    if state not in _OW_SYNC_STATES:
        _fail()
    _fraction(item["progress"], allow_none=True)
    _integer(item["items_processed"], allow_none=True)
    _integer(item["items_total"], allow_none=True)
    warning_codes = _list(item["warning_codes"])
    for code in warning_codes:
        if type(code) is not str or code not in _WARNING_CODES:
            _fail()
    counts = _object(item["counts"])
    _keys(
        counts,
        {"records_saved", "records_rejected"},
        {"records_saved", "records_rejected"},
    )
    _integer(counts["records_saved"], allow_none=True)
    _integer(counts["records_rejected"], allow_none=True)
    _rfc3339(item["started_at"], allow_none=True)
    _rfc3339(item["ended_at"], allow_none=True)
    _rfc3339(item["last_update"])
    if item["ended_at"] is not None and item["started_at"] is None:
        _fail()
    _ordered_optional_timestamps(
        item["started_at"], item["ended_at"], last=item["last_update"]
    )


def _sync_event(value: Any) -> None:
    item = _object(value)
    fields = {
        "event_id",
        "run_id",
        "user_id",
        "provider",
        "source",
        "state",
        "progress",
        "items_processed",
        "items_total",
        "warning_codes",
        "counts",
        "started_at",
        "ended_at",
        "timestamp",
    }
    _keys(item, fields, fields)
    _string(item["event_id"])
    _sync_run(
        {
            field: item[field]
            for field in (
                "run_id",
                "user_id",
                "provider",
                "source",
                "state",
                "progress",
                "items_processed",
                "items_total",
                "warning_codes",
                "counts",
                "started_at",
                "ended_at",
            )
        }
        | {"last_update": item["timestamp"]}
    )
    _rfc3339(item["timestamp"])


def _sync_stream(value: Any) -> None:
    stream = _object(value)
    fields = {"content_type", "replay", "frames"}
    _keys(stream, fields, fields)
    if stream["content_type"] != "text/event-stream":
        _fail()
    _string(stream["content_type"])
    _bounded_integer(stream["replay"], 1, 200)
    frames = _list(stream["frames"])
    for frame_value in frames:
        frame = _object(frame_value)
        if "comment" in frame:
            _keys(frame, {"comment"}, {"comment"})
            if frame["comment"] not in {"connected", "heartbeat"}:
                _fail()
            _string(frame["comment"])
        elif "event" in frame:
            _keys(frame, {"event", "data"}, {"event", "data"})
            if frame["event"] not in _ALLOWED_DOTTED_STRINGS:
                _fail()
            _string(frame["event"])
            data = _object(frame["data"])
            fields = {"run_id", "state", "progress", "warning_codes", "timestamp"}
            _keys(data, fields, fields)
            _string(data["run_id"])
            state = _string(data["state"])
            if state not in _OW_SYNC_STATES:
                _fail()
            _fraction(data["progress"], allow_none=True)
            warning_codes = _list(data["warning_codes"])
            for code in warning_codes:
                if type(code) is not str or code not in _WARNING_CODES:
                    _fail()
            _rfc3339(data["timestamp"])
        else:
            _fail()


def _validate_data_sources(value: Any) -> None:
    response = _object(value)
    _keys(response, {"items", "total"}, {"items", "total"})
    _integer(response["total"])
    for item in _list(response["items"]):
        source = _object(item)
        fields = {
            "id",
            "user_id",
            "provider",
            "user_connection_id",
            "device_model",
            "software_version",
            "source",
            "device_type",
            "original_source_name",
            "display_name",
        }
        _keys(source, fields, fields)
        source_id = _string(source["id"])
        if not _DEMO_ID_PATTERNS["id"].fullmatch(source_id):
            _fail()
        user_id = _string(source["user_id"])
        if not _DEMO_ID_PATTERNS["user_id"].fullmatch(user_id):
            _fail()
        _provider_key(source["provider"])
        if source["user_connection_id"] is not None:
            _fail()
        source_key = _string(source["source"])
        if not _DEMO_ID_PATTERNS["source"].fullmatch(source_key):
            _fail()
        device_type = _string(source["device_type"])
        if device_type not in _DEVICE_TYPES:
            _fail()
        for field in fields - {"id", "user_id", "provider", "user_connection_id"}:
            if field == "software_version" and source[field] is not None:
                _allowlisted_string(source[field], _SYNTHETIC_SOFTWARE_VERSIONS)
            else:
                _optional_string(source[field])


def _validate_coverage(value: Any) -> None:
    coverage = _object(value)
    fields = {
        "providers",
        "timeseries",
        "workout_fields",
        "sleep_fields",
        "health_scores",
    }
    _keys(coverage, fields, fields)
    for provider in _list(coverage["providers"]):
        _provider_key(provider)
    for group_value in _list(coverage["timeseries"]):
        group = _object(group_value)
        _keys(group, {"name", "metrics"}, {"name", "metrics"})
        _string(group["name"])
        for metric_value in _list(group["metrics"]):
            metric = _object(metric_value)
            _keys(metric, {"code", "unit", "providers"}, {"code", "unit", "providers"})
            metric_type = _metric_key(metric["code"])
            unit = _string(metric["unit"])
            if unit not in _BFF_METRIC_UNITS:
                _fail()
            _validate_ow_metric_unit(metric_type, unit)
            for provider in _list(metric["providers"]):
                _provider_key(provider)
    for field_name in ("workout_fields", "sleep_fields", "health_scores"):
        for field_value in _list(coverage[field_name]):
            field = _object(field_value)
            _keys(field, {"code", "providers"}, {"code", "providers"})
            _metric_key(field["code"])
            for provider in _list(field["providers"]):
                _provider_key(provider)


def _validate_ow_response(case: str, value: Any) -> None:
    validators: dict[str, Callable[[Any], None]] = {
        "data_sources": _validate_data_sources,
        "coverage": _validate_coverage,
        "timeseries_match": lambda item: _paginated(item, _timeseries_sample),
        "timeseries_value_null": lambda item: _paginated(item, _timeseries_sample),
        "timeseries_is_daily_total_null": lambda item: _paginated(
            item, _timeseries_sample
        ),
        "activity_summary": lambda item: _paginated(item, _activity_summary),
        "sleep_summary": lambda item: _paginated(item, _sleep_summary),
        "events_sleep": lambda item: _paginated(item, _sleep_event),
        "recovery_summary": lambda item: _paginated(item, _recovery_summary),
        "summaries_data": _summary_inventory,
        "body_summary_relative_now": _body_summary,
        "workouts_aggregate": lambda item: _paginated(item, _workout),
        "sync_runs_terminal": _validate_terminal_sync_array,
        "sync_recent": lambda item: _validate_sync_array(item, _sync_event),
        "sync_stream": _sync_stream,
    }
    validator = validators.get(case)
    if validator is None:
        _fail()
    _safe_validate(validator, value)


def _validate_sync_array(value: Any, item_validator: Callable[[Any], None]) -> None:
    for item in _list(value):
        item_validator(item)


def _validate_terminal_sync_array(value: Any) -> None:
    runs = _list(value)
    if len(runs) != 1:
        _fail()
    _sync_run(runs[0])
    run = _object(runs[0])
    counts = _object(run["counts"])
    if (
        run["state"] != "completed"
        or run["progress"] != 1
        or run["items_processed"] is None
        or run["items_total"] is None
        or run["items_processed"] != run["items_total"]
        or counts["records_saved"] is None
        or counts["records_rejected"] is None
        or run["started_at"] != "2024-01-02T08:31:00Z"
        or run["ended_at"] != "2024-01-02T08:31:04Z"
        or run["last_update"] != "2024-01-02T08:31:04Z"
    ):
        _fail()


def _metric_assertion(value: Any) -> None:
    metric = _object(value)
    fields = {"type", "value", "unit", "is_daily_total"}
    _keys(metric, fields, fields)
    metric_type = _metric_key(metric["type"])
    unit = _string(metric["unit"])
    if unit not in _BFF_METRIC_UNITS:
        _fail()
    _validate_ow_metric_unit(metric_type, unit)
    _measurement(metric["value"], unit)
    _boolean(metric["is_daily_total"])


def _resolve_observed_ref(reference: Any, document: JsonObject) -> Any:
    reference = _string(reference)
    parts = reference.split(".")
    if not parts or parts[0] != "responses":
        _fail()
    current: Any = document
    for part in parts:
        match = re.fullmatch(r"([a-z][a-z0-9_]*)(?:\[(\d+)\])?", part)
        if match is None:
            _fail()
        key, index = match.groups()
        if type(current) is not dict or key not in current:
            _fail()
        current = current[key]
        if index is not None:
            if type(current) is not list:
                _fail()
            position = int(index)
            if position >= len(current):
                _fail()
            current = current[position]
    return current


def _scan_ow_case_observed_reference(
    assertion: JsonObject, responses: JsonObject
) -> None:
    if "observed_ref" not in assertion:
        return
    observed = _resolve_observed_ref(
        assertion["observed_ref"], {"responses": responses}
    )
    _scan_privacy(observed, bff=False, ow_response=True)


def _validate_ow_case(
    case: str, value: Any, responses: JsonObject | None = None
) -> None:
    assertion = _object(value)
    if case == "match":
        _keys(
            assertion,
            {"run_id", "expected", "observed_ref", "expected_result"},
            {"run_id", "expected", "observed_ref", "expected_result"},
        )
        _string(assertion["run_id"])
        _metric_assertion(assertion["expected"])
        _string(assertion["observed_ref"])
        _string(assertion["expected_result"])
        if responses is None:
            _fail()
        observed = _object(
            _resolve_observed_ref(assertion["observed_ref"], {"responses": responses})
        )
        expected = _object(assertion["expected"])
        for field in ("type", "value", "unit", "is_daily_total"):
            if observed.get(field) != expected[field]:
                _fail()
        for field, expected_value in _MATCH_EXPECTED_SCOPE[:2]:
            if observed.get(field) != expected_value:
                _fail()
        observed_source = _object(observed["source"])
        for field, expected_value in _MATCH_EXPECTED_SCOPE[2:]:
            if observed_source.get(field) != expected_value:
                _fail()
    elif case in {
        "summaries_data",
        "events_sleep",
        "sync_stream",
        "value_null",
        "is_daily_total_null",
    }:
        _keys(
            assertion,
            {"observed_ref", "expected_result"},
            {"observed_ref", "expected_result"},
        )
        _string(assertion["observed_ref"])
        _string(assertion["expected_result"])
        observed = _resolve_observed_ref(
            assertion["observed_ref"], {"responses": responses}
        )
        if case == "summaries_data":
            _summary_inventory(observed)
        elif case == "events_sleep":
            _sleep_event(observed)
        elif case == "sync_stream":
            _sync_stream(observed)
        elif case in {"value_null", "is_daily_total_null"}:
            _timeseries_sample(observed)
            if case == "value_null" and _object(observed)["value"] is not None:
                _fail()
            if (
                case == "is_daily_total_null"
                and _object(observed)["is_daily_total"] is not None
            ):
                _fail()
    elif case in {"empty", "zero", "partial"}:
        _keys(
            assertion, {"response", "expected_result"}, {"response", "expected_result"}
        )
        if case == "empty" or case == "zero":
            _paginated(assertion["response"], _timeseries_sample)
        else:
            response = _object(assertion["response"])
            _keys(response, {"data", "pagination"}, {"data", "pagination"})
            _pagination(response["pagination"])
            for item_value in _list(response["data"]):
                item = _object(item_value)
                _keys(
                    item,
                    {"date", "source", "steps", "distance_meters"},
                    {"date", "source", "steps", "distance_meters"},
                )
                _logical_date(item["date"])
                _source(item["source"])
                _integer(item["steps"], allow_none=True)
                _non_negative_number(item["distance_meters"], allow_none=True)
        _string(assertion["expected_result"])
    elif case == "null":
        _keys(
            assertion, {"response", "expected_result"}, {"response", "expected_result"}
        )
        response = _object(assertion["response"])
        _keys(response, {"body_summary", "recovery"}, {"body_summary", "recovery"})
        if response["body_summary"] is not None:
            _body_summary(response["body_summary"])
        recovery = _object(response["recovery"])
        _keys(
            recovery,
            {"recovery_score", "resting_heart_rate_bpm"},
            {"recovery_score", "resting_heart_rate_bpm"},
        )
        _bounded_integer(recovery["recovery_score"], 0, 100, allow_none=True)
        _non_negative_number(recovery["resting_heart_rate_bpm"], allow_none=True)
        _string(assertion["expected_result"])
    elif case == "unsupported":
        _keys(
            assertion,
            {"requested_capability", "public_read_available", "expected_result"},
            {"requested_capability", "public_read_available", "expected_result"},
        )
        _allowlisted_string(
            assertion["requested_capability"], _OW_REQUESTED_CAPABILITIES
        )
        _boolean(assertion["public_read_available"])
        _allowlisted_string(assertion["expected_result"], _OW_EXPECTED_RESULT_VALUES)
    elif case in {"source_ready", "source_ambiguous"}:
        _keys(
            assertion,
            {"candidate_sources", "priority_declared", "expected_result"},
            {"candidate_sources", "priority_declared", "expected_result"},
        )
        for candidate in _list(assertion["candidate_sources"]):
            _source(candidate)
        _boolean(assertion["priority_declared"])
        _string(assertion["expected_result"])
    elif case == "pending":
        _keys(
            assertion, {"response", "expected_result"}, {"response", "expected_result"}
        )
        _validate_sync_array(assertion["response"], _sync_run)
        _string(assertion["expected_result"])
    elif case == "inconclusive":
        _keys(
            assertion, {"observed", "expected_result"}, {"observed", "expected_result"}
        )
        observed = _object(assertion["observed"])
        _keys(observed, {"state", "reason_code"}, {"state", "reason_code"})
        _string(observed["state"])
        _string(observed["reason_code"])
        _string(assertion["expected_result"])
    elif case == "mismatch":
        _keys(
            assertion,
            {"expected", "observed", "expected_result", "expected_run_state"},
            {"expected", "observed", "expected_result", "expected_run_state"},
        )
        _metric_assertion(assertion["expected"])
        _metric_assertion(assertion["observed"])
        _string(assertion["expected_result"])
        _string(assertion["expected_run_state"])
        if assertion["expected_run_state"] != "completed_with_findings":
            _fail()
    else:
        _fail()
    _validate_ow_case_semantics(case, assertion)
    if assertion.get("expected_result") != _OW_EXPECTED_RESULTS[case]:
        _fail()


def _validate_ow_case_semantics(case: str, assertion: JsonObject) -> None:
    if case in {"empty", "zero", "partial"}:
        response = _object(assertion["response"])
        data = _list(response["data"])
        pagination = _object(response["pagination"])
        if case == "empty":
            if data or pagination["has_more"] or pagination["next_cursor"] is not None:
                _fail()
        elif case == "zero":
            if (
                len(data) != 1
                or _object(data[0])["value"] != 0
                or _object(data[0])["is_daily_total"] is not True
            ):
                _fail()
        elif (
            not data
            or pagination["has_more"] is not True
            or pagination["next_cursor"] is None
        ):
            _fail()
    elif case == "null":
        response = _object(assertion["response"])
        recovery = _object(response["recovery"])
        if (
            response["body_summary"] is not None
            or recovery["recovery_score"] is not None
            or recovery["resting_heart_rate_bpm"] is not None
        ):
            _fail()
    elif case == "unsupported":
        if assertion["public_read_available"] is not False:
            _fail()
    elif case == "source_ready":
        candidates = _list(assertion["candidate_sources"])
        if len(candidates) != 1 or assertion["priority_declared"] is not True:
            _fail()
    elif case == "source_ambiguous":
        candidates = _list(assertion["candidate_sources"])
        if len(candidates) != 2 or assertion["priority_declared"] is not False:
            _fail()
    elif case == "pending":
        response = _list(assertion["response"])
        if len(response) != 1:
            _fail()
        run = _object(response[0])
        if (
            run["state"] != "pending"
            or run["progress"] is not None
            or run["ended_at"] is not None
            or run["counts"]["records_saved"] is not None
            or run["counts"]["records_rejected"] is not None
        ):
            _fail()
    elif case == "inconclusive":
        observed = _object(assertion["observed"])
        if (
            observed["state"] != "inconclusive"
            or observed["reason_code"] != "INCONSISTENT_TERMINAL_SIGNALS"
        ):
            _fail()
    elif case == "mismatch":
        expected = _object(assertion["expected"])
        observed = _object(assertion["observed"])
        if (
            expected["type"] == observed["type"]
            and expected["value"] == observed["value"]
            and expected["unit"] == observed["unit"]
            and expected["is_daily_total"] == observed["is_daily_total"]
        ):
            _fail()


def _validate_ow_document(document: Any) -> JsonObject:
    root = _object(document)
    required = {
        "schema_version",
        "synthetic",
        "fixture_scope",
        "subject",
        "safety",
        "notes",
        "public_sync_projection",
        "source_demo",
        "responses",
        "cases",
    }
    allowed = required
    _keys(root, required, allowed)
    _all_json_values(root)

    responses = _object(root["responses"])
    if set(responses) != _OW_RESPONSE_CASES:
        _fail()
    cases = _object(root["cases"])
    if set(cases) != _OW_ASSERTION_CASES:
        _fail()

    for section in (
        "subject",
        "safety",
        "notes",
        "public_sync_projection",
        "source_demo",
    ):
        _scan_privacy(root[section], bff=False, ow_response=True)
    for response in responses.values():
        _scan_privacy(response, bff=False, ow_response=True)
    for assertion in cases.values():
        _scan_privacy(assertion, bff=False, ow_response=True)

    if root["schema_version"] != "ow-read-v1" or root["synthetic"] is not True:
        _fail()
    if root["fixture_scope"] != "public-read-contract":
        _fail()
    subject = _object(root["subject"])
    _keys(subject, {"user_id", "timezone"}, {"user_id", "timezone"})
    if not re.fullmatch(r"user-demo-[a-z0-9-]+", _string(subject["user_id"])):
        _fail()
    if _timezone(subject["timezone"]) != "UTC":
        _fail()
    safety = _object(root["safety"])
    safety_fields = {
        "contains_real_data",
        "contains_private_identifiers",
        "contains_secrets",
        "contains_geodata",
    }
    _keys(safety, safety_fields, safety_fields)
    for value in safety.values():
        if value is not False:
            _fail()
    notes = _list(root["notes"])
    for note in notes:
        _string(note)
        if note not in _OW_SYNTHETIC_NOTES:
            _fail()
    projection = _object(root["public_sync_projection"])
    projection_fields = {
        "owner",
        "classification",
        "implementation_status",
        "allowlisted_fields",
        "upstream_payload",
    }
    _keys(projection, projection_fields, projection_fields)
    if projection["owner"] != "bff" or projection["classification"] != "BFF_sanitized":
        _fail()
    if (
        projection["implementation_status"] != "pending"
        or projection["upstream_payload"] != "raw_not_public"
    ):
        _fail()
    allowlisted_fields = _list(projection["allowlisted_fields"])
    if allowlisted_fields != [
        "state",
        "progress",
        "items_processed",
        "items_total",
        "warning_codes",
        "counts",
    ]:
        _fail()
    _source(root["source_demo"])
    for case, response in responses.items():
        _safe_validate(_validate_ow_response, case, response)
    for case, assertion in cases.items():
        _safe_validate(_validate_ow_case, case, assertion, responses)
    return root


def _bff_warning(value: Any) -> None:
    warning = _object(value)
    fields = {"code", "severity", "message", "domain"}
    _keys(warning, {"code", "severity", "message"}, fields)
    code = _string(warning["code"])
    if code not in _WARNING_CODES:
        _fail()
    severity = _string(warning["severity"])
    if severity not in _BFF_WARNING_SEVERITIES:
        _fail()
    message = _string(warning["message"])
    if message not in _BFF_WARNING_MESSAGES.get(code, frozenset()):
        _fail()
    if "domain" in warning:
        domain = _string(warning["domain"])
        if domain not in _BFF_WARNING_DOMAINS:
            _fail()


def _bff_coverage(value: Any) -> None:
    coverage = _object(value)
    fields = {"requested", "expectedDays", "availableDays", "isPartial", "byDomain"}
    _keys(coverage, set(), fields)
    if "requested" in coverage:
        _requested_window(coverage["requested"])
    for field in ("expectedDays", "availableDays"):
        if field in coverage:
            _integer(coverage[field], allow_none=True)
    if (
        coverage.get("expectedDays") is not None
        and coverage.get("availableDays") is not None
        and coverage["availableDays"] > coverage["expectedDays"]
    ):
        _fail()
    if (coverage.get("expectedDays") is None) != (
        coverage.get("availableDays") is None
    ):
        _fail()
    if "isPartial" in coverage:
        _boolean(coverage["isPartial"])
    if "byDomain" in coverage:
        by_domain = _object(coverage["byDomain"])
        for domain, domain_value in by_domain.items():
            if domain not in {
                "activity",
                "body",
                "heart_rate",
                "recovery",
                "sleep",
                "workouts",
            }:
                _fail()
            domain_coverage = _object(domain_value)
            domain_fields = {"expectedDays", "availableDays", "state"}
            _keys(domain_coverage, domain_fields, domain_fields)
            _integer(domain_coverage["expectedDays"], allow_none=True)
            _integer(domain_coverage["availableDays"], allow_none=True)
            if (
                domain_coverage["expectedDays"] is not None
                and domain_coverage["availableDays"] is not None
                and domain_coverage["availableDays"] > domain_coverage["expectedDays"]
            ):
                _fail()
            if (domain_coverage["expectedDays"] is None) != (
                domain_coverage["availableDays"] is None
            ):
                _fail()
            state = _string(domain_coverage["state"])
            if state not in _BFF_COVERAGE_STATES:
                _fail()


def _bff_counts(value: Any) -> None:
    counts = _object(value)
    fields = {
        "recordsSeen",
        "recordsAccepted",
        "recordsRejected",
        "recordsDuplicated",
        "fieldsUnsupported",
    }
    _keys(counts, fields, fields)
    for item in counts.values():
        _integer(item, allow_none=True)


def _bff_metric_coverage(value: Any) -> None:
    coverage = _object(value)
    fields = {"expectedDays", "availableDays", "observedFraction"}
    _keys(coverage, fields, fields)
    expected_days = _integer(coverage["expectedDays"])
    available_days = _integer(coverage["availableDays"])
    fraction = _fraction(coverage["observedFraction"])
    if expected_days == 0 or available_days > expected_days:
        _fail()
    if available_days == 0 or fraction is None or not 0 < fraction < 1:
        _fail()


def _bff_metric(value: Any, *, metric_name: str | None = None) -> None:
    metric = _object(value)
    fields = {"state", "value", "unit", "isDailyTotal", "sourceKey", "coverage"}
    _keys(metric, {"state", "value", "unit", "isDailyTotal"}, fields)
    state = _string(metric["state"])
    if state not in _BFF_DATA_STATES:
        _fail()
    metric_value = _number(metric["value"], allow_none=True)
    unit = _optional_string(metric["unit"])
    if unit is not None and unit not in _BFF_METRIC_UNITS:
        _fail()
    _validate_bff_overview_unit(metric_name, unit)
    if state in {"value", "partial", "source_ambiguous", "zero"}:
        if metric_value is None:
            _fail()
        if unit is None and metric_name not in _BFF_UNITLESS_VALUE_METRICS:
            _fail()
        if metric_name in _BFF_INTEGER_METRIC_FIELDS:
            _integer(metric_value)
        elif metric_name in _BFF_UNITLESS_VALUE_METRICS:
            _bounded_integer(metric_value, 0, 100)
        else:
            _measurement(metric_value, unit)
    if state == "value" and metric_value == 0:
        _fail()
    if state == "zero" and (
        metric_value != 0
        or (
            metric_name not in _BFF_UNITLESS_VALUE_METRICS
            and metric["isDailyTotal"] is not True
        )
    ):
        _fail()
    if state == "null" and (metric_value is not None or unit is not None):
        _fail()
    if state not in {"value", "partial", "source_ambiguous", "zero"} and (
        metric_value is not None or unit is not None
    ):
        _fail()
    if metric["isDailyTotal"] is not None:
        _boolean(metric["isDailyTotal"])
    if "sourceKey" in metric:
        source_key = _string(metric["sourceKey"])
        if not _DEMO_ID_PATTERNS["sourceKey"].fullmatch(source_key):
            _fail()
    if "coverage" in metric:
        _bff_metric_coverage(metric["coverage"])
    if state == "partial" and "coverage" not in metric:
        _fail()


def _validate_bff_run_state(state: str, run: JsonObject) -> None:
    counts = _object(run["counts"])
    if state == "pending":
        if run["startedAt"] is not None or run["finishedAt"] is not None:
            _fail()
        if any(value is not None for value in counts.values()):
            _fail()
        if "results" in run and _list(run["results"]):
            _fail()
        return

    if run["startedAt"] is None or run["finishedAt"] is None:
        _fail()
    _ordered_optional_timestamps(
        run["requestedAt"], run["startedAt"], last=run["finishedAt"]
    )
    seen = counts["recordsSeen"]
    if seen is None:
        return
    for field in (
        "recordsAccepted",
        "recordsRejected",
        "recordsDuplicated",
        "fieldsUnsupported",
    ):
        count = counts[field]
        if count is not None and count > seen:
            _fail()
    breakdown = [
        counts["recordsAccepted"],
        counts["recordsRejected"],
        counts["recordsDuplicated"],
    ]
    if all(count is not None for count in breakdown) and sum(breakdown) > seen:
        _fail()


def _bff_source_item(value: Any) -> None:
    item = _object(value)
    fields = {"sourceKey", "label", "state", "capabilities", "lastObservedAt"}
    _keys(item, fields, fields)
    if not re.fullmatch(
        r"(?:source-demo|synthetic-source)-[a-z0-9-]+", _string(item["sourceKey"])
    ):
        _fail()
    _string(item["label"])
    state = _string(item["state"])
    if state not in _BFF_SOURCE_STATES:
        _fail()
    for capability in _list(item["capabilities"]):
        capability = _string(capability)
        if capability not in _BFF_SOURCE_CAPABILITIES:
            _fail()
    _rfc3339(item["lastObservedAt"], allow_none=True)


def _bff_run_item(value: Any) -> None:
    item = _object(value)
    fields = {"runKey", "state", "requestedAt", "startedAt", "finishedAt", "counts"}
    _keys(item, fields, fields)
    if not _DEMO_ID_PATTERNS["runKey"].fullmatch(_string(item["runKey"])):
        _fail()
    state = _string(item["state"])
    if state not in _BFF_RUN_STATES:
        _fail()
    _rfc3339(item["requestedAt"])
    _rfc3339(item["startedAt"], allow_none=True)
    _rfc3339(item["finishedAt"], allow_none=True)
    _bff_counts(item["counts"])
    _validate_bff_run_state(state, item)


def _validate_descending_requested_at(items: list[Any]) -> None:
    previous_requested_at: datetime | None = None
    for item_value in items:
        item = _object(item_value)
        requested_at = _rfc3339_datetime(item["requestedAt"])
        if previous_requested_at is not None and requested_at > previous_requested_at:
            _fail()
        previous_requested_at = requested_at


def _bff_page(value: Any) -> None:
    page = _object(value)
    fields = {"nextCursor", "hasNext", "totalCount"}
    _keys(page, fields, fields)
    cursor = page["nextCursor"]
    if cursor is not None and (
        type(cursor) is not str or not _BFF_CURSOR_PATTERN.fullmatch(cursor)
    ):
        _fail()
    _boolean(page["hasNext"])
    if page["hasNext"] is False and cursor is not None:
        _fail()
    if page["hasNext"] is True and cursor is None:
        _fail()
    _integer(page["totalCount"], allow_none=True)


def _bff_scope(value: Any) -> None:
    scope = _object(value)
    fields = {"date", "timezone", "domains"}
    _keys(scope, fields, fields)
    _logical_date(scope["date"])
    _timezone(scope["timezone"])
    domains = _list(scope["domains"])
    if not domains:
        _fail()
    for domain in domains:
        domain = _string(domain)
        if domain not in {
            "activity",
            "sleep",
            "recovery",
            "body",
            "workouts",
            "sources",
        }:
            _fail()


def _bff_result(value: Any) -> None:
    result = _object(value)
    fields = {
        "metric",
        "state",
        "reasonCode",
        "expected",
        "observed",
        "unit",
        "expectedIsDailyTotal",
        "observedIsDailyTotal",
    }
    _keys(result, {"metric", "state"}, fields)
    metric = _string(result["metric"])
    if metric not in _BFF_RESULT_METRICS:
        _fail()
    state = _string(result["state"])
    if state not in _BFF_RESULT_STATES:
        _fail()
    if state == "match":
        _keys(result, {"metric", "state"}, {"metric", "state"})
        return
    if state == "mismatch":
        required = {
            "metric",
            "state",
            "expected",
            "observed",
            "unit",
            "expectedIsDailyTotal",
            "observedIsDailyTotal",
        }
        _keys(result, required, required)
        unit = _string(result["unit"])
        if unit not in _BFF_METRIC_UNITS:
            _fail()
        _validate_ow_metric_unit(metric, unit)
        _measurement(result["expected"], unit)
        _measurement(result["observed"], unit)
        expected = result["expected"]
        observed = result["observed"]
        _boolean(result["expectedIsDailyTotal"])
        _boolean(result["observedIsDailyTotal"])
        if (
            expected == observed
            and result["expectedIsDailyTotal"] == result["observedIsDailyTotal"]
        ):
            _fail()
        return
    _keys(result, {"metric", "state", "reasonCode"}, {"metric", "state", "reasonCode"})
    reason_code = _string(result["reasonCode"])
    if reason_code not in _BFF_RESULT_REASON_CODES:
        _fail()
    expected_metric = {
        "inconclusive": "steps",
        "not_verifiable": "extended_workout_detail",
    }[state]
    if metric != expected_metric:
        _fail()
    expected_reason = {
        "inconclusive": "CURSOR_EXPIRED",
        "not_verifiable": "NO_PUBLIC_WORKOUT_DETAIL",
    }[state]
    if reason_code != expected_reason:
        _fail()


def _bff_verification_run(value: Any) -> None:
    run = _object(value)
    fields = {
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
    _keys(
        run,
        {
            "runKey",
            "state",
            "requestedAt",
            "startedAt",
            "finishedAt",
            "scope",
            "counts",
            "warnings",
        },
        fields,
    )
    if not _DEMO_ID_PATTERNS["runKey"].fullmatch(_string(run["runKey"])):
        _fail()
    state = _string(run["state"])
    if state not in _BFF_RUN_STATES:
        _fail()
    _rfc3339(run["requestedAt"])
    _rfc3339(run["startedAt"], allow_none=True)
    _rfc3339(run["finishedAt"], allow_none=True)
    _bff_scope(run["scope"])
    _bff_counts(run["counts"])
    run_warnings = _list(run["warnings"])
    for warning in run_warnings:
        _bff_warning(warning)
    _validate_warning_domains("verification_run", run_warnings)
    if "results" in run:
        results = _list(run["results"])
        for result_value in results:
            _bff_result(result_value)
    _validate_bff_run_state(state, run)


def _validate_bff_data(case: str, data: Any) -> None:
    if case in {"overview_error", "session_anonymous_200"}:
        if case == "overview_error":
            if data is not None:
                _fail()
        else:
            session = _object(data)
            fields = {"authenticated", "accessState", "canReadVerification"}
            _keys(session, fields, fields)
            _boolean(session["authenticated"])
            access_state = _string(session["accessState"])
            if access_state != "anonymous":
                _fail()
            _boolean(session["canReadVerification"])
            if session != {
                "authenticated": False,
                "accessState": "anonymous",
                "canReadVerification": False,
            }:
                _fail()
        return
    if case == "session_active":
        session = _object(data)
        fields = {"authenticated", "accessState", "canReadVerification"}
        _keys(session, fields, fields)
        _boolean(session["authenticated"])
        access_state = _string(session["accessState"])
        if access_state != "active":
            _fail()
        _boolean(session["canReadVerification"])
        if session != {
            "authenticated": True,
            "accessState": "active",
            "canReadVerification": True,
        }:
            _fail()
    elif case in {"overview_mixed", "overview_empty"}:
        overview = _object(data)
        _keys(
            overview, {"logicalDate", "summary"}, {"logicalDate", "summary", "sources"}
        )
        _logical_date(overview["logicalDate"])
        summary = _object(overview["summary"])
        _keys(summary, set(), set(_BFF_OVERVIEW_SUMMARY_FIELDS))
        for metric_name, metric in summary.items():
            _bff_metric(metric, metric_name=metric_name)
        if "sources" in overview:
            for source in _list(overview["sources"]):
                _bff_source_item(source)
    elif case == "settings_capabilities":
        settings = _object(data)
        fields = {"contract", "versions", "capabilities", "technicalState"}
        _keys(settings, fields, fields)
        if settings["contract"] != "bff-ui-v1":
            _fail()
        versions = _object(settings["versions"])
        _keys(versions, {"bffSchema", "owReference"}, {"bffSchema", "owReference"})
        if versions != {"bffSchema": "1", "owReference": "not_pinned"}:
            _fail()
        capabilities = _object(settings["capabilities"])
        capability_fields = {"gps", "workoutDetails", "segments", "hrZones"}
        _keys(capabilities, capability_fields, capability_fields)
        if capabilities != {
            "gps": "not_verifiable",
            "workoutDetails": "aggregate_only",
            "segments": "not_verifiable",
            "hrZones": "not_verifiable",
        }:
            _fail()
        if settings["technicalState"] != "ready":
            _fail()
    elif case in {"source_ready", "source_ambiguous"}:
        source_data = _object(data)
        _keys(source_data, {"items"}, {"items"})
        for item in _list(source_data["items"]):
            _bff_source_item(item)
    elif case in {"runs_first_page", "runs_second_page"}:
        runs = _object(data)
        _keys(runs, {"items", "page"}, {"items", "page"})
        for item in _list(runs["items"]):
            _bff_run_item(item)
        _bff_page(runs["page"])
    elif case in {
        "verification_run_create",
        "verification_run_partial",
        "verification_not_verifiable",
        "verification_run_mismatch",
        "verification_inconclusive",
    }:
        run_data = _object(data)
        _keys(run_data, {"verificationRun"}, {"verificationRun"})
        _bff_verification_run(run_data["verificationRun"])
    elif data is not None:
        _fail()


def _bff_error(value: Any) -> None:
    error = _object(value)
    fields = {"code", "message", "requestId", "retryable", "field"}
    _keys(error, fields, fields)
    code = _string(error["code"])
    if code not in _ERROR_CODES:
        _fail()
    message = _string(error["message"])
    if message not in _BFF_ERROR_MESSAGES.get(code, frozenset()):
        _fail()
    request_id = _string(error["requestId"])
    if not _DEMO_ID_PATTERNS["requestId"].fullmatch(request_id):
        _fail()
    _boolean(error["retryable"])
    field = _optional_string(error["field"])
    if field not in _BFF_ERROR_FIELDS:
        _fail()


def _has_warning(warnings: list[Any], code: str) -> bool:
    return any(_object(warning)["code"] == code for warning in warnings)


def _validate_warning_domains(case: str, warnings: list[Any]) -> None:
    bound_domains = {
        "BODY_RELATIVE_TO_NOW": "body",
        "PARTIAL_COVERAGE": "activity",
        "SOURCE_AMBIGUOUS": "heart_rate",
    }
    for warning_value in warnings:
        warning = _object(warning_value)
        code = warning["code"]
        if code not in bound_domains:
            continue
        expected_domain = bound_domains[code]
        domain = warning.get("domain")
        if code == "BODY_RELATIVE_TO_NOW" or "domain" in warning:
            if domain != expected_domain:
                _fail()
        elif case == "overview_mixed":
            _fail()


def _validate_bff_case_semantics(case: str, response: JsonObject) -> None:
    data = response["data"]
    warnings = _list(response["warnings"])
    coverage = _object(response["coverage"])
    _validate_warning_domains(case, warnings)

    if case in {"overview_empty", "overview_mixed"}:
        overview = _object(data)
        _logical_date(overview["logicalDate"])
        required_coverage = {
            "requested",
            "expectedDays",
            "availableDays",
            "isPartial",
            "byDomain",
        }
        _keys(coverage, required_coverage, required_coverage)
        requested = _object(coverage["requested"])
        if (
            requested["logicalDate"] != overview["logicalDate"]
            or requested["timezone"] != response["timezone"]
        ):
            _fail()
        if coverage["expectedDays"] != 1:
            _fail()
        if case == "overview_mixed":
            expected_domains = {"activity", "sleep", "body"}
            if set(coverage["byDomain"]) != expected_domains:
                _fail()
            for domain in ("activity", "sleep"):
                if coverage["byDomain"][domain] != {
                    "expectedDays": 1,
                    "availableDays": 1,
                    "state": "complete",
                }:
                    _fail()
            if coverage["byDomain"]["body"] != {
                "expectedDays": None,
                "availableDays": None,
                "state": "relative_to_now",
            }:
                _fail()
            if not _has_warning(warnings, "BODY_RELATIVE_TO_NOW"):
                _fail()
        elif coverage["byDomain"] != {}:
            _fail()

    if case in {
        "session_active",
        "session_anonymous_200",
        "settings_capabilities",
        "source_ready",
        "runs_first_page",
        "runs_second_page",
    } and (coverage or warnings):
        _fail()

    if case == "session_active":
        if data != {
            "authenticated": True,
            "accessState": "active",
            "canReadVerification": True,
        }:
            _fail()
    elif case == "session_anonymous_200":
        if data != {
            "authenticated": False,
            "accessState": "anonymous",
            "canReadVerification": False,
        }:
            _fail()
    elif case == "overview_empty":
        overview = _object(data)
        if (
            overview["summary"] != {}
            or overview.get("sources") != []
            or coverage.get("expectedDays") != 1
            or coverage.get("availableDays") != 0
            or coverage.get("isPartial") is not False
            or coverage.get("byDomain") != {}
            or warnings
        ):
            _fail()
    elif case == "overview_mixed":
        overview = _object(data)
        summary = _object(overview["summary"])
        if (
            set(summary) != _BFF_OVERVIEW_SUMMARY_FIELDS
            or summary["steps"]["state"] != "value"
            or summary["distanceMeters"]["state"] != "partial"
            or summary["activeCaloriesKcal"]["state"] != "zero"
            or summary["sleepDurationSeconds"]["state"] != "value"
            or summary["recoveryScore"]["state"] != "null"
            or summary["stress"]["state"] != "unsupported"
            or summary["heartRate"]["state"] != "source_ambiguous"
            or coverage.get("expectedDays") != 1
            or coverage.get("availableDays") != 1
            or coverage.get("isPartial") is not True
            or not _has_warning(warnings, "PARTIAL_COVERAGE")
            or not _has_warning(warnings, "SOURCE_AMBIGUOUS")
        ):
            _fail()
    elif case == "source_ready":
        items = _list(_object(data)["items"])
        if len(items) != 1 or _object(items[0])["state"] != "ready" or warnings:
            _fail()
    elif case == "source_ambiguous":
        items = _list(_object(data)["items"])
        if (
            len(items) != 2
            or any(_object(item)["state"] != "source_ambiguous" for item in items)
            or len({_object(item)["sourceKey"] for item in items}) != 2
            or len(warnings) != 1
            or not _has_warning(warnings, "SOURCE_AMBIGUOUS")
        ):
            _fail()
    elif case == "runs_first_page":
        runs = _object(data)
        items = _list(runs["items"])
        _validate_descending_requested_at(items)
        items = [_object(item) for item in items]
        states = {item["state"] for item in items}
        if len({item["runKey"] for item in items}) != len(items):
            _fail()
        page = _object(runs["page"])
        if not {"persisted", "partial", "pending"}.issubset(states):
            _fail()
        if page["hasNext"] is not True or page["nextCursor"] is None:
            _fail()
        pending_items = [item for item in items if item["state"] == "pending"]
        if len(pending_items) != 1:
            _fail()
        pending = pending_items[0]
        if pending["startedAt"] is not None or pending["finishedAt"] is not None:
            _fail()
        if any(value is not None for value in pending["counts"].values()):
            _fail()
    elif case == "runs_second_page":
        runs = _object(data)
        page = _object(runs["page"])
        if (
            len(_list(runs["items"])) != 1
            or _object(runs["items"][0])["state"] != "failed"
            or page["hasNext"] is not False
            or page["nextCursor"] is not None
        ):
            _fail()
    elif case in {
        "verification_run_create",
        "verification_run_partial",
        "verification_not_verifiable",
        "verification_run_mismatch",
        "verification_inconclusive",
    }:
        run = _object(_object(data)["verificationRun"])
        run_warnings = _list(run["warnings"])
        counts = _object(run["counts"])
        scope = _object(run["scope"])
        if scope["timezone"] != response["timezone"]:
            _fail()
        if "requested" in coverage:
            requested = _object(coverage["requested"])
            if (
                requested["logicalDate"] != scope["date"]
                or requested["timezone"] != scope["timezone"]
            ):
                _fail()
        if case == "verification_run_create":
            if (
                run["state"] != "pending"
                or run["startedAt"] is not None
                or run["finishedAt"] is not None
                or any(counts[field] is not None for field in counts)
                or run_warnings
                or coverage
                or warnings
            ):
                _fail()
        elif case == "verification_run_partial":
            required_counts = {
                "recordsSeen",
                "recordsAccepted",
                "recordsRejected",
                "recordsDuplicated",
                "fieldsUnsupported",
            }
            if (
                run["state"] != "partial"
                or not _has_warning(run_warnings, "PARTIAL_COVERAGE")
                or coverage.get("isPartial") is not True
                or warnings
                or any(counts[field] is None for field in required_counts)
            ):
                _fail()
        elif case == "verification_run_mismatch":
            results = _list(run.get("results"))
            if (
                run["state"] != "completed_with_findings"
                or not _has_warning(run_warnings, "MISMATCH")
                or not any(
                    _object(result)["state"] == "mismatch"
                    and (
                        _object(result)["expected"] != _object(result)["observed"]
                        or _object(result)["expectedIsDailyTotal"]
                        != _object(result)["observedIsDailyTotal"]
                    )
                    for result in results
                )
                or len(warnings) != 1
                or not _has_warning(warnings, "MISMATCH")
            ):
                _fail()
        elif case == "verification_not_verifiable":
            results = _list(run.get("results"))
            if (
                run["state"] != "not_verifiable"
                or not _has_warning(run_warnings, "NOT_VERIFIABLE")
                or len(warnings) != 1
                or not _has_warning(warnings, "NOT_VERIFIABLE")
                or not any(
                    _object(result).get("state") == "not_verifiable"
                    and _object(result).get("reasonCode") == "NO_PUBLIC_WORKOUT_DETAIL"
                    for result in results
                )
            ):
                _fail()
        elif case == "verification_inconclusive":
            results = _list(run.get("results"))
            if (
                run["state"] != "inconclusive"
                or not _has_warning(run_warnings, "INCONCLUSIVE")
                or len(warnings) != 1
                or not _has_warning(warnings, "INCONCLUSIVE")
                or not any(
                    _object(result).get("state") == "inconclusive"
                    and _object(result).get("reasonCode") == "CURSOR_EXPIRED"
                    for result in results
                )
            ):
                _fail()
    if case in _BFF_ERROR_EXPECTATIONS:
        expected_code, expected_field, expected_retryable = _BFF_ERROR_EXPECTATIONS[
            case
        ]
        error = _object(response["error"])
        if (
            response["data"] is not None
            or coverage != {}
            or warnings
            or error["code"] != expected_code
            or error["field"] != expected_field
            or error["retryable"] is not expected_retryable
        ):
            _fail()


def _validate_bff_response(case: str, value: Any) -> None:
    expected_fixture_case = _BFF_FIXTURE_CASE_BY_RESPONSE_CASE.get(case)
    if expected_fixture_case is None:
        _fail()
    response = _object(value)
    allowed = set(_BASE_BFF_FIELDS) | {"error"}
    _keys(response, set(_BASE_BFF_FIELDS), allowed)
    if response["schemaVersion"] != "1":
        _fail()
    _rfc3339(response["asOf"])
    _timezone(response["timezone"])
    _bff_coverage(response["coverage"])
    if "requested" in response["coverage"]:
        requested = _object(response["coverage"]["requested"])
        if requested["timezone"] != response["timezone"]:
            _fail()
    for warning in _list(response["warnings"]):
        _bff_warning(warning)
    extensions = _object(response["extensions"])
    _keys(extensions, {"fixture"}, {"fixture", "capabilities"})
    fixture = _object(extensions["fixture"])
    _keys(fixture, {"synthetic", "case"}, {"synthetic", "case"})
    if fixture["synthetic"] is not True:
        _fail()
    fixture_case = _allowlisted_string(fixture["case"], _FIXTURE_CASE_NAMES)
    if fixture_case != expected_fixture_case:
        _fail()
    if "capabilities" in extensions:
        capabilities = _object(extensions["capabilities"])
        _keys(capabilities, {"gps", "workoutDetails"}, {"gps", "workoutDetails"})
        if capabilities != {
            "gps": "not_verifiable",
            "workoutDetails": "aggregate_only",
        }:
            _fail()
        for capability in capabilities.values():
            _string(capability)
    _validate_bff_data(case, response["data"])
    if case in _BFF_ERROR_CASES:
        if "error" not in response or response["data"] is not None:
            _fail()
        _bff_error(response["error"])
    elif "error" in response:
        if case != "overview_error":
            _fail()
        _bff_error(response["error"])
    _validate_bff_case_semantics(case, response)


def _validate_adapter_assertion(value: Any) -> None:
    assertion = _object(value)
    fields = {"ow_stage", "ow_status", "ui_state"}
    _keys(assertion, fields, fields)
    stage = assertion["ow_stage"]
    status = assertion["ow_status"]
    ui_state = _allowlisted_string(assertion["ui_state"], _ADAPTER_UI_STATES)
    if _sync_mapping(stage, status) != ui_state:
        _fail()


def _validate_adapter_mapping(value: Any) -> None:
    mapping = _object(value)
    fields = {"runKey", "owRunId", "owStage", "owStatus"}
    _keys(mapping, fields, fields)
    if not _DEMO_ID_PATTERNS["runKey"].fullmatch(_string(mapping["runKey"])):
        _fail()
    if not _DEMO_ID_PATTERNS["owRunId"].fullmatch(_string(mapping["owRunId"])):
        _fail()
    _sync_mapping(mapping["owStage"], mapping["owStatus"])


def _validate_bff_document(document: Any) -> JsonObject:
    root = _object(document)
    fields = {
        "schemaVersion",
        "synthetic",
        "fixtureScope",
        "safety",
        "notes",
        "adapterMappings",
        "responses",
        "adapter_assertions",
    }
    _keys(root, fields, fields)
    _all_json_values(root)
    _scan_privacy(root["safety"], bff=True)
    _scan_privacy(root["notes"], bff=True)
    _scan_privacy(root["adapter_assertions"], bff=False)
    _scan_privacy(root["adapterMappings"], bff=False)

    responses = _object(root["responses"])
    response_cases = set(responses)
    errors = _object(responses.get("errors")) if "errors" in responses else None
    if errors is None:
        _fail()
    success_cases = response_cases - {"errors"}
    if success_cases != _BFF_SUCCESS_CASES or set(errors) != _BFF_ERROR_CASES:
        _fail()
    for case in success_cases:
        _scan_privacy(responses[case], bff=True)
    for case in errors:
        _scan_privacy(errors[case], bff=True)

    _check_public_string(root["schemaVersion"])
    _check_public_string(root["fixtureScope"])
    if (
        root["schemaVersion"] != "1"
        or root["synthetic"] is not True
        or root["fixtureScope"] != "bff-ui-v1"
    ):
        _fail()
    safety = _object(root["safety"])
    safety_fields = {
        "containsRealData",
        "containsPrivateIdentifiers",
        "containsSecrets",
        "containsGeodata",
    }
    _keys(safety, safety_fields, safety_fields)
    for value in safety.values():
        if value is not False:
            _fail()
    for note in _list(root["notes"]):
        _string(note)
        if note not in _BFF_SYNTHETIC_NOTES:
            _fail()
    mappings = _object(root["adapterMappings"])
    _keys(mappings, {"verificationRuns"}, {"verificationRuns"})
    mapping_keys: set[str] = set()
    for mapping_value in _list(mappings["verificationRuns"]):
        _validate_adapter_mapping(mapping_value)
        mapping_key = _object(mapping_value)["runKey"]
        if mapping_key in mapping_keys:
            _fail()
        mapping_keys.add(mapping_key)
    for case in success_cases:
        _safe_validate(_validate_bff_response, case, responses[case])
    for case in errors:
        _safe_validate(_validate_bff_response, case, errors[case])
    assertions = _list(root["adapter_assertions"])
    for assertion_value in assertions:
        _validate_adapter_assertion(assertion_value)
    return root


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(value)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_FIXTURE_PATHS = {
    "docs/fixtures/ow-read-v1.json": _REPOSITORY_ROOT
    / "docs"
    / "fixtures"
    / "ow-read-v1.json",
    "docs/fixtures/ui-verification-v1.json": _REPOSITORY_ROOT
    / "docs"
    / "fixtures"
    / "ui-verification-v1.json",
}


def _fixed_fixture_path(relative_path: str) -> Path:
    if type(relative_path) is not str or relative_path not in _FIXTURE_PATHS:
        _fail()
    candidate = _FIXTURE_PATHS[relative_path].resolve()
    try:
        candidate.relative_to(_REPOSITORY_ROOT)
    except ValueError:
        _fail()
    return candidate


def _load_json_fixture(relative_path: str) -> JsonObject:
    path = _fixed_fixture_path(relative_path)
    try:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            _fail()
        with path.open("r", encoding="utf-8") as fixture_file:
            document = json.load(
                fixture_file,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
    except FixtureContractError:
        raise
    except (OSError, ValueError, json.JSONDecodeError):
        _fail()
    return _object(document)


class OfflineFixtureAdapter:
    """Read validated fixture responses selected by trusted server code."""

    def __init__(self) -> None:
        self._install(
            _load_json_fixture("docs/fixtures/ow-read-v1.json"),
            _load_json_fixture("docs/fixtures/ui-verification-v1.json"),
        )

    @classmethod
    def from_documents(
        cls, ow_document: Mapping[str, Any], bff_document: Mapping[str, Any]
    ) -> OfflineFixtureAdapter:
        """Build an adapter from already-loaded documents for offline tests."""

        instance = cls.__new__(cls)
        instance._install(ow_document, bff_document)
        return instance

    def _install(self, ow_document: Any, bff_document: Any) -> None:
        try:
            _guard_document(ow_document)
            _guard_document(bff_document)
            ow_copy = deepcopy(ow_document)
            bff_copy = deepcopy(bff_document)
            self._ow_document = _validate_ow_document(ow_copy)
            self._bff_document = _validate_bff_document(bff_copy)
        except FixtureContractError:
            raise
        except _VALIDATION_ERRORS:
            _fail()
        self._ow_responses = self._ow_document["responses"]
        self._ow_cases = self._ow_document["cases"]
        bff_responses = self._bff_document["responses"]
        self._bff_responses = {
            **{case: bff_responses[case] for case in _BFF_SUCCESS_CASES},
            **{case: bff_responses["errors"][case] for case in _BFF_ERROR_CASES},
        }

    def get_ow_response(self, case: str) -> JsonObject:
        """Return one allowlisted OW response in its original ``snake_case`` shape."""

        if type(case) is not str or case not in _OW_RESPONSE_CASES:
            _fail()
        response = self._ow_responses[case]
        _validate_privacy_first(
            response,
            _validate_ow_response,
            case,
            response,
            bff=False,
            ow_response=True,
        )
        return deepcopy(response)

    def get_ow_case(self, case: str) -> JsonObject:
        """Return one server-side OW assertion case without the full fixture."""

        if type(case) is not str or case not in _OW_ASSERTION_CASES:
            _fail()
        assertion = self._ow_cases[case]
        _scan_privacy(assertion, bff=False, ow_response=True)
        _safe_validate(
            _scan_ow_case_observed_reference,
            assertion,
            self._ow_responses,
        )
        _safe_validate(
            _validate_ow_case,
            case,
            assertion,
            self._ow_responses,
        )
        return deepcopy(assertion)

    def get_bff_response(self, case: str) -> JsonObject:
        """Return one allowlisted BFF/UI wrapper selected by trusted server code."""

        if type(case) is not str or case not in self._bff_responses:
            _fail()
        response = self._bff_responses[case]
        _validate_privacy_first(
            response,
            _validate_bff_response,
            case,
            response,
            bff=True,
        )
        return deepcopy(response)

    def list_ow_response_cases(self) -> tuple[str, ...]:
        """Return the available OW response selectors."""

        return tuple(sorted(_OW_RESPONSE_CASES))

    def list_ow_cases(self) -> tuple[str, ...]:
        """Return the available OW assertion selectors."""

        return tuple(sorted(_OW_ASSERTION_CASES))

    def list_bff_cases(self) -> tuple[str, ...]:
        """Return the available BFF/UI response selectors."""

        return tuple(sorted(self._bff_responses))


def load_offline_fixture_adapter() -> OfflineFixtureAdapter:
    """Create the repository-relative deterministic adapter."""

    return OfflineFixtureAdapter()


__all__ = [
    "FixtureContractError",
    "OfflineFixtureAdapter",
    "load_offline_fixture_adapter",
]
