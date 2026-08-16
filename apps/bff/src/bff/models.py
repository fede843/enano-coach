from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

from .errors import ErrorCode

Number = StrictInt | StrictFloat
Timestamp = str
LogicalDate = str
MetricUnit = Literal[
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
]
MetricState = Literal[
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
]
RunState = Literal[
    "cancelled",
    "completed_with_findings",
    "failed",
    "inconclusive",
    "not_verifiable",
    "partial",
    "pending",
    "persisted",
    "skipped",
]
WarningCode = Literal[
    "BODY_RELATIVE_TO_NOW",
    "CURSOR_EXPIRED",
    "INCONCLUSIVE",
    "MISMATCH",
    "NOT_VERIFIABLE",
    "PARTIAL_COVERAGE",
    "SOURCE_AMBIGUOUS",
    "UNSUPPORTED",
    "UPSTREAM_LIMITED",
]
WARNING_COPY_BY_CODE: dict[WarningCode, frozenset[str]] = {
    "BODY_RELATIVE_TO_NOW": frozenset({"Body es relativo al momento de consulta."}),
    "CURSOR_EXPIRED": frozenset(
        {"La p\u00e1gina solicitada expir\u00f3; reinicia el listado."}
    ),
    "INCONCLUSIVE": frozenset(
        {"No se pudo cerrar la comparaci\u00f3n porque falt\u00f3 una p\u00e1gina."}
    ),
    "MISMATCH": frozenset({"El hecho observado no coincide con el esperado."}),
    "NOT_VERIFIABLE": frozenset(
        {"La API p\u00fablica no ofrece el schema necesario para esta afirmaci\u00f3n."}
    ),
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
    "UNSUPPORTED": frozenset(
        {"La capacidad solicitada no est\u00e1 disponible en el contrato."}
    ),
    "UPSTREAM_LIMITED": frozenset({"La fuente limit\u00f3 el alcance de la consulta."}),
}
# None means an optional domain with no fixed mapping; an empty set means the
# warning is query-level and must not carry a health-domain label.
WARNING_DOMAIN_RULES: dict[WarningCode, frozenset[str] | None] = {
    "BODY_RELATIVE_TO_NOW": frozenset({"body"}),
    "CURSOR_EXPIRED": frozenset(),
    "INCONCLUSIVE": None,
    "MISMATCH": None,
    "NOT_VERIFIABLE": None,
    "PARTIAL_COVERAGE": None,
    "SOURCE_AMBIGUOUS": None,
    "UNSUPPORTED": None,
    "UPSTREAM_LIMITED": frozenset(),
}
WarningSeverity = Literal["info", "warning"]
WarningDomain = Literal[
    "activity",
    "body",
    "heart_rate",
    "recovery",
    "sleep",
    "workouts",
]
SourceState = Literal["ready", "source_ambiguous"]
SourceCapability = Literal["activity", "body", "heart_rate", "sleep"]
AccessState = Literal["anonymous", "pending", "active", "blocked"]
Domain = Literal["activity", "sleep", "recovery", "body", "workouts", "sources"]
ResultMetric = Literal["extended_workout_detail", "steps"]
ResultState = Literal["inconclusive", "match", "mismatch", "not_verifiable"]
CapabilityValue = Literal["aggregate_only", "not_verifiable"]
CursorToken = str


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class ErrorBody(StrictModel):
    code: ErrorCode
    message: str
    requestId: str
    retryable: StrictBool
    field: str | None

    @field_validator("message")
    @classmethod
    def reject_untrusted_message(cls, value: str) -> str:
        if value not in {
            "A session is required for this query.",
            "Access to this query is blocked.",
            "This account does not have access to this query yet.",
            "The cursor does not match this list context.",
            "The cursor is not valid for this list.",
            "The requested page expired; restart the list.",
            "This method is not allowed.",
            "The request conflicts with an existing operation.",
            "The request could not be completed.",
            "This request is not allowed.",
            "The request limit was reached.",
            "The requested resource was not found.",
            "The requested verification was not found.",
            "The verification scope is not valid.",
            "The source returned an invalid response.",
            "The source is unavailable; query again manually.",
            "The source took too long to respond.",
            "The session has expired.",
            "The query is not valid.",
        }:
            raise ValueError("message is not BFF-owned")
        return value

    @field_validator("requestId")
    @classmethod
    def validate_request_id(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"req-demo-[a-z0-9-]+", value):
            raise ValueError("request id is not synthetic")
        return value


class WarningModel(StrictModel):
    code: WarningCode
    severity: WarningSeverity
    message: str
    domain: WarningDomain | None = None

    @field_validator("message")
    @classmethod
    def validate_warning_copy(cls, value: str) -> str:
        if not any(value in variants for variants in WARNING_COPY_BY_CODE.values()):
            raise ValueError("warning copy is not BFF-owned")
        return value

    @model_validator(mode="after")
    def validate_warning_domain(self) -> WarningModel:
        if self.message not in WARNING_COPY_BY_CODE[self.code]:
            raise ValueError("warning copy is not valid for this code")
        allowed_domains = WARNING_DOMAIN_RULES[self.code]
        if (
            self.domain is not None
            and allowed_domains is not None
            and self.domain not in allowed_domains
        ):
            raise ValueError("warning domain is not valid for this code")
        return self


class RequestedCoverage(StrictModel):
    logicalDate: LogicalDate
    from_: Timestamp = Field(alias="from")
    to: Timestamp
    timezone: str

    @field_validator("logicalDate")
    @classmethod
    def validate_logical_date(cls, value: str) -> str:
        import re
        from datetime import date

        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("invalid logical date")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("invalid logical date") from exc
        return value


class DomainCoverage(StrictModel):
    expectedDays: StrictInt | None
    availableDays: StrictInt | None
    state: Literal[
        "complete",
        "empty",
        "inconclusive",
        "not_verifiable",
        "partial",
        "relative_to_now",
        "unsupported",
    ]


class DomainCoverageMap(StrictModel):
    activity: DomainCoverage | None = None
    body: DomainCoverage | None = None
    recovery: DomainCoverage | None = None
    sleep: DomainCoverage | None = None
    workouts: DomainCoverage | None = None


class Coverage(StrictModel):
    requested: RequestedCoverage | None = None
    expectedDays: StrictInt | None = None
    availableDays: StrictInt | None = None
    isPartial: StrictBool | None = None
    byDomain: DomainCoverageMap | None = None


class MetricCoverage(StrictModel):
    expectedDays: StrictInt
    availableDays: StrictInt
    observedFraction: Number


class Metric(StrictModel):
    state: MetricState
    value: Number | None
    unit: MetricUnit | None
    isDailyTotal: StrictBool | None
    sourceKey: str | None = None
    coverage: MetricCoverage | None = None


class HeartRateMetric(StrictModel):
    state: MetricState
    value: Number | None
    unit: Literal["bpm"] | None
    isDailyTotal: StrictBool | None


class OverviewSummary(StrictModel):
    steps: Metric | None = None
    distanceMeters: Metric | None = None
    activeCaloriesKcal: Metric | None = None
    sleepDurationSeconds: Metric | None = None
    recoveryScore: Metric | None = None
    stress: Metric | None = None
    heartRate: HeartRateMetric | None = None


class SourceItem(StrictModel):
    sourceKey: str
    label: str
    state: SourceState
    capabilities: list[SourceCapability]
    lastObservedAt: Timestamp | None = None

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        if value not in {
            "Fuente sintética A",
            "Fuente sintética B",
            "Fuente sintética",
        }:
            raise ValueError("label is not BFF-owned")
        return value


class SourceData(StrictModel):
    items: list[SourceItem]


class RunCounts(StrictModel):
    recordsSeen: StrictInt | None
    recordsAccepted: StrictInt | None
    recordsRejected: StrictInt | None
    recordsDuplicated: StrictInt | None
    fieldsUnsupported: StrictInt | None


class RunScope(StrictModel):
    date: LogicalDate
    timezone: str
    domains: list[Domain]

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        import re
        from datetime import date

        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("invalid date")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("invalid date") from exc
        return value


class VerificationResult(StrictModel):
    metric: ResultMetric
    state: ResultState
    reasonCode: str | None = None
    expected: Number | None = None
    observed: Number | None = None
    unit: MetricUnit | None = None
    expectedIsDailyTotal: StrictBool | None = None
    observedIsDailyTotal: StrictBool | None = None


class RunListItem(StrictModel):
    runKey: str
    state: RunState
    requestedAt: Timestamp
    startedAt: Timestamp | None
    finishedAt: Timestamp | None
    counts: RunCounts


class VerificationRun(RunListItem):
    scope: RunScope
    warnings: list[WarningModel]
    results: list[VerificationResult] | None = None


class RunPage(StrictModel):
    nextCursor: CursorToken | None
    hasNext: StrictBool
    totalCount: StrictInt | None


class RunListData(StrictModel):
    items: list[RunListItem]
    page: RunPage


class RunDetailData(StrictModel):
    verificationRun: VerificationRun


class OverviewData(StrictModel):
    logicalDate: LogicalDate
    summary: OverviewSummary
    sources: list[SourceItem] | None = None
    runs: RunListData | None = None


class SessionData(StrictModel):
    authenticated: StrictBool
    accessState: AccessState
    canReadVerification: StrictBool


class SettingsVersions(StrictModel):
    bffSchema: Literal["1"]
    owReference: Literal["not_pinned"]


class SettingsCapabilities(StrictModel):
    gps: CapabilityValue
    workoutDetails: CapabilityValue
    segments: CapabilityValue
    hrZones: CapabilityValue


class SettingsData(StrictModel):
    contract: Literal["bff-ui-v1"]
    versions: SettingsVersions
    capabilities: SettingsCapabilities
    technicalState: Literal["ready"]


class FixtureExtension(StrictModel):
    synthetic: StrictBool
    case: str


class CapabilityExtension(StrictModel):
    gps: CapabilityValue | None = None
    workoutDetails: CapabilityValue | None = None
    segments: CapabilityValue | None = None
    hrZones: CapabilityValue | None = None


class Extensions(StrictModel):
    fixture: FixtureExtension | None = None
    capabilities: CapabilityExtension | None = None


DataT = TypeVar("DataT", bound=StrictModel)


class Envelope(StrictModel, Generic[DataT]):
    schemaVersion: Literal["1"] = "1"
    asOf: Timestamp
    timezone: str
    data: DataT | None
    coverage: Coverage
    warnings: list[WarningModel]
    extensions: Extensions
    error: ErrorBody | None = None


class CreateRunBody(StrictModel):
    date: str = Field(min_length=1, max_length=10)
    timezone: str = Field(min_length=1, max_length=64)
    domains: list[Domain] = Field(min_length=1, max_length=6)
