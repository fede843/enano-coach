import { isValidCursor } from "./runs";
import type {
  AccessState,
  ApiErrorPayload,
  Coverage,
  DomainCoverage,
  Envelope,
  Extensions,
  Metric,
  MetricState,
  MetricUnit,
  OverviewData,
  ActivityTrendData,
  ActivityTrendMetric,
  ActivityTrendRange,
  SleepTrendData,
  SleepInterval,
  ActivityTrendPointMetric,
  RunCounts,
  RunItem,
  RunScope,
  RunsPageData,
  SessionData,
  SettingsData,
  Source,
  VerificationResult,
  VerificationRun,
  Warning
} from "./types";

const BASE_FIELDS = ["schemaVersion", "asOf", "timezone", "data", "coverage", "warnings", "extensions"] as const;

export const API_ROUTES = Object.freeze({
  session: "/api/v1/session",
  overview: "/api/v1/me/verify/overview",
  activityTrend: "/api/v1/me/verify/activity-trend",
  sleepTrend: "/api/v1/me/verify/sleep-trend",
  sources: "/api/v1/me/verify/sources",
  settings: "/api/v1/me/verify/settings",
  runs: "/api/v1/me/verify/runs"
});

export const API_ROUTE_PATHS = Object.freeze([
  API_ROUTES.session,
  API_ROUTES.overview,
  API_ROUTES.activityTrend,
  API_ROUTES.sleepTrend,
  API_ROUTES.sources,
  API_ROUTES.settings,
  API_ROUTES.runs,
  `${API_ROUTES.runs}/:runKey`,
  `${API_ROUTES.runs} [POST]`
]);

const QUERY_FIELDS: Record<string, readonly string[]> = {
  [API_ROUTES.session]: [],
  [API_ROUTES.overview]: ["date", "timezone"],
  [API_ROUTES.activityTrend]: ["date", "timezone", "range"],
  [API_ROUTES.sleepTrend]: ["date", "timezone", "range"],
  [API_ROUTES.sources]: ["date", "timezone"],
  [API_ROUTES.settings]: [],
  [API_ROUTES.runs]: ["from", "to", "state", "limit", "cursor"]
};

const SAFE_ERROR_CODES = new Set([
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
  "SESSION_EXPIRED",
  "SESSION_REQUIRED",
  "UPSTREAM_INVALID",
  "UPSTREAM_TIMEOUT",
  "UPSTREAM_UNAVAILABLE"
]);

export const ERROR_COPY: Record<string, string> = Object.freeze({
  ACCESS_BLOCKED: "El acceso a esta consulta está bloqueado.",
  ACCESS_PENDING: "La cuenta todavía no tiene acceso a esta consulta.",
  CLIENT_CRYPTO_UNAVAILABLE: "No se puede iniciar la verificación en este navegador.",
  CURSOR_CONTEXT_MISMATCH: "El cursor no coincide con este listado.",
  CURSOR_EXPIRED: "La página expiró; reinicia el listado.",
  FORBIDDEN: "Esta consulta no está permitida.",
  IDEMPOTENCY_CONFLICT: "La solicitud entra en conflicto con otra operación.",
  INTERNAL_ERROR: "No se pudo completar la solicitud.",
  INVALID_CURSOR: "El cursor no es válido para este listado.",
  INVALID_QUERY: "La fecha, zona horaria o filtro no es válido.",
  INVALID_SCOPE: "El alcance de la verificación no es válido.",
  METHOD_NOT_ALLOWED: "Este método no está permitido.",
  NOT_FOUND: "No se encontró el recurso solicitado.",
  RATE_LIMITED: "Se alcanzó el límite de solicitudes.",
  RUN_NOT_FOUND: "No se encontró la verificación solicitada.",
  SESSION_EXPIRED: "La sesión expiró.",
  SESSION_REQUIRED: "La sesión es necesaria para consultar.",
  UPSTREAM_INVALID: "La fuente devolvió una respuesta no válida.",
  UPSTREAM_TIMEOUT: "La fuente tardó demasiado en responder.",
  UPSTREAM_UNAVAILABLE: "La fuente no está disponible; consulta de nuevo manualmente.",
  NETWORK_ERROR: "No se pudo contactar con el BFF.",
  MALFORMED_RESPONSE: "La respuesta del BFF no tiene el formato esperado."
});

const SAFE_WARNING_CODES = new Set([
  "BODY_RELATIVE_TO_NOW",
  "CURSOR_EXPIRED",
  "INCONCLUSIVE",
  "MISMATCH",
  "NOT_VERIFIABLE",
  "PARTIAL_COVERAGE",
  "SOURCE_AMBIGUOUS",
  "UNSUPPORTED",
  "UPSTREAM_LIMITED"
]);
const SAFE_WARNING_SEVERITIES = new Set(["info", "warning"]);
const SAFE_WARNING_DOMAINS = new Set(["activity", "body", "heart_rate", "recovery", "sleep", "workouts"]);
const SAFE_ERROR_FIELDS = new Set([
  "Content-Length",
  "Content-Type",
  "Idempotency-Key",
  "Origin",
  "body",
  "date",
  "domains",
  "from",
  "limit",
  "cursor",
  "state",
  "timezone",
  "to"
]);
const SAFE_UNITS = new Set<Exclude<MetricUnit, null>>([
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
  "watts"
]);
const SAFE_METRIC_STATES = new Set<MetricState>([
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
  "zero"
]);
const SAFE_RUN_STATES = new Set([
  "cancelled",
  "completed_with_findings",
  "failed",
  "inconclusive",
  "not_verifiable",
  "partial",
  "pending",
  "persisted",
  "skipped"
]);
const SAFE_DOMAINS = new Set(["activity", "sleep", "recovery", "body", "workouts", "sources"]);
const SAFE_SOURCE_CAPABILITIES = new Set(["activity", "body", "heart_rate", "sleep"]);
const SAFE_SOURCE_STATES = new Set(["ready", "source_ambiguous"]);
const SAFE_RESULT_STATES = new Set(["inconclusive", "match", "mismatch", "not_verifiable"]);
const SAFE_RESULT_METRICS = new Set(["extended_workout_detail", "steps"]);
const SAFE_RESULT_REASONS = new Set(["CURSOR_EXPIRED", "NO_PUBLIC_WORKOUT_DETAIL"]);
const SAFE_DOMAIN_COVERAGE_STATES = new Set([
  "complete",
  "empty",
  "inconclusive",
  "not_verifiable",
  "partial",
  "relative_to_now",
  "unsupported"
]);
type MetricRule = {
  unit: MetricUnit;
  nonNegative?: boolean;
  integer?: boolean;
  minimum?: number;
  maximum?: number;
};

const METRIC_RULES: Record<string, MetricRule> = {
  steps: { unit: "count", nonNegative: true, integer: true },
  distanceMeters: { unit: "meters", nonNegative: true },
  activeCaloriesKcal: { unit: "kcal", nonNegative: true },
  sleepDurationSeconds: { unit: "seconds", nonNegative: true, integer: true },
  recoveryScore: { unit: null, nonNegative: true, integer: true, minimum: 0, maximum: 100 },
  stress: { unit: null },
  heartRate: { unit: "bpm", nonNegative: true }
};
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const UTC_TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;
const UUID_V4_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const REQUEST_ID_PATTERN = /^req-demo-[a-z0-9-]+$/;
const RUN_KEY_PATTERN = /^verify-demo-[a-z0-9-]+$/;
// Keep unrecognized reference text out of the view model until it has a contract.
const OW_REFERENCE_NOT_PINNED = "not_pinned" as const;

const idempotencyBrand: unique symbol = Symbol("generated-idempotency-key");
export type IdempotencyKey = { readonly [idempotencyBrand]: true };
const generatedIdempotencyKeys = new WeakSet<object>();
const idempotencyValues = new WeakMap<object, string>();

export class InvalidResponse extends Error {
  constructor(message = "invalid response") {
    super(message);
    this.name = "InvalidResponse";
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly field: string | null;
  readonly retryable: boolean;
  readonly requestId: string | null;
  readonly retryAfterMs: number | null;
  readonly retryAfter: number | null;

  constructor({
    status = 0,
    code = "NETWORK_ERROR",
    field = null,
    retryable = false,
    requestId = null,
    retryAfterMs = null
  }: {
    status?: number;
    code?: string;
    field?: string | null;
    retryable?: boolean;
    requestId?: string | null;
    retryAfterMs?: number | null;
  } = {}) {
    super(ERROR_COPY[code] || ERROR_COPY.NETWORK_ERROR);
    this.name = "ApiError";
    this.status = status;
    this.code = ERROR_COPY[code] ? code : "NETWORK_ERROR";
    this.field = typeof field === "string" ? field : null;
    this.retryable = retryable === true;
    this.requestId = REQUEST_ID_PATTERN.test(String(requestId || "")) ? requestId : null;
    this.retryAfterMs = Number.isFinite(retryAfterMs) && (retryAfterMs || 0) >= 0 && (retryAfterMs || 0) <= 86_400_000
      ? Math.floor(retryAfterMs || 0)
      : null;
    this.retryAfter = this.retryAfterMs === null || this.retryAfterMs === 0
      ? null
      : Math.ceil(this.retryAfterMs / 1000);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new InvalidResponse(message);
  }
}

function onlyKeys(value: unknown, allowed: readonly string[], required: readonly string[] = []): asserts value is Record<string, unknown> {
  assert(isRecord(value), "expected object");
  const allowedSet = new Set(allowed);
  assert(Object.keys(value).every((key) => allowedSet.has(key)), "unknown response field");
  assert(required.every((key) => Object.prototype.hasOwnProperty.call(value, key)), "missing response field");
}

function validDate(value: unknown): value is string {
  if (typeof value !== "string" || !DATE_PATTERN.test(value)) {
    return false;
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().startsWith(value);
}

function invalidQuery(field: string | null): ApiError {
  return new ApiError({ status: 400, code: "INVALID_QUERY", field, retryable: false });
}

function invalidScope(field: string): ApiError {
  return new ApiError({ status: 422, code: "INVALID_SCOPE", field, retryable: false });
}

export function validTimezone(value: unknown): value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > 64) {
    return false;
  }
  try {
    new Intl.DateTimeFormat("en", { timeZone: value }).format();
    return true;
  } catch {
    return false;
  }
}

function validTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || !UTC_TIMESTAMP_PATTERN.test(value)) {
    return false;
  }
  const datePart = value.slice(0, 10);
  const hour = Number(value.slice(11, 13));
  const minute = Number(value.slice(14, 16));
  const second = Number(value.slice(17, 19));
  if (!validDate(datePart) || hour > 23 || minute > 59 || second > 59) {
    return false;
  }
  return Number.isFinite(Date.parse(value));
}

function parseWarning(value: unknown): Warning {
  onlyKeys(value, ["code", "severity", "message", "domain"], ["code", "severity", "message"]);
  assert(typeof value.code === "string" && SAFE_WARNING_CODES.has(value.code), "unknown warning code");
  assert(typeof value.severity === "string" && SAFE_WARNING_SEVERITIES.has(value.severity), "unknown warning severity");
  assert(typeof value.message === "string" && value.message.length <= 240, "unsafe warning copy");
  if (value.domain !== undefined && value.domain !== null) {
    assert(typeof value.domain === "string" && SAFE_WARNING_DOMAINS.has(value.domain), "unknown warning domain");
  }
  return {
    code: value.code,
    severity: value.severity as Warning["severity"],
    ...(value.domain === undefined || value.domain === null ? {} : { domain: value.domain })
  };
}

function parseWarnings(value: unknown): Warning[] {
  assert(Array.isArray(value) && value.length <= 100, "invalid warnings");
  return value.map(parseWarning);
}

function parseExtensions(value: unknown): Extensions {
  assert(isRecord(value), "invalid extensions");
  const sanitized: Extensions = {};
  if (value.fixture !== undefined) {
    onlyKeys(value.fixture, ["synthetic", "case"], ["synthetic", "case"]);
    assert(value.fixture.synthetic === true && typeof value.fixture.case === "string", "invalid fixture extension");
    sanitized.fixture = { synthetic: true, case: value.fixture.case };
  }
  if (value.capabilities !== undefined) {
    onlyKeys(value.capabilities, ["gps", "workoutDetails", "segments", "hrZones"]);
    const capabilities: NonNullable<Extensions["capabilities"]> = {};
    for (const [key, capability] of Object.entries(value.capabilities)) {
      assert(capability === "aggregate_only" || capability === "not_verifiable", "invalid capability extension");
      capabilities[key as keyof NonNullable<Extensions["capabilities"]>] = capability;
    }
    sanitized.capabilities = capabilities;
  }
  return sanitized;
}

function parseCoverage(value: unknown): Coverage {
  onlyKeys(value, ["requested", "expectedDays", "availableDays", "isPartial", "byDomain"]);
  const coverage: Coverage = {};
  if (value.requested !== undefined && value.requested !== null) {
    onlyKeys(value.requested, ["logicalDate", "from", "to", "timezone"], ["logicalDate", "from", "to", "timezone"]);
    assert(validDate(value.requested.logicalDate), "invalid coverage date");
    assert(validTimestamp(value.requested.from) && validTimestamp(value.requested.to), "invalid coverage window");
    assert(Date.parse(value.requested.from) < Date.parse(value.requested.to), "reversed coverage window");
    assert(validTimezone(value.requested.timezone), "invalid coverage timezone");
    coverage.requested = {
      logicalDate: value.requested.logicalDate,
      from: value.requested.from,
      to: value.requested.to,
      timezone: value.requested.timezone
    };
  }
  for (const key of ["expectedDays", "availableDays"] as const) {
    const rawCount = value[key];
    if (rawCount !== undefined && rawCount !== null) {
      assert(Number.isInteger(rawCount) && (rawCount as number) >= 0, "invalid coverage count");
      coverage[key] = rawCount as number;
    } else if (rawCount === null) {
      coverage[key] = null;
    }
  }
  const expectedDays = value.expectedDays as number | null | undefined;
  const availableDays = value.availableDays as number | null | undefined;
  const countsAbsent = expectedDays === undefined && availableDays === undefined;
  const countsNull = expectedDays === null && availableDays === null;
  const countsNumeric = Number.isInteger(expectedDays) && Number.isInteger(availableDays);
  assert(countsAbsent || countsNull || countsNumeric, "incomplete coverage counts");
  if (expectedDays !== undefined && availableDays !== undefined && expectedDays !== null && availableDays !== null) {
    assert(availableDays <= expectedDays, "invalid coverage range");
  }
  if (value.isPartial !== undefined) {
    assert(typeof value.isPartial === "boolean", "invalid partial coverage flag");
    assert(!countsAbsent, "partial coverage has no scope counts");
    coverage.isPartial = value.isPartial;
  }
  if (value.byDomain !== undefined && value.byDomain !== null) {
    onlyKeys(value.byDomain, ["activity", "body", "recovery", "sleep", "workouts"]);
    const byDomain: NonNullable<Coverage["byDomain"]> = {};
    for (const [key, domain] of Object.entries(value.byDomain)) {
      onlyKeys(domain, ["expectedDays", "availableDays", "state"], ["expectedDays", "availableDays", "state"]);
      const expected = domain.expectedDays as number | null;
      const available = domain.availableDays as number | null;
      const domainState = domain.state as DomainCoverage["state"];
      assert(typeof domain.state === "string" && SAFE_DOMAIN_COVERAGE_STATES.has(domain.state), "invalid domain coverage state");
      assert(expected === null || Number.isInteger(expected) && expected >= 0, "invalid domain expected days");
      assert(available === null || Number.isInteger(available) && available >= 0, "invalid domain available days");
      assert(
        (expected === null && available === null)
          || (Number.isInteger(expected) && Number.isInteger(available)),
        "incomplete domain coverage counts"
      );
      if (expected !== null && available !== null) {
        assert(available <= expected, "invalid domain coverage range");
      }
      if (["complete", "partial", "empty"].includes(domainState)) {
        assert(expected !== null && available !== null, "daily domain has no coverage counts");
      }
      if (domainState === "relative_to_now") {
        assert(expected === null && available === null, "relative coverage has daily counts");
      }
      byDomain[key as keyof NonNullable<Coverage["byDomain"]>] = {
        expectedDays: expected,
        availableDays: available,
        state: domainState
      };
    }
    coverage.byDomain = byDomain;
  }
  return coverage;
}

function parseError(value: unknown): ApiErrorPayload {
  onlyKeys(value, ["code", "message", "requestId", "retryable", "field"], ["code", "message", "requestId", "retryable", "field"]);
  assert(typeof value.code === "string" && SAFE_ERROR_CODES.has(value.code), "unknown error code");
  assert(typeof value.message === "string" && value.message.length <= 240, "unsafe error copy");
  assert(typeof value.requestId === "string" && REQUEST_ID_PATTERN.test(value.requestId), "unsafe request id");
  assert(typeof value.retryable === "boolean", "invalid retryable flag");
  assert(value.field === null || typeof value.field === "string" && SAFE_ERROR_FIELDS.has(value.field), "invalid error field");
  return {
    code: value.code,
    retryable: value.retryable,
    requestId: value.requestId,
    field: value.field
  };
}

export function parseEnvelope(value: unknown): Envelope {
  const hasError = isRecord(value) && Object.prototype.hasOwnProperty.call(value, "error");
  onlyKeys(value, hasError ? [...BASE_FIELDS, "error"] : BASE_FIELDS, BASE_FIELDS);
  assert(value.schemaVersion === "1", "unsupported schema version");
  assert(validTimestamp(value.asOf), "invalid asOf");
  assert(validTimezone(value.timezone), "invalid envelope timezone");
  assert(value.data === null || isRecord(value.data), "invalid envelope data");
  const parsed: Envelope = {
    schemaVersion: "1",
    asOf: value.asOf,
    timezone: value.timezone,
    data: value.data,
    coverage: parseCoverage(value.coverage),
    warnings: parseWarnings(value.warnings),
    extensions: parseExtensions(value.extensions)
  };
  if (hasError) {
    assert(parsed.data === null, "error response contains data");
    parsed.error = parseError(value.error);
  }
  return parsed;
}

function parseNumber(value: unknown, allowNull = false): number | null {
  if (allowNull && value === null) {
    return null;
  }
  assert(typeof value === "number" && Number.isFinite(value), "invalid numeric value");
  return value;
}

function parseMetricCoverage(value: unknown): Metric["coverage"] {
  onlyKeys(value, ["expectedDays", "availableDays", "observedFraction"], ["expectedDays", "availableDays", "observedFraction"]);
  const expectedDays = value.expectedDays as number;
  const availableDays = value.availableDays as number;
  const observedFraction = value.observedFraction as number;
  assert(Number.isInteger(expectedDays) && expectedDays > 0, "invalid metric expected days");
  assert(Number.isInteger(availableDays) && availableDays >= 0 && availableDays <= expectedDays, "invalid metric available days");
  assert(typeof observedFraction === "number" && Number.isFinite(observedFraction) && observedFraction >= 0 && observedFraction <= 1, "invalid metric fraction");
  return {
    expectedDays,
    availableDays,
    observedFraction
  };
}

function parseMetric(value: unknown, { metricKey, heartRate = false, expectedUnit }: { metricKey?: string; heartRate?: boolean; expectedUnit?: MetricUnit } = {}): Metric {
  onlyKeys(value, ["state", "value", "unit", "isDailyTotal", "sourceKey", "coverage"], ["state", "value", "unit", "isDailyTotal"]);
  assert(typeof value.state === "string" && SAFE_METRIC_STATES.has(value.state as MetricState), "unknown metric state");
  const numericValue = parseNumber(value.value, true);
  assert(value.unit === null || typeof value.unit === "string" && SAFE_UNITS.has(value.unit as Exclude<MetricUnit, null>), "unknown metric unit");
  assert(typeof value.isDailyTotal === "boolean" || value.isDailyTotal === null, "invalid daily total flag");
  if (value.sourceKey !== undefined) {
    assert(typeof value.sourceKey === "string" && value.sourceKey.length > 0 && value.sourceKey.length <= 128, "invalid source key");
  }
  const coverage = value.coverage === undefined ? undefined : parseMetricCoverage(value.coverage);
  const state = value.state as MetricState;
  const unit = value.unit as MetricUnit;
  if (["null", "empty", "unsupported", "not_verifiable", "pending", "inconclusive", "error"].includes(state)) {
    assert(numericValue === null && unit === null, "missing metric state changed into a value");
  }
  if (["value", "partial", "source_ambiguous"].includes(state)) {
    assert(numericValue !== null, "value state has no value");
  }
  if (state === "value") {
    assert(numericValue !== 0, "a confirmed zero must use the zero state");
  }
  if (state === "zero") {
    assert(numericValue === 0, "zero state has a non-zero value");
  }
  if (state === "partial") {
    assert(coverage !== undefined && coverage.observedFraction > 0 && coverage.observedFraction < 1, "partial metric has no partial coverage");
  }
  const rule = metricKey === undefined ? undefined : METRIC_RULES[metricKey];
  if (rule && numericValue !== null) {
    if (rule.nonNegative) {
      assert(numericValue >= 0, "metric value cannot be negative");
    }
    if (rule.integer) {
      assert(Number.isInteger(numericValue), "metric value must be an integer");
    }
    if (rule.minimum !== undefined) {
      assert(numericValue >= rule.minimum, "metric value is below its supported minimum");
    }
    if (rule.maximum !== undefined) {
      assert(numericValue <= rule.maximum, "metric value is above its supported maximum");
    }
  }
  if (heartRate) {
    assert(unit === null || unit === "bpm", "heart rate has an invalid unit");
    assert(coverage === undefined, "scalar heart rate has unexpected coverage");
  }
  if (expectedUnit === null) {
    assert(unit === null, "metric must be unitless");
  } else if (expectedUnit && ["value", "partial", "source_ambiguous", "zero"].includes(state)) {
    assert(unit === expectedUnit, "metric has an invalid unit");
  }
  return {
    state,
    value: numericValue,
    unit,
    isDailyTotal: value.isDailyTotal,
    ...(value.sourceKey === undefined ? {} : { sourceKey: value.sourceKey }),
    ...(coverage === undefined ? {} : { coverage })
  };
}

function parseSource(value: unknown): Source {
  onlyKeys(value, ["sourceKey", "label", "state", "capabilities", "lastObservedAt"], ["sourceKey", "label", "state", "capabilities"]);
  assert(typeof value.sourceKey === "string" && value.sourceKey.length > 0 && value.sourceKey.length <= 128, "invalid source key");
  assert(typeof value.label === "string" && value.label.length > 0 && value.label.length <= 120, "invalid source label");
  assert(typeof value.state === "string" && SAFE_SOURCE_STATES.has(value.state), "unknown source state");
  assert(Array.isArray(value.capabilities) && value.capabilities.every((item) => typeof item === "string" && SAFE_SOURCE_CAPABILITIES.has(item)), "invalid source capabilities");
  if (value.lastObservedAt !== undefined && value.lastObservedAt !== null) {
    assert(validTimestamp(value.lastObservedAt), "invalid source timestamp");
  }
  return {
    sourceKey: value.sourceKey,
    label: value.label,
    state: value.state as Source["state"],
    capabilities: value.capabilities as Source["capabilities"],
    ...(value.lastObservedAt === undefined ? {} : { lastObservedAt: value.lastObservedAt as string | null })
  };
}

function parseCounts(value: unknown): RunCounts {
  const keys = ["recordsSeen", "recordsAccepted", "recordsRejected", "recordsDuplicated", "fieldsUnsupported"] as const;
  onlyKeys(value, keys, keys);
  for (const count of Object.values(value)) {
    assert(count === null || typeof count === "number" && Number.isInteger(count) && count >= 0, "invalid run count");
  }
  return {
    recordsSeen: value.recordsSeen as number | null,
    recordsAccepted: value.recordsAccepted as number | null,
    recordsRejected: value.recordsRejected as number | null,
    recordsDuplicated: value.recordsDuplicated as number | null,
    fieldsUnsupported: value.fieldsUnsupported as number | null
  };
}

function parseScope(value: unknown): RunScope {
  onlyKeys(value, ["date", "timezone", "domains"], ["date", "timezone", "domains"]);
  assert(validDate(value.date) && validTimezone(value.timezone), "invalid run scope");
  assert(Array.isArray(value.domains) && value.domains.length > 0 && value.domains.every((domain) => typeof domain === "string" && SAFE_DOMAINS.has(domain)), "invalid run domains");
  return {
    date: value.date,
    timezone: value.timezone,
    domains: value.domains as RunScope["domains"]
  };
}

function validateRunLifecycle(run: Pick<RunItem, "state" | "requestedAt" | "startedAt" | "finishedAt">, asOf: string): void {
  const producedAt = Date.parse(asOf);
  const requestedAt = Date.parse(run.requestedAt);
  const startedAt = run.startedAt === null ? null : Date.parse(run.startedAt);
  const finishedAt = run.finishedAt === null ? null : Date.parse(run.finishedAt);
  assert(Number.isFinite(producedAt) && Number.isFinite(requestedAt), "invalid run lifecycle timestamp");
  assert(requestedAt <= producedAt, "run was requested after the response was produced");
  if (startedAt !== null) {
    assert(Number.isFinite(startedAt) && startedAt >= requestedAt && startedAt <= producedAt, "run has an invalid start chronology");
  }
  if (finishedAt !== null) {
    assert(Number.isFinite(finishedAt) && finishedAt >= requestedAt && finishedAt <= producedAt, "run has an invalid finish chronology");
    if (startedAt !== null) {
      assert(finishedAt >= startedAt, "run finished before it started");
    }
  }
  if (run.state === "pending") {
    assert(finishedAt === null, "pending run is already finished");
  } else {
    assert(startedAt !== null && finishedAt !== null, "terminal run has incomplete timestamps");
  }
}

function parseResult(value: unknown): VerificationResult {
  onlyKeys(value, ["metric", "state", "reasonCode", "expected", "observed", "unit", "expectedIsDailyTotal", "observedIsDailyTotal"], ["metric", "state"]);
  assert(typeof value.metric === "string" && SAFE_RESULT_METRICS.has(value.metric), "invalid verification result");
  assert(typeof value.state === "string" && SAFE_RESULT_STATES.has(value.state), "invalid verification result");
  if (value.state === "match") {
    assert(Object.keys(value).length === 2, "match result has unexpected detail");
    return { metric: value.metric as VerificationResult["metric"], state: "match" };
  }
  if (value.state === "mismatch") {
    onlyKeys(value, ["metric", "state", "expected", "observed", "unit", "expectedIsDailyTotal", "observedIsDailyTotal"], ["metric", "state", "expected", "observed", "unit", "expectedIsDailyTotal", "observedIsDailyTotal"]);
    parseNumber(value.expected);
    parseNumber(value.observed);
    assert(typeof value.unit === "string" && SAFE_UNITS.has(value.unit as Exclude<MetricUnit, null>), "invalid mismatch unit");
    assert(typeof value.expectedIsDailyTotal === "boolean" && typeof value.observedIsDailyTotal === "boolean", "invalid mismatch flags");
    const expected = value.expected as number;
    const observed = value.observed as number;
    if (value.metric === "steps") {
      assert(value.unit === "count", "steps mismatch has an invalid unit");
      assert(Number.isInteger(expected) && expected >= 0 && Number.isInteger(observed) && observed >= 0, "steps mismatch has invalid values");
    }
    assert(expected !== observed || value.expectedIsDailyTotal !== value.observedIsDailyTotal, "mismatch result has no observable difference");
    return {
      metric: value.metric as VerificationResult["metric"],
      state: "mismatch",
      expected,
      observed,
      unit: value.unit as Exclude<MetricUnit, null>,
      expectedIsDailyTotal: value.expectedIsDailyTotal,
      observedIsDailyTotal: value.observedIsDailyTotal
    };
  }
  onlyKeys(value, ["metric", "state", "reasonCode"], ["metric", "state", "reasonCode"]);
  assert(typeof value.reasonCode === "string" && SAFE_RESULT_REASONS.has(value.reasonCode), "invalid result reason");
  if (value.state === "inconclusive") {
    assert(value.reasonCode === "CURSOR_EXPIRED", "inconclusive result has an invalid reason");
  } else {
    assert(value.reasonCode === "NO_PUBLIC_WORKOUT_DETAIL", "not verifiable result has an invalid reason");
    assert(value.metric === "extended_workout_detail", "workout detail result has an invalid metric");
  }
  return {
    metric: value.metric as VerificationResult["metric"],
    state: value.state as VerificationResult["state"],
    reasonCode: value.reasonCode as VerificationResult["reasonCode"]
  };
}

function parseRunItem(value: unknown, asOf: string): RunItem {
  const keys = ["runKey", "state", "requestedAt", "startedAt", "finishedAt", "counts"] as const;
  onlyKeys(value, keys, keys);
  assert(typeof value.runKey === "string" && RUN_KEY_PATTERN.test(value.runKey), "invalid run key");
  assert(typeof value.state === "string" && SAFE_RUN_STATES.has(value.state), "unknown run state");
  assert(validTimestamp(value.requestedAt), "invalid run request time");
  assert(value.startedAt === null || validTimestamp(value.startedAt), "invalid run start time");
  assert(value.finishedAt === null || validTimestamp(value.finishedAt), "invalid run finish time");
  const run: RunItem = {
    runKey: value.runKey,
    state: value.state as RunItem["state"],
    requestedAt: value.requestedAt,
    startedAt: value.startedAt,
    finishedAt: value.finishedAt,
    counts: parseCounts(value.counts)
  };
  validateRunLifecycle(run, asOf);
  return run;
}

function parseRun(value: unknown, asOf: string): VerificationRun {
  onlyKeys(value, ["runKey", "state", "requestedAt", "startedAt", "finishedAt", "scope", "counts", "warnings", "results"], ["runKey", "state", "requestedAt", "startedAt", "finishedAt", "scope", "counts", "warnings"]);
  const item = parseRunItem({
    runKey: value.runKey,
    state: value.state,
    requestedAt: value.requestedAt,
    startedAt: value.startedAt,
    finishedAt: value.finishedAt,
    counts: value.counts
  }, asOf);
  const warnings = parseWarnings(value.warnings);
  const results = value.results === undefined || value.results === null ? undefined : (() => {
    assert(Array.isArray(value.results), "invalid run results");
    return value.results.map(parseResult);
  })();
  if (item.state === "pending") {
    assert(results === undefined || results.length === 0, "pending run has terminal results");
  }
  if (item.state === "completed_with_findings") {
    assert(
      results?.length !== undefined
        && results.length > 0
        && results.some((result) => result.state === "mismatch")
        && results.every((result) => result.state === "match" || result.state === "mismatch"),
      "findings state has an incoherent result"
    );
    assert(warnings.some((warning) => warning.code === "MISMATCH"), "findings state has no mismatch warning");
  }
  if (item.state === "persisted") {
    assert(results === undefined || results.every((result) => result.state === "match"), "persisted run has unresolved results");
    assert(!warnings.some((warning) => ["INCONCLUSIVE", "MISMATCH", "NOT_VERIFIABLE", "PARTIAL_COVERAGE"].includes(warning.code)), "persisted run has a contradictory warning");
  }
  if (item.state === "not_verifiable") {
    assert(results?.length !== undefined && results.length > 0 && results.every((result) => result.state === "not_verifiable"), "not verifiable run has no contractual limitation");
    assert(warnings.some((warning) => warning.code === "NOT_VERIFIABLE"), "not verifiable run has no limitation warning");
  }
  if (item.state === "partial") {
    assert(warnings.some((warning) => warning.code === "PARTIAL_COVERAGE"), "partial run has no coverage warning");
    assert(results === undefined || results.every((result) => result.state === "match"), "partial run has a contradictory result");
  }
  if (item.state === "inconclusive") {
    assert(results?.length !== undefined && results.length > 0 && results.every((result) => result.state === "inconclusive"), "inconclusive run has no corresponding result");
    assert(warnings.some((warning) => warning.code === "INCONCLUSIVE"), "inconclusive run has no inconclusive warning");
  }
  return {
    ...item,
    scope: parseScope(value.scope),
    warnings,
    ...(results === undefined ? {} : { results })
  };
}

function parseRunPageData(value: unknown, asOf: string): RunsPageData {
  onlyKeys(value, ["items", "page"], ["items", "page"]);
  assert(Array.isArray(value.items), "invalid run items");
  const items = value.items.map((item) => parseRunItem(item, asOf));
  onlyKeys(value.page, ["nextCursor", "hasNext", "totalCount"], ["nextCursor", "hasNext", "totalCount"]);
  assert(value.page.nextCursor === null || isValidCursor(value.page.nextCursor), "invalid opaque cursor");
  assert(typeof value.page.hasNext === "boolean", "invalid cursor continuation flag");
  assert(value.page.totalCount === null || typeof value.page.totalCount === "number" && Number.isInteger(value.page.totalCount) && value.page.totalCount >= 0, "invalid total count");
  if (value.page.hasNext) {
    assert(isValidCursor(value.page.nextCursor), "continuation has no cursor");
  } else {
    assert(value.page.nextCursor === null, "end page has a cursor");
  }
  return {
    items,
    page: {
      nextCursor: value.page.nextCursor,
      hasNext: value.page.hasNext,
      totalCount: value.page.totalCount as number | null
    }
  };
}

function parseDataEnvelope<T>(envelope: Envelope, parser: (data: Record<string, unknown>) => T): Envelope<T> {
  assert(envelope.error === undefined, "error envelope used as data");
  assert(envelope.data !== null && isRecord(envelope.data), "successful response has no data");
  return { ...envelope, data: parser(envelope.data) };
}

function validateResponseContext(envelope: Envelope, context: { date: string; timezone: string }, { daily = false } = {}): void {
  assert(validDate(context.date) && validTimezone(context.timezone), "invalid query context");
  assert(envelope.timezone === context.timezone, "response timezone does not match query");
  if (daily) {
    assert(isRecord(envelope.data) && envelope.data.logicalDate === context.date, "response date does not match query");
    const requested = envelope.coverage.requested;
    assert(requested !== undefined && requested !== null, "daily response has no requested coverage");
    assert(requested.logicalDate === context.date, "coverage date does not match query");
    assert(requested.timezone === context.timezone, "coverage timezone does not match query");
    assert(envelope.coverage.expectedDays === 1, "daily response has invalid expected days");
    assert(Number.isInteger(envelope.coverage.availableDays) && (envelope.coverage.availableDays || 0) >= 0 && (envelope.coverage.availableDays || 0) <= 1, "daily response has invalid available days");
    assert(typeof envelope.coverage.isPartial === "boolean", "daily response has no partial flag");
  } else if (envelope.coverage.requested !== undefined && envelope.coverage.requested !== null) {
    assert(envelope.coverage.requested.timezone === context.timezone, "coverage timezone does not match query");
  }
}

export function parseSession(envelope: Envelope): Envelope<SessionData> {
  return parseDataEnvelope(envelope, (data) => {
    onlyKeys(data, ["authenticated", "accessState", "canReadVerification"], ["authenticated", "accessState", "canReadVerification"]);
    assert(typeof data.authenticated === "boolean" && typeof data.canReadVerification === "boolean", "invalid session flags");
    assert(typeof data.accessState === "string" && ["anonymous", "pending", "active", "blocked"].includes(data.accessState), "invalid access state");
    if (!data.authenticated) {
      assert(data.accessState === "anonymous" && data.canReadVerification === false, "anonymous session has access");
    } else {
      assert(data.accessState !== "anonymous", "authenticated session is anonymous");
      assert(data.canReadVerification === (data.accessState === "active"), "session access state mismatch");
    }
    return {
      authenticated: data.authenticated,
      accessState: data.accessState as AccessState,
      canReadVerification: data.canReadVerification
    };
  });
}

export function parseOverviewEnvelope(envelope: Envelope, context?: { date: string; timezone: string } | null): Envelope<OverviewData> {
  const parsed = parseDataEnvelope(envelope, (data) => {
    onlyKeys(data, ["logicalDate", "summary", "sources", "runs"], ["logicalDate", "summary"]);
    assert(validDate(data.logicalDate), "invalid overview date");
    onlyKeys(data.summary, Object.keys(METRIC_RULES));
    const summary: OverviewData["summary"] = {};
    for (const [key, metric] of Object.entries(data.summary)) {
      summary[key as keyof OverviewData["summary"]] = parseMetric(metric, {
        metricKey: key,
        heartRate: key === "heartRate",
        expectedUnit: METRIC_RULES[key]?.unit
      });
    }
    const sources = data.sources === undefined ? undefined : (() => {
      assert(Array.isArray(data.sources), "invalid overview sources");
      const parsedSources = data.sources.map(parseSource);
      const sourceKeys = new Set(parsedSources.map((source) => source.sourceKey));
      for (const metric of Object.values(summary)) {
        if (metric.sourceKey !== undefined) {
          assert(sourceKeys.has(metric.sourceKey), "metric source is not declared");
        }
      }
      return parsedSources;
    })();
    const runs = data.runs === undefined ? undefined : parseRunPageData(data.runs, envelope.asOf);
    return {
      logicalDate: data.logicalDate,
      summary,
      ...(sources === undefined ? {} : { sources }),
      ...(runs === undefined ? {} : { runs })
    };
  });
  if (context) {
    validateResponseContext(parsed, context, { daily: true });
  }
  return parsed;
}

export function parseActivityTrendEnvelope(envelope: Envelope, context?: { date: string; timezone: string } | null): Envelope<ActivityTrendData> {
  const parsed = parseDataEnvelope(envelope, (data) => {
    onlyKeys(data, ["logicalDate", "range", "steps", "distanceMeters", "points", "bucketMode"], ["logicalDate", "range", "steps", "distanceMeters", "points"]);
    assert(validDate(data.logicalDate) && ["daily", "7d", "monthly", "180d", "annual"].includes(String(data.range)), "invalid activity trend");
    const bucketMode = data.bucketMode === undefined ? "daily" : data.bucketMode;
    assert(bucketMode === "daily" || bucketMode === "calendar-month", "invalid activity trend buckets");
    const range = data.range as ActivityTrendData["range"];
    assert(
      (range === "daily" || range === "7d" || range === "monthly")
        ? bucketMode === "daily"
        : bucketMode === "calendar-month",
      "invalid activity trend bucket mode"
    );
    const expectedDays = range === "daily" ? 1 : range === "7d" ? 7 : range === "monthly" ? new Date(Date.UTC(Number(String(data.logicalDate).slice(0, 4)), Number(String(data.logicalDate).slice(5, 7)), 0)).getUTCDate() : range === "180d" ? 180 : (new Date(Date.UTC(Number(String(data.logicalDate).slice(0, 4)), 1, 29)).getUTCDate() === 29 ? 366 : 365);
    const parseAggregate = (value: unknown, unit: Exclude<MetricUnit, null>): ActivityTrendData["steps"] => {
      onlyKeys(value, ["unit", "totalObserved", "averageObserved", "observedDays", "expectedDays"], ["unit", "totalObserved", "averageObserved", "observedDays", "expectedDays"]);
       assert(value.unit === unit && typeof value.observedDays === "number" && Number.isInteger(value.observedDays) && value.observedDays >= 0 && value.observedDays <= expectedDays && value.expectedDays === expectedDays, "invalid trend aggregate");
      const totalObserved = parseNumber(value.totalObserved, true);
      const averageObserved = parseNumber(value.averageObserved, true);
      assert((totalObserved === null || totalObserved >= 0) && (averageObserved === null || averageObserved >= 0), "invalid trend aggregate values");
       return { unit, totalObserved, averageObserved, observedDays: value.observedDays as number, expectedDays };
    };
     assert(Array.isArray(data.points) && data.points.length > 0, "invalid trend points");
     const expectedDates = range === "daily" ? [String(data.logicalDate)] : range === "7d" ? Array.from({ length: 7 }, (_, index) => {
         const value = new Date(`${data.logicalDate}T00:00:00Z`);
         value.setUTCDate(value.getUTCDate() - (6 - index));
         return value.toISOString().slice(0, 10);
        }) : range === "monthly" ? Array.from({ length: new Date(Date.UTC(Number(String(data.logicalDate).slice(0, 4)), Number(String(data.logicalDate).slice(5, 7)), 0)).getUTCDate() }, (_, index) => `${String(data.logicalDate).slice(0, 7)}-${String(index + 1).padStart(2, "0")}`) : (() => {
          const end = new Date(`${String(data.logicalDate)}T00:00:00Z`);
          const start = range === "annual" ? new Date(Date.UTC(end.getUTCFullYear(), 0, 1)) : new Date(end.getTime() - 179 * 86400000);
          start.setUTCDate(1);
          const monthCount = range === "annual"
            ? 12
            : (end.getUTCFullYear() - start.getUTCFullYear()) * 12 + end.getUTCMonth() - start.getUTCMonth() + 1;
          return Array.from({ length: monthCount }, (_, index) => {
            const month = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + index, 1));
            return month.toISOString().slice(0, 7) + "-01";
          });
        })();
    const points = data.points.map((point) => {
      onlyKeys(point, ["date", "steps", "distanceMeters"], ["date", "steps", "distanceMeters"]);
        const parsePoint = (value: unknown, unit: MetricUnit): ActivityTrendPointMetric => { onlyKeys(value, ["state", "value", "unit"], ["state", "value", "unit"]); assert(typeof value.state === "string" && ["empty", "null", "zero", "value", "partial", "inconclusive", "source_ambiguous"].includes(value.state), "invalid trend point"); const parsed = parseNumber(value.value, true); assert(parsed === null || parsed >= 0, "invalid trend point value"); assert(!["empty", "null", "inconclusive"].includes(value.state) || parsed === null, "invalid trend point value"); assert(!["value", "partial", "source_ambiguous"].includes(value.state) || parsed !== null, "observed trend point has no value"); assert(value.state !== "zero" || parsed === 0, "invalid trend zero"); assert(["empty", "null", "inconclusive"].includes(value.state) || value.unit === unit, "invalid trend point unit"); return { state: value.state as MetricState, value: parsed, unit: value.unit as MetricUnit }; };
       return { date: String(point.date), steps: parsePoint(point.steps, "count"), distanceMeters: parsePoint(point.distanceMeters, "meters") };
    });
     assert(points.every((point, index) => point.date === expectedDates[index]) && new Set(points.map((point) => point.date)).size === expectedDates.length, "invalid trend dates");
     return { logicalDate: data.logicalDate as string, range, bucketMode: bucketMode as ActivityTrendData["bucketMode"], steps: parseAggregate(data.steps, "count"), distanceMeters: parseAggregate(data.distanceMeters, "meters"), points };
  });
  if (context) validateResponseContext(parsed, context);
  return parsed;
}

export function parseSourcesEnvelope(envelope: Envelope, context?: { date: string; timezone: string } | null): Envelope<{ items: Source[] }> {
  const parsed = parseDataEnvelope(envelope, (data) => {
    onlyKeys(data, ["items"], ["items"]);
    assert(Array.isArray(data.items), "invalid source items");
    return { items: data.items.map(parseSource) };
  });
  if (context) {
    validateResponseContext(parsed, context);
  }
  return parsed;
}

export function parseSettingsEnvelope(envelope: Envelope): Envelope<SettingsData> {
  return parseDataEnvelope(envelope, (data) => {
    onlyKeys(data, ["contract", "versions", "capabilities", "technicalState"], ["contract", "versions", "capabilities", "technicalState"]);
    assert(data.contract === "bff-ui-v1", "invalid contract name");
    onlyKeys(data.versions, ["bffSchema", "owReference"], ["bffSchema", "owReference"]);
    assert(data.versions.bffSchema === "1" && typeof data.versions.owReference === "string", "invalid versions");
    onlyKeys(data.capabilities, ["gps", "workoutDetails", "segments", "hrZones"], ["gps", "workoutDetails", "segments", "hrZones"]);
    for (const capability of Object.values(data.capabilities)) {
      assert(capability === "aggregate_only" || capability === "not_verifiable", "invalid settings capability");
    }
    assert(data.technicalState === "ready", "invalid technical state");
    return {
      contract: "bff-ui-v1",
      versions: { bffSchema: "1", owReference: OW_REFERENCE_NOT_PINNED },
      capabilities: data.capabilities as SettingsData["capabilities"],
      technicalState: "ready"
    };
  });
}

export function parseRunsEnvelope(envelope: Envelope): Envelope<RunsPageData> {
  return parseDataEnvelope(envelope, (data) => parseRunPageData(data, envelope.asOf));
}

export function parseRunDetailEnvelope(envelope: Envelope): Envelope<{ verificationRun: VerificationRun }> {
  return parseDataEnvelope(envelope, (data) => {
    onlyKeys(data, ["verificationRun"], ["verificationRun"]);
    return { verificationRun: parseRun(data.verificationRun, envelope.asOf) };
  });
}

function statusCodeFor(status: number): string {
  return ({
    400: "INVALID_QUERY",
    401: "SESSION_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "IDEMPOTENCY_CONFLICT",
    410: "CURSOR_EXPIRED",
    422: "INVALID_SCOPE",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "UPSTREAM_INVALID",
    503: "UPSTREAM_UNAVAILABLE",
    504: "UPSTREAM_TIMEOUT"
  } as Record<number, string>)[status] || "NETWORK_ERROR";
}

export function parseRetryAfter(value: string | null, now = Date.now()): number | null {
  if (!value) {
    return null;
  }
  if (/^\d+$/.test(value)) {
    const seconds = Number(value);
    return Number.isSafeInteger(seconds) && seconds <= 86_400 ? seconds * 1000 : null;
  }
  const deadline = Date.parse(value);
  if (!Number.isFinite(deadline)) {
    return null;
  }
  const delay = deadline - now;
  return delay >= 0 && delay <= 86_400_000 ? delay : null;
}

async function request(path: string, options: RequestInit = {}): Promise<Envelope> {
  try {
    const response = await fetch(path, {
      ...options,
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(options.headers || {})
      }
    });
    const responseRetryAfterMs = parseRetryAfter(response.headers.get("Retry-After"));
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new ApiError({
        status: response.status,
        code: response.ok ? "UPSTREAM_INVALID" : statusCodeFor(response.status),
        retryable: response.status === 429 || response.status >= 500,
        retryAfterMs: responseRetryAfterMs
      });
    }
    let envelope: Envelope;
    try {
      envelope = parseEnvelope(payload);
    } catch {
      throw new ApiError({
        status: response.status,
        code: response.ok ? "UPSTREAM_INVALID" : statusCodeFor(response.status),
        retryable: response.status === 429 || response.status >= 500,
        retryAfterMs: responseRetryAfterMs
      });
    }
    if (!response.ok || envelope.error !== undefined) {
      const error = envelope.error;
      throw new ApiError({
        status: response.status,
        code: error?.code || statusCodeFor(response.status),
        field: error?.field || null,
        retryable: error?.retryable === true,
        requestId: error?.requestId || null,
        retryAfterMs: responseRetryAfterMs
      });
    }
    return envelope;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof InvalidResponse) {
      throw new ApiError({ code: "MALFORMED_RESPONSE", retryable: false });
    }
    if (error instanceof Error && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError({ code: "NETWORK_ERROR", retryable: true });
  }
}

function queryUrl(path: string, params: Record<string, string | number | null | undefined> = {}): string {
  assert(Object.prototype.hasOwnProperty.call(QUERY_FIELDS, path), "route is not allowlisted");
  const allowed = new Set(QUERY_FIELDS[path]);
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    assert(allowed.has(key), "query field is not allowlisted");
    if (value === undefined || value === null || value === "") {
      continue;
    }
    assert(typeof value === "string" || typeof value === "number", "unsafe query value");
    const stringValue = String(value);
    assert(!/[\u0000-\u001f\u007f]/.test(stringValue), "unsafe query value");
    search.set(key, stringValue);
  }
  const encoded = search.toString();
  return encoded ? `${path}?${encoded}` : path;
}

function contextParams(context: { date: string; timezone: string }): { date: string; timezone: string } {
  if (!validDate(context?.date)) {
    throw invalidQuery("date");
  }
  if (!validTimezone(context?.timezone)) {
    throw invalidQuery("timezone");
  }
  return { date: context.date, timezone: context.timezone };
}

export function buildApiUrl(path: string, params: Record<string, string | number | null | undefined> = {}): string {
  return queryUrl(path, params);
}

export async function getSession({ signal }: { signal?: AbortSignal } = {}): Promise<Envelope<SessionData>> {
  return parseSession(await request(API_ROUTES.session, { signal }));
}

export async function getOverview(context: { date: string; timezone: string }, { signal }: { signal?: AbortSignal } = {}): Promise<Envelope<OverviewData>> {
  return parseOverviewEnvelope(await request(queryUrl(API_ROUTES.overview, contextParams(context)), { signal }), context);
}

export async function getActivityTrend(context: { date: string; timezone: string; range?: string }, { signal }: { signal?: AbortSignal } = {}): Promise<Envelope<ActivityTrendData>> {
  const params = contextParams(context);
  return parseActivityTrendEnvelope(await request(queryUrl(API_ROUTES.activityTrend, { ...params, range: context.range || "7d" }), { signal }), context);
}

export function parseSleepTrendEnvelope(envelope: Envelope, context?: { date: string; timezone: string } | null): Envelope<SleepTrendData> {
  const parsed = parseDataEnvelope(envelope, (data) => {
    onlyKeys(data, ["logicalDate", "range", "bucketMode", "nightSleepSeconds", "napsSeconds", "awakeSeconds", "lightSeconds", "deepSeconds", "remSeconds", "points", "observedDays", "averageBedtime", "averageWakeTime", "intervals"], ["logicalDate", "range", "bucketMode", "nightSleepSeconds", "napsSeconds", "points"]);
    assert(validDate(data.logicalDate) && ["daily", "7d", "monthly", "180d", "annual"].includes(String(data.range)), "invalid sleep trend");
    const range = data.range as ActivityTrendRange;
    assert((range === "daily" || range === "7d" || range === "monthly") ? data.bucketMode === "daily" : data.bucketMode === "calendar-month", "invalid sleep trend buckets");
    const year = Number(String(data.logicalDate).slice(0, 4));
    const month = Number(String(data.logicalDate).slice(5, 7));
    const expectedDays = range === "daily" ? 1 : range === "7d" ? 7 : range === "monthly" ? new Date(Date.UTC(year, month, 0)).getUTCDate() : range === "180d" ? 180 : new Date(Date.UTC(year, 1, 29)).getUTCDate() === 29 ? 366 : 365;
    const parseAggregate = (value: unknown): SleepTrendData["nightSleepSeconds"] => { onlyKeys(value, ["state", "unit", "totalObserved", "averageObserved", "observedDays", "expectedDays"], ["unit", "totalObserved", "averageObserved", "observedDays", "expectedDays"]); const observedDays = value.observedDays as number; assert(value.unit === "seconds" && Number.isInteger(observedDays) && observedDays >= 0 && observedDays <= expectedDays && value.expectedDays === expectedDays, "invalid sleep aggregate"); const totalObserved = parseNumber(value.totalObserved, true); const averageObserved = parseNumber(value.averageObserved, true); assert((totalObserved === null || totalObserved >= 0) && (averageObserved === null || averageObserved >= 0), "invalid sleep aggregate values"); const state = value.state === undefined ? undefined : String(value.state); assert(state === undefined || ["value", "empty", "source_ambiguous"].includes(state), "invalid sleep aggregate state"); assert(state === "source_ambiguous" ? totalObserved === null && averageObserved === null : observedDays === 0 ? totalObserved === null && averageObserved === null : totalObserved !== null && averageObserved !== null, "invalid sleep aggregate state"); assert(state !== "empty" || observedDays === 0, "invalid sleep aggregate state"); assert(state !== "value" || observedDays > 0, "invalid sleep aggregate state"); return { ...(state === undefined ? {} : { state: state as "value" | "empty" | "source_ambiguous" }), unit: "seconds", totalObserved, averageObserved, observedDays, expectedDays }; };
     const points = data.points as unknown[];
    assert(Array.isArray(points) && points.length > 0, "invalid sleep trend points");
    const parsePointMetric = (value: unknown): ActivityTrendPointMetric => { onlyKeys(value, ["state", "value", "unit"], ["state", "value", "unit"]); assert(typeof value.state === "string" && ["empty", "null", "zero", "value", "partial", "inconclusive", "source_ambiguous", "unsupported"].includes(value.state), "invalid sleep point"); const state = value.state as string; const parsed = parseNumber(value.value, true); assert(parsed === null || parsed >= 0, "invalid sleep point value"); assert(!["empty", "null", "inconclusive", "source_ambiguous", "unsupported"].includes(state) || parsed === null, "invalid sleep point value"); assert(!["value", "partial"].includes(state) || parsed !== null, "observed sleep point has no value"); assert(state !== "zero" || parsed === 0, "invalid sleep zero"); assert(["empty", "null", "inconclusive", "unsupported"].includes(state) || value.unit === "seconds", "invalid sleep point unit"); return { state: state as MetricState, value: parsed, unit: value.unit as MetricUnit }; };
    const expectedDates = range === "daily" ? [String(data.logicalDate)] : range === "7d" ? Array.from({ length: 7 }, (_, index) => { const value = new Date(`${data.logicalDate}T00:00:00Z`); value.setUTCDate(value.getUTCDate() - (6 - index)); return value.toISOString().slice(0, 10); }) : range === "monthly" ? Array.from({ length: new Date(Date.UTC(year, month, 0)).getUTCDate() }, (_, index) => `${String(data.logicalDate).slice(0, 7)}-${String(index + 1).padStart(2, "0")}`) : (() => { const end = new Date(`${data.logicalDate}T00:00:00Z`); const start = range === "annual" ? new Date(Date.UTC(year, 0, 1)) : new Date(end.getTime() - 179 * 86400000); start.setUTCDate(1); const count = range === "annual" ? 12 : (end.getUTCFullYear() - start.getUTCFullYear()) * 12 + end.getUTCMonth() - start.getUTCMonth() + 1; return Array.from({ length: count }, (_, index) => { const value = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + index, 1)); return value.toISOString().slice(0, 7) + "-01"; }); })();
    assert(points.length === expectedDates.length, "invalid sleep trend point count");
    const parsedPoints = points.map((value) => { onlyKeys(value, ["date", "nightSleepSeconds", "napsSeconds", "unclassifiedSeconds", "stages", "bedtime", "wakeTime"], ["date", "nightSleepSeconds", "napsSeconds", "stages", "bedtime", "wakeTime"]); assert(validDate(value.date), "invalid sleep point date"); onlyKeys(value.stages, ["awakeSeconds", "lightSeconds", "deepSeconds", "remSeconds"], ["awakeSeconds", "lightSeconds", "deepSeconds", "remSeconds"]); for (const timestamp of [value.bedtime, value.wakeTime]) assert(timestamp === null || validTimestamp(timestamp), "invalid sleep timestamp"); const nightSleepSeconds = parsePointMetric(value.nightSleepSeconds); const stages = { awakeSeconds: parsePointMetric(value.stages.awakeSeconds), lightSeconds: parsePointMetric(value.stages.lightSeconds), deepSeconds: parsePointMetric(value.stages.deepSeconds), remSeconds: parsePointMetric(value.stages.remSeconds) }; const unclassifiedSeconds = value.unclassifiedSeconds === undefined ? undefined : parsePointMetric(value.unclassifiedSeconds); if (nightSleepSeconds.value !== null && unclassifiedSeconds?.value !== null && unclassifiedSeconds?.value !== undefined) { const classified = [stages.lightSeconds, stages.deepSeconds, stages.remSeconds].reduce((total, metric) => total + (metric.value || 0), 0); assert(classified + unclassifiedSeconds.value === nightSleepSeconds.value, "invalid unclassified sleep remainder"); } return { date: value.date as string, nightSleepSeconds, napsSeconds: parsePointMetric(value.napsSeconds), ...(unclassifiedSeconds === undefined ? {} : { unclassifiedSeconds }), stages, bedtime: value.bedtime as string | null, wakeTime: value.wakeTime as string | null }; });
    assert(parsedPoints.every((point, index) => point.date === expectedDates[index]), "invalid sleep trend dates");
     assert(Number.isInteger(data.observedDays) && (data.observedDays as number) >= 0 && (data.observedDays as number) <= expectedDays && data.observedDays === (data.nightSleepSeconds as { observedDays: unknown }).observedDays, "invalid sleep observed days");
     const parseOptionalTimestamp = (value: unknown): string | null => {
       assert(value === null || validTimestamp(value), "invalid sleep timestamp");
       return value as string | null;
     };
     const averageBedtime = data.averageBedtime === undefined ? undefined : parseOptionalTimestamp(data.averageBedtime);
     const averageWakeTime = data.averageWakeTime === undefined ? undefined : parseOptionalTimestamp(data.averageWakeTime);
      let intervals: SleepTrendData["intervals"] | undefined;
      if (data.intervals !== undefined) {
        assert(Array.isArray(data.intervals), "invalid sleep intervals");
        assert(range === "daily" || data.intervals.length === 0, "sleep intervals are only available daily");
        let previousEnd = -Infinity;
       intervals = data.intervals.map((value) => {
         onlyKeys(value, ["start", "end", "category", "isNap"], ["start", "end", "category", "isNap"]);
         assert(validTimestamp(value.start) && validTimestamp(value.end), "invalid sleep interval timestamp");
         const start = Date.parse(value.start);
         const end = Date.parse(value.end);
         assert(start < end && start >= previousEnd, "invalid sleep interval ordering");
          assert(typeof value.category === "string" && ["sleeping", "awake", "light", "deep", "rem", "in_bed", "unknown"].includes(value.category), "invalid sleep interval category");
         assert(typeof value.isNap === "boolean", "invalid sleep interval nap flag");
         previousEnd = end;
          return { start: value.start, end: value.end, category: value.category as SleepInterval["category"], isNap: value.isNap };
       });
     }
     return { logicalDate: data.logicalDate as string, range, bucketMode: data.bucketMode as SleepTrendData["bucketMode"], nightSleepSeconds: parseAggregate(data.nightSleepSeconds), napsSeconds: parseAggregate(data.napsSeconds), awakeSeconds: parseAggregate(data.awakeSeconds), lightSeconds: parseAggregate(data.lightSeconds), deepSeconds: parseAggregate(data.deepSeconds), remSeconds: parseAggregate(data.remSeconds), observedDays: data.observedDays as number, points: parsedPoints, ...(averageBedtime === undefined ? {} : { averageBedtime }), ...(averageWakeTime === undefined ? {} : { averageWakeTime }), ...(intervals === undefined ? {} : { intervals }) };
  });
  if (context) validateResponseContext(parsed, context);
  return parsed;
}

export async function getSleepTrend(context: { date: string; timezone: string; range?: string }, { signal }: { signal?: AbortSignal } = {}): Promise<Envelope<SleepTrendData>> {
  const params = contextParams(context);
  return parseSleepTrendEnvelope(await request(queryUrl(API_ROUTES.sleepTrend, { ...params, range: context.range || "7d" }), { signal }), context);
}

export async function getSources(context: { date: string; timezone: string }, { signal }: { signal?: AbortSignal } = {}): Promise<Envelope<{ items: Source[] }>> {
  return parseSourcesEnvelope(await request(queryUrl(API_ROUTES.sources, contextParams(context)), { signal }), context);
}

export async function getSettings({ signal }: { signal?: AbortSignal } = {}): Promise<Envelope<SettingsData>> {
  return parseSettingsEnvelope(await request(API_ROUTES.settings, { signal }));
}

export async function getRuns(filters: Record<string, string | number | null | undefined> = {}, { signal }: { signal?: AbortSignal } = {}): Promise<Envelope<RunsPageData>> {
  const allowedFilterKeys = new Set(QUERY_FIELDS[API_ROUTES.runs]);
  for (const key of Object.keys(filters)) {
    if (!allowedFilterKeys.has(key)) {
      throw invalidQuery(null);
    }
  }
  const params: Record<string, string> = {};
  for (const key of ["from", "to", "state", "limit", "cursor"]) {
    const value = filters[key];
    if (value !== undefined && value !== null && value !== "") {
      params[key] = String(value);
    }
  }
  if (params.from !== undefined && !validDate(params.from)) {
    throw invalidQuery("from");
  }
  if (params.to !== undefined && !validDate(params.to)) {
    throw invalidQuery("to");
  }
  if (params.from !== undefined && params.to !== undefined && params.from > params.to) {
    throw invalidQuery("from");
  }
  if (params.state !== undefined && !SAFE_RUN_STATES.has(params.state)) {
    throw invalidQuery("state");
  }
  if (params.limit !== undefined && !/^(?:[1-9]|[1-9]\d|100)$/.test(params.limit)) {
    throw invalidQuery("limit");
  }
  if (params.cursor !== undefined && !isValidCursor(params.cursor)) {
    throw invalidQuery("cursor");
  }
  return parseRunsEnvelope(await request(queryUrl(API_ROUTES.runs, params), { signal }));
}

export function createIdempotencyKey(): IdempotencyKey {
  const cryptoApi = globalThis.crypto;
  try {
    let value: string | null = null;
    if (typeof cryptoApi?.randomUUID === "function") {
      const uuid = cryptoApi.randomUUID();
      if (typeof uuid === "string" && UUID_V4_PATTERN.test(uuid)) {
        value = `verify-ui-key-${uuid}`;
      }
    }
    if (!value && typeof cryptoApi?.getRandomValues === "function") {
      const bytes = new Uint8Array(16);
      cryptoApi.getRandomValues(bytes);
      value = `verify-ui-key-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
    }
    if (value) {
      const key = Object.freeze({});
      generatedIdempotencyKeys.add(key);
      idempotencyValues.set(key, value);
      return key as IdempotencyKey;
    }
  } catch {
    // Do not replace a failed secure source with a predictable value.
  }
  throw new ApiError({ code: "CLIENT_CRYPTO_UNAVAILABLE", retryable: false });
}

function idempotencyHeaderValue(value: unknown): string | null {
  if ((typeof value !== "object" && typeof value !== "function") || value === null || !generatedIdempotencyKeys.has(value)) {
    return null;
  }
  return idempotencyValues.get(value) || null;
}

export async function createVerificationRun({
  date,
  timezone,
  domains,
  idempotencyKey
}: {
  date: string;
  timezone: string;
  domains: string[];
  idempotencyKey?: IdempotencyKey;
}, { signal }: { signal?: AbortSignal } = {}): Promise<Envelope<{ verificationRun: VerificationRun }>> {
  if (!validDate(date)) {
    throw invalidQuery("date");
  }
  if (!validTimezone(timezone)) {
    throw invalidQuery("timezone");
  }
  if (!Array.isArray(domains) || domains.length === 0 || !domains.every((domain) => SAFE_DOMAINS.has(domain))) {
    throw invalidScope("domains");
  }
  const requestKey = idempotencyKey ?? createIdempotencyKey();
  const requestKeyValue = idempotencyHeaderValue(requestKey);
  if (!requestKeyValue) {
    throw invalidQuery("Idempotency-Key");
  }
  return parseRunDetailEnvelope(await request(API_ROUTES.runs, {
    method: "POST",
    signal,
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": requestKeyValue
    },
    body: JSON.stringify({ date, timezone, domains })
  }));
}

export async function getRunDetail(runKey: string, { signal }: { signal?: AbortSignal } = {}): Promise<Envelope<{ verificationRun: VerificationRun }>> {
  if (typeof runKey !== "string" || !RUN_KEY_PATTERN.test(runKey)) {
    throw invalidQuery("runKey");
  }
  const path = `${API_ROUTES.runs}/${encodeURIComponent(runKey)}`;
  return parseRunDetailEnvelope(await request(path, { signal }));
}
