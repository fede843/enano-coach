export type RouteName = "overview" | "sources" | "runs" | "detail" | "settings" | "unknown";

export interface AppRoute {
  name: RouteName;
  path: string;
  runKey?: string;
}

export type AccessState = "anonymous" | "pending" | "active" | "blocked";
export type SessionStatus = "loading" | "ready";
export type PageStatus = "idle" | "loading" | "ready" | "error";

export type MetricState =
  | "empty"
  | "error"
  | "inconclusive"
  | "not_verifiable"
  | "null"
  | "partial"
  | "pending"
  | "source_ambiguous"
  | "unsupported"
  | "value"
  | "zero";

export type RunState =
  | "cancelled"
  | "completed_with_findings"
  | "failed"
  | "inconclusive"
  | "not_verifiable"
  | "partial"
  | "pending"
  | "persisted"
  | "skipped";

export type SourceState = "ready" | "source_ambiguous";
export type WarningSeverity = "info" | "warning";

export interface Warning {
  code: string;
  severity: WarningSeverity;
  domain?: string;
}

export interface MetricCoverage {
  expectedDays: number;
  availableDays: number;
  observedFraction: number;
}

export type MetricUnit =
  | "bpm"
  | "celsius"
  | "cm"
  | "count"
  | "kcal"
  | "kg"
  | "m_per_s"
  | "meters"
  | "ms"
  | "percent"
  | "rpm"
  | "seconds"
  | "watts"
  | null;

export interface Metric {
  state: MetricState;
  value: number | null;
  unit: MetricUnit;
  isDailyTotal: boolean | null;
  sourceKey?: string;
  coverage?: MetricCoverage;
}

export interface RequestedCoverage {
  logicalDate: string;
  from: string;
  to: string;
  timezone: string;
}

export interface DomainCoverage {
  expectedDays: number | null;
  availableDays: number | null;
  state: "complete" | "empty" | "inconclusive" | "not_verifiable" | "partial" | "relative_to_now" | "unsupported";
}

export interface Coverage {
  requested?: RequestedCoverage | null;
  expectedDays?: number | null;
  availableDays?: number | null;
  isPartial?: boolean;
  byDomain?: Partial<Record<"activity" | "body" | "recovery" | "sleep" | "workouts", DomainCoverage>>;
}

export interface Extensions {
  fixture?: { synthetic: true; case: string };
  capabilities?: Partial<Record<"gps" | "workoutDetails" | "segments" | "hrZones", "aggregate_only" | "not_verifiable">>;
}

export interface ApiErrorPayload {
  code: string;
  retryable: boolean;
  requestId: string;
  field: string | null;
}

export interface Envelope<T = unknown> {
  schemaVersion: "1";
  asOf: string;
  timezone: string;
  data: T | null;
  coverage: Coverage;
  warnings: Warning[];
  extensions: Extensions;
  error?: ApiErrorPayload;
}

export interface SessionData {
  authenticated: boolean;
  accessState: AccessState;
  canReadVerification: boolean;
}

export interface Source {
  sourceKey: string;
  label: string;
  state: SourceState;
  capabilities: Array<"activity" | "body" | "heart_rate" | "sleep">;
  lastObservedAt?: string | null;
}

export interface OverviewData {
  logicalDate: string;
  summary: Partial<Record<"steps" | "distanceMeters" | "activeCaloriesKcal" | "sleepDurationSeconds" | "recoveryScore" | "stress" | "heartRate", Metric>>;
  sources?: Source[];
  runs?: RunsPageData;
}

export type ActivityTrendRange = "daily" | "7d" | "monthly" | "180d" | "annual";
export interface ActivityTrendMetric { unit: Exclude<MetricUnit, null>; totalObserved: number | null; averageObserved: number | null; observedDays: number; expectedDays: number }
export interface ActivityTrendPointMetric { state: MetricState; value: number | null; unit: MetricUnit }
export interface ActivityTrendData { logicalDate: string; range: ActivityTrendRange; bucketMode: "daily" | "calendar-month"; steps: ActivityTrendMetric; distanceMeters: ActivityTrendMetric; points: Array<{ date: string; steps: ActivityTrendPointMetric; distanceMeters: ActivityTrendPointMetric }> }

export interface RunCounts {
  recordsSeen: number | null;
  recordsAccepted: number | null;
  recordsRejected: number | null;
  recordsDuplicated: number | null;
  fieldsUnsupported: number | null;
}

export interface VerificationResult {
  metric: "extended_workout_detail" | "steps";
  state: "inconclusive" | "match" | "mismatch" | "not_verifiable";
  reasonCode?: "CURSOR_EXPIRED" | "NO_PUBLIC_WORKOUT_DETAIL";
  expected?: number;
  observed?: number;
  unit?: Exclude<MetricUnit, null>;
  expectedIsDailyTotal?: boolean;
  observedIsDailyTotal?: boolean;
}

export interface RunItem {
  runKey: string;
  state: RunState;
  requestedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  counts: RunCounts;
}

export interface RunScope {
  date: string;
  timezone: string;
  domains: Array<"activity" | "sleep" | "recovery" | "body" | "workouts" | "sources">;
}

export interface VerificationRun extends RunItem {
  scope: RunScope;
  warnings: Warning[];
  results?: VerificationResult[] | null;
}

export interface RunsPageData {
  items: RunItem[];
  page: {
    nextCursor: string | null;
    hasNext: boolean;
    totalCount: number | null;
  };
}

export interface SettingsData {
  contract: "bff-ui-v1";
  versions: { bffSchema: "1"; owReference: "not_pinned" };
  capabilities: {
    gps: "aggregate_only" | "not_verifiable";
    workoutDetails: "aggregate_only" | "not_verifiable";
    segments: "aggregate_only" | "not_verifiable";
    hrZones: "aggregate_only" | "not_verifiable";
  };
  technicalState: "ready";
}

export interface PageState {
  status: PageStatus;
  envelope: Envelope | null;
  error: import("./api").ApiError | null;
}

export interface RunsState {
  filters: { from: string; to: string; state: string };
  items: RunItem[];
  nextCursor: string | null;
  hasNext: boolean;
  loadingMore: boolean;
  error: import("./api").ApiError | null;
  createError: import("./api").ApiError | null;
  createKey: import("./api").IdempotencyKey | null;
  seenCursors: Set<string>;
  creating: boolean;
}

export interface AppState {
  route: AppRoute;
  context: { date: string; timezone: string };
  sessionStatus: SessionStatus;
  session: Envelope<SessionData> | null;
  sessionError: import("./api").ApiError | null;
  retryUntil: number | null;
  retryError: import("./api").ApiError | null;
  page: PageState;
  activityTrend?: PageState;
  runs: RunsState;
}
