import { type FormEvent, type MouseEvent, type ReactElement } from "react";

import { ApiError, ERROR_COPY } from "./api";
import {
  CAPABILITY_COPY,
  DOMAIN_LABELS,
  METRIC_DOMAINS,
  METRIC_LABELS,
  METRIC_ORDER,
  NAV_ITEMS,
  PAGE_COPY,
  RESULT_REASON_COPY,
  RUN_FILTER_STATES,
  SOURCE_CAPABILITY_LABELS,
  TIMEZONES
} from "./copy";
import { isRetryBlocked, retryGateRemaining } from "./controller-state";
import {
  formatCount,
  formatCoverageFraction,
  formatMetricDetail,
  formatMetricValue,
  formatNumber,
  formatResultNumber,
  formatTimestamp,
  formatUtcTimestamp,
  safeStateCopy,
  stateLabel,
  warningText
} from "./format";
import { hasUsableNextPage, isCursorResetError } from "./runs";
import { validationErrorId } from "./validation";
import type {
  AppState,
  Envelope,
  Metric,
  OverviewData,
  ActivityTrendData,
  SleepTrendData,
  ActivityTrendRange,
  RunItem,
  SettingsData,
  Source,
  VerificationResult,
  VerificationRun
} from "./types";

const STATE_SYMBOLS: Record<string, string> = {
  good: "✓",
  warn: "!",
  bad: "x",
  neutral: "-",
  accent: "0"
};

const VALIDATION_FIELD_COPY: Record<string, string> = {
  date: "Revisa la fecha seleccionada.",
  timezone: "Revisa la zona horaria.",
  from: "Revisa la fecha inicial.",
  to: "Revisa la fecha final.",
  state: "Revisa el estado seleccionado."
};

export type ViewAction = "next-page" | "reset-runs" | "retry" | "retry-create" | "create-run";

export interface ViewActions {
  navigate(path: string): void;
  onRouteClick(event: MouseEvent<HTMLAnchorElement>, path: string): void;
  onContextSubmit(event: FormEvent<HTMLFormElement>): void;
  onRunsSubmit(event: FormEvent<HTMLFormElement>): void;
  onAction(action: ViewAction): void;
  trendRange?: ActivityTrendRange;
  setTrendRange?(range: ActivityTrendRange): void;
  setTrendDate?(date: string): void;
  shiftTrend?(direction: -1 | 1): void;
  trendRanges?: Array<{ value: ActivityTrendRange; label: string }>;
  sleepRange?: ActivityTrendRange;
  setSleepRange?(range: ActivityTrendRange): void;
  shiftSleep?(direction: -1 | 1): void;
  sleepDate?: string;
  setSleepDate?(date: string): void;
  sleepMode?: SleepDisplayMode;
  setSleepMode?(mode: SleepDisplayMode): void;
}

export type SleepDisplayMode = "schedule" | "duration";

function currentNav(routeName: AppState["route"]["name"]): string {
  if (routeName === "detail") {
    return "/verify/runs";
  }
  return {
    overview: "/verify",
    sources: "/verify/sources",
    runs: "/verify/runs",
    settings: "/verify/settings"
  }[routeName as "overview" | "sources" | "runs" | "settings"] || "/verify";
}

function stateBadge(state: string, compact = false): ReactElement {
  const copy = safeStateCopy(state);
  const symbol = STATE_SYMBOLS[copy.tone] || "-";
  return (
    <span className={`state-pill tone-${copy.tone}${compact ? " compact" : ""}`} title={copy.detail}>
      <span aria-hidden="true">{symbol}</span>{copy.label}
    </span>
  );
}

function pageHeading(state: AppState): ReactElement {
  const copy = PAGE_COPY[state.route.name as keyof typeof PAGE_COPY] || PAGE_COPY.overview;
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{copy.eyebrow}</p>
        <h1>{copy.title}</h1>
        <p className="page-description">{copy.description}</p>
      </div>
      <div className="heading-mark" aria-hidden="true"><span>SOLO</span><strong>LECTURA</strong></div>
    </div>
  );
}

function renderNav(state: AppState, actions: ViewActions): ReactElement {
  const active = currentNav(state.route.name);
  return (
    <>
      <nav className="side-nav" aria-label="Navegación principal">
        <p className="nav-kicker">MAPA DE LECTURA</p>
        <div className="nav-links">
          {NAV_ITEMS.map((item) => (
            <a
              className={`nav-link${item.route === active ? " is-active" : ""}`}
              href={item.route}
              key={item.route}
              aria-current={item.route === active ? "page" : undefined}
              onClick={(event) => actions.onRouteClick(event, item.route)}
            >
              <span className="nav-index" aria-hidden="true">{item.mark}</span>
              <span>{item.label}</span>
            </a>
          ))}
        </div>
        <div className="nav-footnote"><span className="footnote-dot" /><span>Sin mutaciones<br />Sin datos offline</span></div>
      </nav>
      <nav className="mobile-nav" aria-label="Navegación móvil">
        {NAV_ITEMS.map((item) => (
          <a
            className={`mobile-nav-link${item.route === active ? " is-active" : ""}`}
            href={item.route}
            key={item.route}
            aria-current={item.route === active ? "page" : undefined}
            onClick={(event) => actions.onRouteClick(event, item.route)}
          >
            <span aria-hidden="true">{item.mark}</span><span>{item.shortLabel}</span>
          </a>
        ))}
      </nav>
    </>
  );
}

function renderHeader(state: AppState, actions: ViewActions): ReactElement {
  return (
    <header className="topbar">
      <a className="brand" href="/verify" aria-label="Enano Coach, ir a verificación" onClick={(event) => actions.onRouteClick(event, "/verify")}>
        <span className="brand-mark" aria-hidden="true">E</span>
        <span className="brand-copy"><strong>ENANO</strong><span>COACH / LECTURA</span></span>
      </a>
      <div className="topbar-context">
        <span className="read-only-chip"><span aria-hidden="true">●</span> SOLO LECTURA</span>
        <span className="topbar-zone">Zona efectiva: <strong>{state.context.timezone}</strong></span>
      </div>
    </header>
  );
}

function invalidField(error: ApiError | null | undefined, field: string): boolean {
  return error?.code === "INVALID_QUERY" && error.field === field;
}

function fieldValidationProps(error: ApiError | null | undefined, field: string): { "aria-invalid": true | undefined; "aria-describedby": string | undefined } {
  const invalid = invalidField(error, field);
  return {
    "aria-invalid": invalid ? true : undefined,
    "aria-describedby": invalid ? validationErrorId(field) || undefined : undefined
  };
}

function fieldValidationMessage(error: ApiError | null | undefined, field: string): ReactElement | null {
  const errorId = validationErrorId(field);
  if (!invalidField(error, field) || !errorId) return null;
  return <span id={errorId} className="field-error">{VALIDATION_FIELD_COPY[field] || "Revisa este campo."}</span>;
}

function contextForm(state: AppState, actions: ViewActions, label = "Ventana"): ReactElement {
  const disabled = isRetryBlocked(state.retryUntil);
  const error = state.page.error;
  return (
    <form className="context-form" data-form="context" key={`${state.context.date}-${state.context.timezone}`} onSubmit={actions.onContextSubmit}>
      <div className="field-group" data-invalid={invalidField(error, "date") || undefined}>
        <label htmlFor="context-date">{label} <span>fecha lógica</span></label>
        <input id="context-date" name="date" type="date" autoComplete="off" defaultValue={state.context.date} required {...fieldValidationProps(error, "date")} />
        {fieldValidationMessage(error, "date")}
      </div>
      <div className="field-group" data-invalid={invalidField(error, "timezone") || undefined}>
        <label htmlFor="context-timezone">Zona horaria <span>IANA</span></label>
        <select id="context-timezone" name="timezone" autoComplete="off" defaultValue={state.context.timezone} {...fieldValidationProps(error, "timezone")}>
          {TIMEZONES.map((zone) => <option value={zone} key={zone}>{zone}</option>)}
        </select>
        {fieldValidationMessage(error, "timezone")}
      </div>
      <button className="button button-primary" type="submit" disabled={disabled}><span aria-hidden="true">↗</span> Consultar</button>
    </form>
  );
}

function coveragePanel(envelope: Envelope): ReactElement {
  const coverage = envelope.coverage;
  const requested = coverage.requested;
  const expected = coverage.expectedDays;
  const available = coverage.availableDays;
  const isEmpty = available === 0 && coverage.isPartial === false;
  const ratio = isEmpty
    ? "Sin observaciones"
    : expected === null || expected === undefined || available === null || available === undefined
      ? "No aplica"
      : `${available} / ${expected} días`;
  const partial = coverage.isPartial === true;
  return (
    <section className="coverage-panel" aria-labelledby="coverage-title">
      <div className="panel-rule"><span /><span /><span /></div>
      <div className="coverage-main">
        <div>
          <p className="eyebrow">COBERTURA DE LA VENTANA</p>
          <h2 id="coverage-title">{ratio}</h2>
          <p className="coverage-caption">{partial ? "Hay datos, pero la ventana no está completa." : "La cobertura describe el alcance; no convierte la ausencia en un valor."}</p>
        </div>
        <div className="coverage-state">{stateBadge(partial ? "partial" : available === 0 ? "empty" : "value")}</div>
      </div>
      <div className="coverage-meta">
        <div><span>Fecha lógica</span><strong>{requested?.logicalDate || "No disponible"}</strong></div>
        <div><span>Zona aplicada</span><strong>{requested?.timezone || envelope.timezone}</strong></div>
        <div><span>Ventana UTC</span><strong>{requested ? `${requested.from} → ${requested.to}` : "No disponible"}</strong></div>
        <div><span>Generado / UTC</span><strong>{formatUtcTimestamp(envelope.asOf)}</strong></div>
      </div>
    </section>
  );
}

function warningsPanel(warnings: Envelope["warnings"], title = "Advertencias de lectura"): ReactElement {
  if (warnings.length === 0) {
    return <div className="quiet-note"><span aria-hidden="true">✓</span> No hay advertencias públicas para esta respuesta.</div>;
  }
  return (
    <section className="warnings-panel" aria-labelledby="warnings-title">
      <div className="section-heading compact-heading"><div><p className="eyebrow">SEÑALES A CONSERVAR</p><h2 id="warnings-title">{title}</h2></div><span className="warning-count">{warnings.length}</span></div>
      <ul className="warning-list">
        {warnings.map((warning, index) => (
          <li key={`${warning.code}-${index}`}><span className="warning-symbol" aria-hidden="true">!</span><div><strong>{warningText(warning)}</strong><span>{warning.code}{warning.domain ? ` · ${warning.domain}` : ""}</span></div></li>
        ))}
      </ul>
    </section>
  );
}

function metricCard(key: string, metric: Metric): ReactElement {
  const copy = safeStateCopy(metric.state);
  const formatted = formatMetricValue(metric);
  return (
    <article className={`metric-card tone-${copy.tone} state-${metric.state}`}>
      <div className="metric-topline"><span className="metric-domain">{METRIC_DOMAINS[key] || "Lectura"}</span>{stateBadge(metric.state, true)}</div>
      <h2>{METRIC_LABELS[key] || "Lectura"}</h2>
      <div className="metric-reading"><strong>{formatted.isValue ? formatted.value : "—"}</strong><span>{formatted.isValue ? formatted.unit : ""}</span></div>
      <p className="metric-detail">{formatMetricDetail(key, metric)}</p>
      <div className="metric-footer"><span>Estado: {copy.label}</span>{metric.coverage ? <span>{formatCoverageFraction(metric.coverage)}</span> : null}</div>
    </article>
  );
}

function emptyOverview(envelope: Envelope): ReactElement {
  return (
    <section className="empty-state" aria-labelledby="empty-title">
      <div className="empty-stamp">Ventana vacía</div>
      <h2 id="empty-title">No hay datos para esta ventana</h2>
      <p>La ventana está completa y no contiene observaciones. Es distinto de un cero confirmado y de una medición nula.</p>
      <span className="empty-context">{envelope.coverage.requested?.logicalDate || "Fecha no disponible"} · {envelope.timezone}</span>
    </section>
  );
}

function emptySources(context: AppState["context"]): ReactElement {
  return (
    <section className="empty-state source-empty-state" aria-labelledby="source-empty-title">
      <div className="empty-stamp">Inventario de proveniencia</div>
      <h2 id="source-empty-title">No hay fuentes declaradas para esta consulta</h2>
      <p>El inventario de proveniencia no devolvió fuentes para la fecha y zona solicitadas. Esto no determina la cobertura diaria ni la existencia de datos de salud.</p>
      <span className="empty-context">Fecha consultada: {context.date} · Zona: {context.timezone}</span>
    </section>
  );
}

function scopeNote(envelope: Envelope): ReactElement {
  const gps = envelope.extensions.capabilities?.gps === "not_verifiable";
  return (
    <aside className="scope-note" aria-label="Límite de esta vista">
      <div className="scope-note-mark" aria-hidden="true">↳</div>
      <div><strong>La vista preserva el límite de la evidencia.</strong><p>{gps ? "GPS figura solo como no verificable; no hay mapa, ruta ni coordenadas en esta vista." : "No se agregan rutas, muestras ni detalles que el contrato no publica."}</p></div>
    </aside>
  );
}

export function trendPointText(state: string, value: number | null, unit: string): string {
  if (state === "empty") return "Ausente";
  if (state === "null") return "Sin medición";
  if (state === "partial" && value === null) return "Parcial";
  if (state === "source_ambiguous") return "Fuente ambigua";
  if (state === "inconclusive") return "Inconclusa";
  if (value === null) return "Sin medición";
  return `${value.toLocaleString("es-ES")} ${unit}`;
}

function trendQuickLabel(range: ActivityTrendRange): string {
  return { daily: "Diario", "7d": "7D", monthly: "1M", "180d": "180D", annual: "Anual" }[range];
}

export function formatTrendRangeLabel(range: ActivityTrendRange): string {
  return {
    daily: "Diario",
    "7d": "7 días",
    monthly: "Mensual",
    "180d": "180 días",
    annual: "Anual"
  }[range];
}

export function formatTrendBucketLabel(date: string): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  if (!Number.isFinite(parsed.getTime())) return date;
  return new Intl.DateTimeFormat("es-ES", { month: "long", year: "numeric", timeZone: "UTC" }).format(parsed);
}

export function formatTrendPointLabel(date: string, range: ActivityTrendRange | "calendar-month"): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  if (!Number.isFinite(parsed.getTime())) return date;
  if (range === "calendar-month") {
    return new Intl.DateTimeFormat("es-ES", { month: "short", timeZone: "UTC" }).format(parsed).replace(".", "");
  }
  if (range === "monthly") {
    return new Intl.DateTimeFormat("es-ES", { day: "2-digit", timeZone: "UTC" }).format(parsed);
  }
  return new Intl.DateTimeFormat("es-ES", { weekday: "short", day: "2-digit", timeZone: "UTC" }).format(parsed).replace(".", "");
}

export function trendBarHeight(state: string, value: number | null, total: number | null): string {
  const numericState = state === "value" || (state === "partial" && value !== null) || state === "zero";
  if (!numericState || value === null || !Number.isFinite(value) || value < 0 || total === null || !Number.isFinite(total) || total <= 0) return "0%";
  return `${(value / total) * 100}%`;
}

export function trendMetricMaximum(points: ActivityTrendData["points"], metric: "steps" | "distanceMeters"): number {
  return Math.max(0, ...points.flatMap((point) => {
    const value = point[metric].value;
    return typeof value === "number" && Number.isFinite(value) && value >= 0 ? [value] : [];
  }));
}

type AxisScale = { maximum: number; ticks: number[] };

function axisTicks(maximum: number, increment: number): number[] {
  const intervalCount = Math.round(maximum / increment);
  return Array.from({ length: intervalCount + 1 }, (_, index) => {
    const value = maximum - index * increment;
    return Number(value.toPrecision(12));
  });
}

function niceAxisScale(maximum: number, minimumIncrement = 0): AxisScale {
  if (!Number.isFinite(maximum) || maximum <= 0) return { maximum: 0, ticks: [0] };
  const roughIncrement = maximum / 5;
  const magnitude = 10 ** Math.floor(Math.log10(roughIncrement));
  const normalized = roughIncrement / magnitude;
  const multiplier = [1, 2, 2.5, 5, 10].find((candidate) => candidate >= normalized) || 10;
  const increment = Math.max(minimumIncrement, multiplier * magnitude);
  const axisMaximum = Math.ceil(maximum / increment) * increment;
  if (!Number.isFinite(increment) || increment <= 0 || !Number.isFinite(axisMaximum)) {
    return { maximum, ticks: [maximum, 0] };
  }
  return { maximum: axisMaximum, ticks: axisTicks(axisMaximum, increment) };
}

function trendMetricAxisScale(maximum: number, metric: "steps" | "distanceMeters"): AxisScale {
  if (!Number.isFinite(maximum) || maximum <= 0) return { maximum: 0, ticks: [0] };
  const increment = metric === "steps"
    ? maximum <= 10_000 ? 2_000 : maximum <= 20_000 ? 4_000 : 5_000
    : maximum <= 3_000 ? 500 : maximum <= 10_000 ? 1_000 : 2_000;
  const axisMaximum = Math.ceil(maximum / increment) * increment;
  const ticks = axisTicks(axisMaximum, increment);
  return ticks.length <= 6 ? { maximum: axisMaximum, ticks } : niceAxisScale(maximum, 1);
}

export function trendMetricAxisMaximum(maximum: number, metric: "steps" | "distanceMeters"): number {
  return trendMetricAxisScale(maximum, metric).maximum;
}

export function trendAxisTicks(maximum: number, metric?: "steps" | "distanceMeters"): number[] {
  if (!metric) {
    if (!Number.isFinite(maximum) || maximum <= 0) return [0, 0, 0];
    return [maximum, maximum / 2, 0];
  }
  return trendMetricAxisScale(maximum, metric).ticks;
}

export function trendAxisTickLabel(value: number, metric: "steps" | "distanceMeters"): string {
  if (metric === "steps") return Math.round(value).toLocaleString("es-ES");
  if (value >= 1000) return `${(value / 1000).toLocaleString("es-ES", { maximumFractionDigits: 1 })} km`;
  return `${Math.round(value).toLocaleString("es-ES")} m`;
}

function trendBarTitle(point: ActivityTrendData["points"][number], key: "steps" | "distanceMeters", unit: string): string {
  const metric = point[key];
  return `${key === "steps" ? "Pasos" : "Distancia"}: ${trendPointText(metric.state, metric.value, unit)} · Estado: ${safeStateCopy(metric.state).label}`;
}

export function trendGuidePosition(average: number | null, maximum: number | null): string | null {
  if (typeof average !== "number" || !Number.isFinite(average) || average < 0 || typeof maximum !== "number" || !Number.isFinite(maximum) || maximum < 0) return null;
  if (maximum === 0) return average === 0 ? "0%" : null;
  return `${Math.min(100, (average / maximum) * 100)}%`;
}

function trendAverageGuide(metric: ActivityTrendData["steps"], maximum: number): ReactElement | null {
  const position = trendGuidePosition(metric.averageObserved, maximum);
  if (position === null) return null;
  return <div className="trend-average-guide" style={{ bottom: position }} aria-label="Promedio observado" data-testid="activity-average-guide" />;
}

export function trendMetricText(metric: ActivityTrendData["steps"], kind: "total" | "average"): string {
  const value = kind === "total" ? metric.totalObserved : metric.averageObserved;
  return formatNumber(kind === "average" && value !== null ? Math.round(value) : value);
}

function trendAggregateText(metric: ActivityTrendData["steps"], kind: "total" | "average", unit: string): string {
  const text = trendMetricText(metric, kind);
  return text === "Sin medición" || !unit ? text : `${text} ${unit}`;
}

function trendSeries(metric: ActivityTrendData["steps"], points: ActivityTrendData["points"], key: "steps" | "distanceMeters", label: string, unit: string, range: ActivityTrendRange | "calendar-month"): ReactElement {
  const maximum = trendMetricMaximum(points, key);
  const axisMaximum = trendMetricAxisMaximum(maximum, key);
  const axisMetric = key === "steps" ? "steps" : "distanceMeters";
  const ticks = trendAxisTicks(maximum, axisMetric);
  return <div className={`trend-series trend-${axisMetric}`} data-testid={`activity-trend-${axisMetric}`}><div className="trend-bar-group-label">{label}</div><div className="trend-axis" aria-label={`Escala de ${label}`}>{ticks.map((tick, index) => <span key={`${axisMetric}-tick-${index}`}>{trendAxisTickLabel(tick, axisMetric)}</span>)}</div><div className="trend-plot-area"><div className="trend-plot" style={{ "--trend-axis-maximum": axisMaximum, "--trend-grid-step": `${100 / Math.max(1, ticks.length - 1)}%` } as React.CSSProperties}>{trendAverageGuide(metric, axisMaximum)}{points.map((point) => { const tooltip = trendBarTitle(point, key, unit); const isNumeric = point[key].value !== null && ["value", "partial", "zero"].includes(point[key].state); return <div className={`trend-bar trend-${point[key].state}${isNumeric ? " trend-bar-numeric chart-tooltip-target" : ""}`} key={`${key}-${point.date}`} tabIndex={isNumeric ? 0 : undefined} data-tooltip={isNumeric ? tooltip : undefined} data-tooltip-primitive={isNumeric ? "chart" : undefined} data-tooltip-delay={isNumeric ? "immediate" : undefined} aria-label={`${point.date}: ${trendPointText(point[key].state, point[key].value, unit)}; estado ${safeStateCopy(point[key].state).label}`} style={{ height: trendBarHeight(point[key].state, point[key].value, axisMaximum) }} />; })}</div><div className="trend-bar-labels" aria-hidden="true">{points.map((point) => <span key={`${key}-label-${point.date}`}>{formatTrendPointLabel(point.date, range)}</span>)}</div></div></div>;
}

function trendBucketSummary(trend: ActivityTrendData): ReactElement {
  return <ul className="trend-bucket-summary" aria-label="Resumen accesible de buckets de actividad">{trend.points.map((point) => <li key={point.date}><strong>{formatTrendBucketLabel(point.date)}</strong><span className="visually-hidden"> ({point.date})</span><span>Pasos: {trendPointText(point.steps.state, point.steps.value, "pasos")}</span><span>Distancia: {trendPointText(point.distanceMeters.state, point.distanceMeters.value, "m")}</span></li>)}</ul>;
}

function sleepSeconds(metric: { state: string; value: number | null }): string {
  const label = safeStateCopy(metric.state).label;
  if (metric.value === null) return `${metric.state}/${label}`;
  return `${Math.round(metric.value / 60)} min (${metric.state}/${label})`;
}

export function sleepDurationValue(value: number | null): string {
  if (value === null) return "Sin medición";
  const minutes = Math.max(0, Math.round(value / 60));
  const hours = Math.floor(minutes / 60);
  return minutes % 60 === 0 ? `${hours} h` : `${hours} h ${minutes % 60} min`;
}

export const sleepValue = sleepDurationValue;

export type SleepBarSegment = { kind: "night" | "awake" | "unclassified" | "light" | "deep" | "rem"; seconds: number };

export function sleepDurationSegments(point: SleepTrendData["points"][number]): SleepBarSegment[] {
  const segments: SleepBarSegment[] = [];
  const metric = point.nightSleepSeconds;
  if (metric.value !== null && ["value", "partial"].includes(metric.state) && metric.value > 0) {
    segments.push({ kind: "night", seconds: metric.value });
  }
  return segments;
}

export function sleepStageSegments(point: SleepTrendData["points"][number], genericSeconds = 0): SleepBarSegment[] {
  const segments: SleepBarSegment[] = [];
  if (!point.stages) return [];
  const specific = ([
    ["light", point.stages.lightSeconds],
    ["deep", point.stages.deepSeconds],
    ["rem", point.stages.remSeconds]
  ] as const).filter(([, metric]) => metric.value !== null && ["value", "partial", "zero"].includes(metric.state));
  const specificTotal = specific.reduce((sum, [, stage]) => sum + (stage.value ?? 0), 0);
  const explicitUnclassified = point.unclassifiedSeconds;
  const unclassifiedSeconds = explicitUnclassified?.value !== null
    && explicitUnclassified?.value !== undefined
    && ["value", "partial", "zero"].includes(explicitUnclassified.state)
    ? explicitUnclassified.value
    : genericSeconds;
  if (
    point.nightSleepSeconds.value === null
    || !["value", "partial", "zero"].includes(point.nightSleepSeconds.state)
    || genericSeconds < 0
    || unclassifiedSeconds < 0
    || specificTotal + unclassifiedSeconds !== point.nightSleepSeconds.value
  ) return [];
  const awake = point.stages.awakeSeconds;
  if (awake.value !== null && awake.value > 0 && ["value", "partial"].includes(awake.state)) {
    segments.push({ kind: "awake", seconds: awake.value });
  }
  if (explicitUnclassified && unclassifiedSeconds > 0) segments.push({ kind: "unclassified", seconds: unclassifiedSeconds });
  else if (genericSeconds > 0) segments.push({ kind: "night", seconds: genericSeconds });
  for (const [kind, metric] of specific) {
    if (metric.value !== null && metric.value > 0) segments.push({ kind, seconds: metric.value });
  }
  return segments;
}

function localHour(value: string | null, timezone: string): number | null {
  if (!value) return null;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en", { timeZone: timezone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(date);
  const hour = Number(parts.find((part) => part.type === "hour")?.value);
  const minute = Number(parts.find((part) => part.type === "minute")?.value);
  return Number.isFinite(hour) && Number.isFinite(minute) ? hour + minute / 60 : null;
}

export function formatSleepTime(value: string | null, timezone: string): string {
  if (!value) return "Sin medición";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Sin medición";
  try {
    return new Intl.DateTimeFormat("es-ES", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: timezone }).format(date);
  } catch {
    return "Sin medición";
  }
}

export function sleepHourBounds(points: Array<{ bedtime: string | null; wakeTime: string | null }>, timezone: string): { min: number; max: number } | null {
  const intervals = points.flatMap((point) => {
    const start = localHour(point.bedtime, timezone);
    const end = localHour(point.wakeTime, timezone);
    const startInstant = point.bedtime ? Date.parse(point.bedtime) : NaN;
    const endInstant = point.wakeTime ? Date.parse(point.wakeTime) : NaN;
    if (start === null || end === null || !Number.isFinite(startInstant) || !Number.isFinite(endInstant) || endInstant <= startInstant) return [];
    const normalizedStart = start < 12 ? start + 24 : start;
    const duration = Math.min(24, (endInstant - startInstant) / 3_600_000);
    return [{ start: normalizedStart, end: normalizedStart + duration }];
  });
  if (intervals.length === 0) return null;
  const observedMin = Math.min(...intervals.map((interval) => interval.start));
  const observedMax = Math.max(...intervals.map((interval) => interval.end));
  let min = Math.floor(observedMin / 2) * 2 - 2;
  let max = Math.ceil(observedMax / 2) * 2 + 2;
  if (max - min > 24) {
    min = Math.floor(observedMin / 2) * 2;
    max = min + 24;
    if (observedMax > max) {
      max = Math.ceil(observedMax / 2) * 2;
      min = max - 24;
    }
  }
  return max - min <= 24 && observedMin >= min && observedMax <= max ? { min, max } : null;
}

export function sleepSchedulePosition(start: string | null, end: string | null, timezone: string, bounds = { min: 0, max: 48 }): { top: string; height: string } | null {
  const startHour = localHour(start, timezone);
  const endHour = localHour(end, timezone);
  if (startHour === null || endHour === null || !start || !end) return null;
  const startInstant = Date.parse(start);
  const endInstant = Date.parse(end);
  if (!Number.isFinite(startInstant) || !Number.isFinite(endInstant) || endInstant <= startInstant) return null;
  const durationHours = Math.min(24, (endInstant - startInstant) / 3_600_000);
  const visualStart = startHour < 12 ? startHour + 24 : startHour;
  const visualEnd = visualStart + durationHours;
  const span = Math.max(1, bounds.max - bounds.min);
  if (visualStart < bounds.min || visualEnd > bounds.max) return null;
  const top = 100 - ((visualEnd - bounds.min) / span) * 100;
  const height = Math.max(2, ((visualEnd - visualStart) / span) * 100);
  return { top: `${top}%`, height: `${height}%` };
}

export function sleepAxisTickPosition(value: number, bounds: { min: number; max: number }): string {
  return `${100 - ((value - bounds.min) / Math.max(1, bounds.max - bounds.min)) * 100}%`;
}

export function sleepGuidePosition(value: number | null, fallback: number, bounds: { min: number; max: number }): string | null {
  const rawHour = value ?? fallback;
  const hour = rawHour < 14 ? rawHour + 24 : rawHour;
  if (!Number.isFinite(hour) || hour < bounds.min || hour > bounds.max) return null;
  return sleepAxisTickPosition(hour, bounds);
}

export function sleepHourTicks(bounds: { min: number; max: number }): number[] {
  const ticks: number[] = [];
  for (let value = bounds.min; value <= bounds.max; value += 2) {
    ticks.unshift(value);
  }
  return ticks.length > 0 ? ticks : [bounds.max, bounds.min];
}

export function sleepDurationGuidePosition(average: number | null, maximum: number): string | null {
  if (typeof average !== "number" || !Number.isFinite(average) || average < 0 || !Number.isFinite(maximum) || maximum <= 0) return null;
  return `${Math.min(100, (average / maximum) * 100)}%`;
}

function sleepPointState(point: SleepTrendData["points"][number]): string {
  return safeStateCopy(point.nightSleepSeconds.state).label;
}

function sleepTooltip(point: SleepTrendData["points"][number], timezone: string, kind: "Noche" | "Siesta"): string {
  const start = kind === "Noche" ? point.bedtime : null;
  const end = kind === "Noche" ? point.wakeTime : null;
  const range = start && end ? `${formatTimestamp(start, timezone)} → ${formatTimestamp(end, timezone)}` : "Horario no disponible";
  const metric = kind === "Noche" ? point.nightSleepSeconds : point.napsSeconds;
  const tooltipState = safeStateCopy(metric.state).label;
  return `${kind} · ${range} · Duración: ${sleepValue(metric.value)} · Estado: ${tooltipState}`;
}

function sleepHourAxis(bounds: { min: number; max: number } | null): ReactElement | null {
  if (!bounds) return null;
  const ticks = sleepHourTicks(bounds);
  return <div className="sleep-hour-axis" aria-label="Escala de hora local">{ticks.map((value) => <span key={value} data-sleep-tick={value} style={{ top: sleepAxisTickPosition(value, bounds) }}>{`${String(Math.floor(value) % 24).padStart(2, "0")}:00`}</span>)}</div>;
}

function sleepGrid(ticks: number[], bounds: { min: number; max: number }): ReactElement {
  return <div className="sleep-grid" aria-hidden="true">{ticks.map((tick) => <span key={`sleep-grid-${tick}`} data-sleep-tick={tick} style={{ top: sleepAxisTickPosition(tick, bounds) }} />)}</div>;
}

export function sleepDurationAxis(maximum: number): ReactElement {
  const ticks = sleepDurationAxisTicks(maximum);
  const bounds = { min: 0, max: Math.max(1, ticks[0] || maximum) };
  return <div className="sleep-hour-axis sleep-duration-axis" aria-label="Escala de duración del sueño">{ticks.map((value, index) => <span key={`sleep-duration-tick-${index}`} data-sleep-tick={value} style={{ top: sleepAxisTickPosition(value, bounds) }}>{sleepDurationValue(value)}</span>)}</div>;
}

export function sleepDurationAxisTicks(maximum: number): number[] {
  if (!Number.isFinite(maximum) || maximum <= 0) return [0];
  const increment = 2 * 3600;
  const axisMaximum = Math.ceil(maximum / increment) * increment;
  const ticks = axisTicks(axisMaximum, increment);
  if (ticks.length <= 6) return ticks;
  return niceAxisScale(maximum / 3600).ticks.map((tick) => tick * 3600);
}

type SleepInterval = NonNullable<SleepTrendData["intervals"]>[number];

const sleepSegmentLabels: Record<SleepBarSegment["kind"], string> = {
  night: "Sueño genérico",
  awake: "Despierto",
  unclassified: "Sin clasificar",
  light: "Ligero",
  deep: "Profundo",
  rem: "REM"
};

function sleepSegmentState(point: SleepTrendData["points"][number], kind: SleepBarSegment["kind"]): string {
  if (kind === "awake") return point.stages.awakeSeconds.state;
  if (kind === "unclassified") return point.unclassifiedSeconds?.state || point.nightSleepSeconds.state;
  if (kind === "light") return point.stages.lightSeconds.state;
  if (kind === "deep") return point.stages.deepSeconds.state;
  if (kind === "rem") return point.stages.remSeconds.state;
  return point.nightSleepSeconds.state;
}

function sleepCompositionSegments(point: SleepTrendData["points"][number], segments: SleepBarSegment[]): ReactElement[] {
  return segments.map((segment, index) => {
    const tooltip = `${sleepSegmentLabels[segment.kind]} · Duración: ${sleepValue(segment.seconds)} · Estado: ${safeStateCopy(sleepSegmentState(point, segment.kind)).label}`;
    return <span className={`sleep-segment sleep-segment-${segment.kind} chart-tooltip-target`} key={segment.kind} tabIndex={0} data-tooltip={tooltip} data-tooltip-primitive="chart" data-tooltip-delay="immediate" data-stage-index={index} aria-label={tooltip} style={{ flex: `${segment.seconds} 1 0` }} />;
  });
}

const sleepIntervalLabels: Record<SleepInterval["category"], string> = {
  sleeping: "Sueño genérico",
  awake: "Despierto",
  light: "Ligero",
  deep: "Profundo",
  rem: "REM",
  in_bed: "En cama",
  unknown: "Desconocido"
};

function sleepIntervalTooltip(interval: SleepInterval, timezone: string): string {
  const duration = Math.max(0, Date.parse(interval.end) - Date.parse(interval.start)) / 1000;
  return `${sleepIntervalLabels[interval.category]} · ${formatTimestamp(interval.start, timezone)} → ${formatTimestamp(interval.end, timezone)} · Duración: ${sleepValue(duration)}${interval.isNap ? " · Siesta" : ""}`;
}

function sleepBar(point: SleepTrendData["points"][number], timezone: string, kind: "Noche" | "Siesta", mode: SleepDisplayMode, max: number, bounds: { min: number; max: number } | null, intervals: SleepInterval[] = [], compositionOnly = false): ReactElement {
  const metric = kind === "Noche" ? point.nightSleepSeconds : point.napsSeconds;
  const numeric = metric.value !== null && ["value", "partial", "zero"].includes(metric.state);
  const schedule = kind === "Noche" && bounds ? sleepSchedulePosition(point.bedtime, point.wakeTime, timezone, bounds) : null;
  const composition = kind === "Noche" ? sleepStageSegments(point) : [];
  const durationHeight = numeric ? `${Math.max(2, ((metric.value || 0) / max) * 100)}%` : "0%";
  const style = mode === "schedule" && schedule
    ? schedule
    : mode === "schedule" && kind === "Siesta"
      ? { bottom: "0", height: durationHeight }
      : { height: durationHeight };
  const tooltip = sleepTooltip(point, timezone, kind);
  const barClass = `trend-bar sleep-bar sleep-${kind === "Noche" ? "night" : "nap"} sleep-${metric.state}${numeric ? " trend-bar-numeric sleep-bar-numeric" : ""}${composition.length > 0 ? " sleep-composition-bar" : ""} chart-tooltip-target`;
  return <div className={barClass} style={style} tabIndex={0} data-tooltip={tooltip} data-tooltip-primitive="chart" data-tooltip-delay="immediate" data-stage-orientation={composition.length > 0 ? "composition-only" : undefined} aria-label={tooltip}>{composition.length > 0 ? sleepCompositionSegments(point, composition) : null}</div>;
}

function sleepDurationBar(point: SleepTrendData["points"][number], timezone: string, max: number, genericSeconds = 0): ReactElement {
  const segments = sleepStageSegments(point, genericSeconds);
  const contradictory = point.nightSleepSeconds.value !== null
    && ["value", "partial"].includes(point.nightSleepSeconds.state)
    && point.nightSleepSeconds.value > 0
    && segments.length === 0;
  const tooltip = contradictory ? "Etapas inconclusas: la suma no coincide con la duración nocturna" : segments.map((segment) => `${sleepSegmentLabels[segment.kind]}: ${sleepValue(segment.seconds)}`).join(" · ") || `Noche: ${sleepValue(point.nightSleepSeconds.value)}`;
  const interactive = segments.length > 0 || contradictory;
  return <div className={`trend-bar sleep-bar sleep-duration-bar sleep-${contradictory ? "inconclusive" : point.nightSleepSeconds.state}${segments.length > 0 ? " sleep-bar-numeric trend-bar-numeric" : ""}${interactive ? " chart-tooltip-target" : ""}`} tabIndex={interactive ? 0 : undefined} data-tooltip={interactive ? tooltip : undefined} data-tooltip-primitive={interactive ? "chart" : undefined} data-tooltip-delay={interactive ? "immediate" : undefined} data-stage-orientation="vertical-stack" aria-label={tooltip} style={{ height: sleepDurationBarHeight(segments, max) }}>
    {sleepCompositionSegments(point, segments)}
  </div>;
}

export function sleepDurationBarHeight(segments: SleepBarSegment[], max: number): string {
  const night = segments.reduce((sum, segment) => sum + segment.seconds, 0);
  return `${Math.min(100, (night / Math.max(1, max)) * 100)}%`;
}

export function sleepDurationMaximum(points: SleepTrendData["points"]): number {
  return Math.max(1, ...points.map((point) => {
    const segments = sleepStageSegments(point);
    return segments.reduce((sum, segment) => sum + segment.seconds, 0);
  }));
}

export function sleepNightDurationMaximum(points: SleepTrendData["points"]): number {
  const maximum = Math.max(1, ...points.map((point) => {
    const awake = point.stages?.awakeSeconds;
    const awakeSeconds = awake?.value !== null && awake?.value !== undefined && ["value", "partial", "zero"].includes(awake.state) ? awake.value : 0;
    return point.nightSleepSeconds.value !== null && ["value", "partial", "zero"].includes(point.nightSleepSeconds.state)
      ? point.nightSleepSeconds.value + awakeSeconds
      : 0;
  }));
  return sleepDurationAxisTicks(maximum)[0];
}

function sleepTrendControls(actions: ViewActions, logicalDate: string, range: ActivityTrendRange): ReactElement {
  const selectedDate = actions.sleepDate || logicalDate;
  const selectedRange = actions.sleepRange || range;
  return <div className="trend-controls sleep-trend-controls" role="group" aria-labelledby="sleep-controls-title"><span id="sleep-controls-title" className="visually-hidden">Controles de ventana de sueño</span><label className="visually-hidden" htmlFor="sleep-date">Fecha de sueño</label><input data-testid="sleep-trend-date" id="sleep-date" name="sleep-date" autoComplete="off" type="date" value={selectedDate} onChange={(event) => actions.setSleepDate?.(event.target.value)} /><button data-testid="sleep-trend-previous" className="button button-secondary trend-arrow" type="button" aria-label="Ventana anterior de sueño" onClick={() => actions.shiftSleep?.(-1)}>←</button><div data-testid="sleep-trend-range" className="trend-quick-ranges" role="group" aria-label="Seleccionar ventana de sueño">{(actions.trendRanges || []).map((option) => <button className={`trend-quick-range${option.value === selectedRange ? " is-selected" : ""}`} type="button" key={option.value} aria-label={`Seleccionar ventana de sueño ${trendQuickLabel(option.value)}`} aria-pressed={option.value === selectedRange} onClick={() => actions.setSleepRange?.(option.value)}>{trendQuickLabel(option.value)}</button>)}</div><button data-testid="sleep-trend-next" className="button button-secondary trend-arrow" type="button" aria-label="Ventana siguiente de sueño" disabled={selectedDate >= new Date().toISOString().slice(0, 10)} onClick={() => actions.shiftSleep?.(1)}>→</button></div>;
}

function SleepTrendSection({ state, trend, actions }: { state: AppState; trend: SleepTrendData | null; actions: ViewActions }): ReactElement {
  const status = state.sleepTrend?.status || "idle";
  const selectedDate = actions.sleepDate || trend?.logicalDate || state.context.date;
  const selectedRange = actions.sleepRange || trend?.range || "7d";
  if (!trend) return <section className="trend-panel sleep-trend-panel" aria-labelledby="sleep-trend-title" data-testid="sleep-trend-panel">
    <div className="section-heading"><div><p className="eyebrow">TENDENCIA DE SUEÑO</p><h2 id="sleep-trend-title">Sueño por ventana</h2><p className="trend-coverage-note" data-testid="sleep-trend-context">Fin lógico seleccionado: {selectedDate}.</p></div><span className="section-aside">{formatTrendRangeLabel(selectedRange)}</span></div>
    {sleepTrendControls(actions, selectedDate, selectedRange)}
    <div data-testid="sleep-trend-body" aria-busy={status === "loading"}>{status === "error" ? <p role="status">No se pudo cargar el sueño para la fecha y ventana seleccionadas; los controles siguen disponibles.</p> : <p role="status">Cargando sueño para la fecha y ventana seleccionadas…</p>}</div>
  </section>;
    const max = sleepNightDurationMaximum(trend.points);
    const sleepRange = actions.sleepRange || trend.range;
    const hourBounds = sleepHourBounds(trend.points, state.context.timezone) || (trend.averageBedtime || trend.averageWakeTime ? { min: 22, max: 36 } : null);
    const bedtimeHour = localHour(trend.averageBedtime || null, state.context.timezone);
    const wakeHour = localHour(trend.averageWakeTime || null, state.context.timezone);
      const bedtimeGuide = !hourBounds || bedtimeHour === null ? null : sleepGuidePosition(bedtimeHour, hourBounds.min, hourBounds);
      const wakeGuide = !hourBounds || wakeHour === null ? null : sleepGuidePosition(wakeHour, hourBounds.max, hourBounds);
   const formatSleepTimeForContext = (value: string | null) => formatSleepTime(value, state.context.timezone);
    const longRange = trend.bucketMode === "calendar-month";
    const mode = actions.sleepMode || "schedule";
    const effectiveMode = longRange ? "duration" : mode;
    const hasNaps = trend.napsSeconds.observedDays > 0;
     const hasSpecificStages = [trend.awakeSeconds, trend.lightSeconds, trend.deepSeconds, trend.remSeconds].some((aggregate) => aggregate.observedDays > 0);
    const totalObserved = !hasNaps || trend.nightSleepSeconds.totalObserved === null || trend.napsSeconds.totalObserved === null ? null : trend.nightSleepSeconds.totalObserved + trend.napsSeconds.totalObserved;
    const scheduleTicks = hourBounds ? sleepHourTicks(hourBounds) : [];
    return <section className="trend-panel sleep-trend-panel" aria-labelledby="sleep-trend-title" data-testid="sleep-trend-panel">
      <div className="section-heading"><div><p className="eyebrow">TENDENCIA DE SUEÑO</p><h2 id="sleep-trend-title">Sueño por ventana</h2><p className="trend-coverage-note" data-testid="sleep-trend-context">Fin lógico seleccionado: {trend.logicalDate}. {trend.observedDays === 0 ? "No hay datos de sueño para esta ventana." : `${trend.observedDays} días observados; las siestas se conservan separadas de la noche.`}</p></div><span className="section-aside">{formatTrendRangeLabel(trend.range)}</span></div>
      {sleepTrendControls(actions, trend.logicalDate, sleepRange)}
      <div data-testid="sleep-trend-body" aria-busy="false">
      <div className="sleep-summary"><span>Promedio noche: <strong>{sleepDurationValue(trend.nightSleepSeconds.averageObserved)}</strong></span><span>Total noche: <strong>{sleepDurationValue(trend.nightSleepSeconds.totalObserved)}</strong></span>{trend.napsSeconds.totalObserved !== null ? <><span>Promedio siestas: <strong>{sleepDurationValue(trend.napsSeconds.averageObserved)}</strong></span><span>Total siestas: <strong>{sleepDurationValue(trend.napsSeconds.totalObserved)}</strong></span></> : null}{totalObserved !== null ? <span>Total combinado <small>(siestas observadas):</small> <strong>{sleepDurationValue(totalObserved)}</strong></span> : null}{trend.averageBedtime ? <span>Hora media de acostarse: <strong>{formatSleepTimeForContext(trend.averageBedtime)}</strong></span> : null}{trend.averageWakeTime ? <span>Hora media de despertarse: <strong>{formatSleepTimeForContext(trend.averageWakeTime)}</strong></span> : null}<span>Cobertura: <strong>{trend.nightSleepSeconds.observedDays} / {trend.nightSleepSeconds.expectedDays} días</strong></span></div>
     {!longRange ? <div className="sleep-mode-controls" role="group" aria-label="Modo de visualización del sueño" data-testid="sleep-mode-toggle"><span>Mostrar como</span>{([ ["schedule", "Horario"], ["duration", "Duración"] ] as const).map(([value, label]) => <button key={value} className={`sleep-mode-button${effectiveMode === value ? " is-selected" : ""}`} type="button" aria-pressed={effectiveMode === value} onClick={() => actions.setSleepMode?.(value)}>{label}</button>)}</div> : <p className="sleep-range-note">Los rangos largos se resumen por mes para conservar la lectura.</p>}
               <div className={`sleep-visual sleep-${effectiveMode} sleep-range-${trend.range}`} data-testid={`sleep-trend-${effectiveMode}-chart`} aria-label={effectiveMode === "schedule" ? "Barras de sueño por horario local" : longRange ? "Resumen mensual de duración del sueño" : "Barras de duración del sueño"}>{effectiveMode === "schedule" ? sleepHourAxis(hourBounds) : sleepDurationAxis(max)}<div className="sleep-plot">{effectiveMode === "schedule" ? (hourBounds ? sleepGrid(scheduleTicks, hourBounds) : null) : sleepGrid(sleepDurationAxisTicks(max), { min: 0, max })}{effectiveMode === "schedule" ? <>{bedtimeGuide ? <div className="sleep-average-guide sleep-average-bedtime" style={{ top: bedtimeGuide }} aria-label="Hora media de acostarse" data-testid="sleep-bedtime-guide" /> : null}{wakeGuide ? <div className="sleep-average-guide sleep-average-wake" style={{ top: wakeGuide }} aria-label="Hora media de despertarse" data-testid="sleep-wake-guide" /> : null}</> : effectiveMode === "duration" ? (() => { const position = sleepDurationGuidePosition(trend.nightSleepSeconds.averageObserved, max); return position ? <div className="sleep-average-guide sleep-average-duration" style={{ bottom: position }} aria-label="Promedio de duración de la noche" data-testid="sleep-average-guide" /> : null; })() : null}{trend.points.map((point) => { const genericSeconds = trend.range === "daily" ? (trend.intervals || []).filter((interval) => !interval.isNap && interval.category === "sleeping" && (!point.bedtime || Date.parse(interval.start) >= Date.parse(point.bedtime)) && (!point.wakeTime || Date.parse(interval.end) <= Date.parse(point.wakeTime))).reduce((total, interval) => total + (Date.parse(interval.end) - Date.parse(interval.start)) / 1000, 0) : 0; return <div className="sleep-day" key={point.date}><div className="sleep-day-plot">{effectiveMode === "duration" ? sleepDurationBar(point, state.context.timezone, max, genericSeconds) : sleepBar(point, state.context.timezone, "Noche", effectiveMode, max, hourBounds, trend.range === "daily" ? trend.intervals || [] : [], trend.range !== "daily")}</div></div>; })}</div><div className="sleep-label-row" aria-hidden="true">{trend.points.map((point) => <span className="sleep-day-label" key={`label-${point.date}`}>{formatTrendPointLabel(point.date, trend.bucketMode === "calendar-month" ? "calendar-month" : trend.range)}</span>)}</div></div>
          {effectiveMode === "schedule" ? <div className="sleep-guide-legend">{bedtimeGuide ? <span className="sleep-guide-key sleep-guide-key-bedtime">Hora media de acostarse</span> : null}{wakeGuide ? <span className="sleep-guide-key sleep-guide-key-wake">Hora media de despertarse</span> : null}{trend.range !== "daily" && (!bedtimeGuide || !wakeGuide) ? <span className="sleep-guide-warning">Guías omitidas: promedios no comparables con esta ventana.</span> : null}</div> : <div className="sleep-guide-legend"><span className="sleep-guide-key sleep-guide-key-duration">Promedio noche: {sleepValue(trend.nightSleepSeconds.averageObserved)}</span><span className="sleep-guide-warning">La escala usa solo duración nocturna; las siestas no la cambian.</span></div>}
          {trend.range === "daily" && trend.intervals?.length ? <div className="sleep-event-timeline" aria-label="Cronología de intervalos de sueño"><div className="sleep-event-track">{trend.intervals.map((interval, index) => { const tooltip = sleepIntervalTooltip(interval, state.context.timezone); return <span className={`sleep-event sleep-event-${interval.category}${interval.isNap ? " sleep-event-nap" : ""} chart-tooltip-target`} key={`${interval.start}-${interval.end}-${interval.category}-${interval.isNap ? "nap" : "night"}-${index}`} tabIndex={0} data-tooltip={tooltip} data-tooltip-primitive="chart" data-tooltip-delay="immediate" aria-label={tooltip} style={{ flex: `${Date.parse(interval.end) - Date.parse(interval.start)} 1 0` }} />; })}</div></div> : null}
        <ul className="sleep-accessible-list visually-hidden" aria-label="Detalle accesible de sueño">{trend.points.map((point) => <li key={`sleep-${point.date}`}><strong>{point.date}</strong><span>Noche: {sleepValue(point.nightSleepSeconds.value)} · estado: {sleepPointState(point)}</span><span>Siestas: {sleepValue(point.napsSeconds.value)} · estado: {safeStateCopy(point.napsSeconds.state).label}</span>{!longRange ? <span>Horario local: {point.bedtime ? formatTimestamp(point.bedtime, state.context.timezone) : "Sin medición"} → {point.wakeTime ? formatTimestamp(point.wakeTime, state.context.timezone) : "Sin medición"}</span> : null}</li>)}</ul>
       <p className="scope-note-inline">{hasSpecificStages ? "Solo se muestran etapas específicas observadas y validadas; el sueño genérico no se reparte entre etapas." : "La fuente solo publica sueño genérico o no publica etapas; no se infieren etapas específicas."}</p>
      </div>
  </section>;
}

function overviewPage(state: AppState, actions: ViewActions): ReactElement {
  const envelope = state.page.envelope as Envelope<OverviewData>;
  const data = envelope.data;
  const summary = data?.summary || {};
    const trendPage = state.activityTrend || { status: "idle" as const, envelope: null, error: null };
    const trend = trendPage.envelope?.data as ActivityTrendData | null;
    const sleepTrend = state.sleepTrend?.envelope?.data as SleepTrendData | null;
  const observedSummary = Object.values(summary).filter((metric) => metric.state !== "unsupported");
  const fieldCount = observedSummary.length;
  const isEmpty = fieldCount === 0 && envelope.coverage.availableDays === 0;
    const trendContent = trend ? <section className="trend-panel" aria-labelledby="activity-trend-title" data-testid="activity-trend-panel">
       <div className="section-heading"><div><p className="eyebrow">TENDENCIA DE ACTIVIDAD</p><h2 id="activity-trend-title">Actividad por ventana</h2><p className="trend-coverage-note">Fin lógico seleccionado: {trend.logicalDate}. {trend.steps.observedDays} de {trend.steps.expectedDays} días con pasos; los datos observados conservan su estado.</p></div><span className="section-aside">{formatTrendRangeLabel(trend.range)}</span></div>
         <div className="trend-controls" aria-label="Controles de ventana de tendencia"><label className="visually-hidden" htmlFor="activity-date">Fecha de actividad</label><input id="activity-date" name="activity-date" type="date" autoComplete="off" value={trend.logicalDate} onChange={(event) => actions.setTrendDate?.(event.target.value)} /><button className="button button-secondary trend-arrow" type="button" aria-label="Ventana anterior" onClick={() => actions.shiftTrend?.(-1)}>←</button><div className="trend-quick-ranges" role="group" aria-label="Seleccionar ventana">{(actions.trendRanges || [{ value: "7d", label: "7 días" }]).map((range) => <button className={`trend-quick-range${range.value === (actions.trendRange || "7d") ? " is-selected" : ""}`} type="button" key={range.value} aria-label={`Seleccionar ventana ${trendQuickLabel(range.value)}`} aria-current={range.value === (actions.trendRange || "7d") ? "true" : undefined} aria-pressed={range.value === (actions.trendRange || "7d")} onClick={() => actions.setTrendRange?.(range.value)}>{trendQuickLabel(range.value)}</button>)}</div><button className="button button-secondary trend-arrow" type="button" aria-label="Ventana siguiente" disabled={trend.logicalDate >= new Date().toISOString().slice(0, 10)} onClick={() => actions.shiftTrend?.(1)}>→</button></div>
       <div className="trend-summary"><span>Total pasos: <strong>{trendAggregateText(trend.steps, "total", "")}</strong></span><span>Promedio pasos: <strong>{trendAggregateText(trend.steps, "average", "")}</strong></span><span>Total distancia: <strong>{trendAggregateText(trend.distanceMeters, "total", "m")}</strong></span><span>Promedio distancia: <strong>{trendAggregateText(trend.distanceMeters, "average", "m")}</strong></span><span>Cobertura: <strong>{trend.steps.observedDays} / {trend.steps.expectedDays} días</strong></span></div><div className="trend-legend" aria-label="Leyenda de la tendencia"><span><i className="trend-legend-line" aria-hidden="true" /> Promedio observado</span><span><i className="trend-legend-absence" aria-hidden="true" /> Ausencia conservada en altura y estado</span></div>
       <p className="trend-bucket-label">{trend.bucketMode === "calendar-month" ? "Resumen mensual: buckets por mes calendario" : "Buckets por día"}</p>
         <div className="trend-bars" data-testid="activity-trend-charts" aria-label={`Series separadas de pasos y distancia por ${trend.bucketMode === "calendar-month" ? "mes" : "día"}`}>{trendSeries(trend.steps, trend.points, "steps", "Pasos", "pasos", trend.bucketMode === "calendar-month" ? "calendar-month" : trend.range)}{trendSeries(trend.distanceMeters, trend.points, "distanceMeters", "Distancia", "m", trend.bucketMode === "calendar-month" ? "calendar-month" : trend.range)}</div>
        {trend.bucketMode === "calendar-month" ? trendBucketSummary(trend) : null}
   </section> : null;
   return (
    <>
      {contextForm(state, actions)}
      {coveragePanel(envelope)}
      {isEmpty ? emptyOverview(envelope) : (
        <section className="metrics-section" aria-labelledby="metrics-title">
          <div className="section-heading"><div><p className="eyebrow">LECTURAS PUBLICADAS</p><h2 id="metrics-title">Lo que la ventana permite afirmar</h2></div><span className="section-aside">{fieldCount} campo{fieldCount === 1 ? "" : "s"}</span></div>
          <div className="metric-grid">
            {METRIC_ORDER.filter((key) => summary[key] !== undefined).map((key) => <div key={key}>{metricCard(key, summary[key] as Metric)}</div>)}
          </div>
        </section>
      )}
       {trendPage.status === "loading" ? <section className="trend-panel" aria-label="Tendencia de actividad" aria-busy="true">Cargando tendencia de actividad…</section> : trendPage.status === "error" ? <section className="trend-panel" role="status">No se pudo cargar la tendencia de actividad; el resumen diario sigue disponible.</section> : trendContent}
         <SleepTrendSection state={state} trend={sleepTrend} actions={actions} />
       {warningsPanel(envelope.warnings)}
      {scopeNote(envelope)}
    </>
  );
}

function sourceRows(items: Source[], timezone: string): ReactElement[] {
  return items.map((item) => (
    <tr key={item.sourceKey}>
      <th scope="row"><span className="table-primary">{item.label}</span><span className="table-secondary">Alias opaco BFF no mostrado</span></th>
      <td>{stateBadge(item.state)}</td>
      <td><div className="capability-list">{item.capabilities.map((capability) => <span key={capability}>{SOURCE_CAPABILITY_LABELS[capability] || capability}</span>)}</div></td>
      <td>{item.lastObservedAt ? <><span className="table-primary">{formatTimestamp(item.lastObservedAt, timezone)}</span><span className="table-secondary">Zona: {timezone}</span></> : <span className="table-secondary">Sin observación</span>}</td>
    </tr>
  ));
}

function sourceCards(items: Source[], timezone: string): ReactElement[] {
  return items.map((item) => (
    <article className="compact-card" role="listitem" key={item.sourceKey}>
      <div className="compact-card-heading"><h3>{item.label}</h3>{stateBadge(item.state)}</div>
      <dl><div><dt>Capacidades</dt><dd><div className="capability-list">{item.capabilities.map((capability) => <span key={capability}>{SOURCE_CAPABILITY_LABELS[capability] || capability}</span>)}</div></dd></div><div><dt>Última observación</dt><dd>{item.lastObservedAt ? formatTimestamp(item.lastObservedAt, timezone) : "Sin observación"}</dd></div></dl>
    </article>
  ));
}

function sourcesPage(state: AppState, actions: ViewActions): ReactElement {
  const envelope = state.page.envelope as Envelope<{ items: Source[] }>;
  const items = envelope.data?.items || [];
  if (items.length === 0) {
    return <>{contextForm(state, actions, "Consultar fuentes")}{emptySources(state.context)}{warningsPanel(envelope.warnings)}</>;
  }
  return (
    <>
      {contextForm(state, actions, "Consultar fuentes")}
      <section className="table-panel" aria-labelledby="sources-title">
        <div className="section-heading"><div><p className="eyebrow">INVENTARIO SANITIZADO</p><h2 id="sources-title">Proveniencia sin selección silenciosa</h2></div><span className="section-aside">{items.length} fuente{items.length === 1 ? "" : "s"}</span></div>
        <div className="responsive-table-wrap desktop-table" role="region" tabIndex={0} aria-label="Tabla de fuentes; desliza horizontalmente para verla completa"><table className="data-table"><caption>Fuentes declaradas por el BFF</caption><thead><tr><th scope="col">Fuente</th><th scope="col">Estado</th><th scope="col">Capacidades</th><th scope="col">Última observación</th></tr></thead><tbody>{sourceRows(items, envelope.timezone)}</tbody></table></div>
        <div className="compact-card-list mobile-only" role="list" aria-label="Fuentes declaradas por el BFF">{sourceCards(items, envelope.timezone)}</div>
      </section>
      {warningsPanel(envelope.warnings, "Advertencias de proveniencia")}
      <aside className="scope-note" aria-label="Regla de proveniencia"><div className="scope-note-mark" aria-hidden="true">!</div><div><strong>Disponible no significa completo.</strong><p>Una fuente disponible tiene proveniencia suficiente para el alcance, pero no garantiza que exista una lectura.</p></div></aside>
    </>
  );
}

function runsFilters(state: AppState, actions: ViewActions): ReactElement {
  const filters = state.runs.filters;
  const loading = state.page.status === "loading";
  const error = state.page.error?.code === "INVALID_QUERY"
    ? state.page.error
    : state.runs.error?.code === "INVALID_QUERY"
      ? state.runs.error
      : null;
  return (
    <form className="filter-bar" data-form="runs" aria-busy={loading} key={`${filters.from}-${filters.to}-${filters.state}`} onSubmit={actions.onRunsSubmit}>
      <div className="field-group" data-invalid={invalidField(error, "from") || undefined}><label htmlFor="runs-from">Desde</label><input id="runs-from" name="from" type="date" autoComplete="off" defaultValue={filters.from} {...fieldValidationProps(error, "from")} />{fieldValidationMessage(error, "from")}</div>
      <div className="field-group" data-invalid={invalidField(error, "to") || undefined}><label htmlFor="runs-to">Hasta</label><input id="runs-to" name="to" type="date" autoComplete="off" defaultValue={filters.to} {...fieldValidationProps(error, "to")} />{fieldValidationMessage(error, "to")}</div>
      <div className="field-group" data-invalid={invalidField(error, "state") || undefined}><label htmlFor="runs-state">Estado</label><select id="runs-state" name="state" autoComplete="off" defaultValue={filters.state} {...fieldValidationProps(error, "state")}>{RUN_FILTER_STATES.map((item) => <option value={item.value} key={item.value || "all"}>{item.label}</option>)}</select>{fieldValidationMessage(error, "state")}</div>
      <button className="button button-secondary" type="submit" disabled={isRetryBlocked(state.retryUntil) || loading}>Aplicar filtros</button>
      <p id="runs-filter-status" className="filter-note" role="status" aria-live="polite" aria-atomic="true">{loading ? "Aplicando filtros…" : `Las horas se muestran en ${state.context.timezone}. La zona no se envía como filtro de verificaciones.`}</p>
    </form>
  );
}

function runCounts(counts: RunItem["counts"]): ReactElement {
  return <div className="run-counts" aria-label="Conteos agregados"><div><span>Vistos</span><strong>{formatCount(counts.recordsSeen)}</strong></div><div><span>Aceptados</span><strong>{formatCount(counts.recordsAccepted)}</strong></div><div><span>Rechazados</span><strong>{formatCount(counts.recordsRejected)}</strong></div><div><span>Duplicados</span><strong>{formatCount(counts.recordsDuplicated)}</strong></div><div><span>Campos no soportados</span><strong>{formatCount(counts.fieldsUnsupported)}</strong></div></div>;
}

function runRows(items: RunItem[], timezone: string, actions: ViewActions): ReactElement[] {
  return items.map((item) => (
    <tr key={item.runKey}>
      <th scope="row"><a className="run-link" href={`/verify/runs/${encodeURIComponent(item.runKey)}`} onClick={(event) => actions.onRouteClick(event, `/verify/runs/${encodeURIComponent(item.runKey)}`)}>{item.runKey}</a><span className="table-secondary">Solicitada {formatTimestamp(item.requestedAt, timezone)}</span></th>
      <td>{stateBadge(item.state)}</td><td>{runCounts(item.counts)}</td><td><span className="table-primary">{item.finishedAt ? formatTimestamp(item.finishedAt, timezone) : "En curso"}</span><span className="table-secondary">{item.startedAt ? "Procesada" : "Aún no iniciada"}</span></td>
    </tr>
  ));
}

function runCards(items: RunItem[], timezone: string, actions: ViewActions): ReactElement[] {
  return items.map((item) => (
    <article className="compact-card" role="listitem" key={item.runKey}>
      <div className="compact-card-heading"><h3><a className="run-link" href={`/verify/runs/${encodeURIComponent(item.runKey)}`} onClick={(event) => actions.onRouteClick(event, `/verify/runs/${encodeURIComponent(item.runKey)}`)}>{item.runKey}</a></h3>{stateBadge(item.state)}</div>
      <dl><div><dt>Solicitada</dt><dd>{formatTimestamp(item.requestedAt, timezone)}</dd></div><div><dt>Finalizada</dt><dd>{item.finishedAt ? formatTimestamp(item.finishedAt, timezone) : "En curso"}</dd></div></dl>{runCounts(item.counts)}
    </article>
  ));
}

function errorPanel(error: ApiError | null | undefined, actions: ViewActions, options: { action?: ViewAction; retryUntil?: number | null } = {}): ReactElement | null {
  if (!error) return null;
  const action = options.action || "retry";
  const canRetry = action === "retry" && error.retryable !== false;
  const canResetRuns = action === "reset-runs";
  const canRetryCreate = action === "retry-create" && (error.retryable === true || error.code === "IDEMPOTENCY_CONFLICT");
  const remaining = retryGateRemaining(options.retryUntil ?? null);
  const retryBlocked = remaining > 0;
  const buttonLabel = action === "reset-runs" ? "Reiniciar listado" : canRetryCreate ? "Reintentar verificación" : "Consultar de nuevo";
  return (
    <section className="error-state" role="alert">
      <div className="error-symbol" aria-hidden="true">!</div>
      <div><p className="eyebrow">ERROR {error.status || "LOCAL"} / {error.code}</p><h2>{errorTitle(error)}</h2><p>{ERROR_COPY[error.code] || ERROR_COPY.NETWORK_ERROR}</p>{error.field ? <span className="error-field">Campo: {error.field}</span> : null}{retryBlocked ? <span className="error-field" role="status" aria-live="polite">Puedes volver a consultar en {Math.ceil(remaining / 1000)} s.</span> : null}{error.requestId ? <span className="error-field">Referencia: <code>{error.requestId}</code></span> : null}{canRetry || canResetRuns || canRetryCreate ? <button className="button button-secondary" type="button" data-action={action} disabled={retryBlocked} onClick={() => actions.onAction(action)}>{buttonLabel}</button> : null}</div>
    </section>
  );
}

export function renderErrorPanel(error: ApiError | null | undefined, options: { action?: ViewAction; retryUntil?: number | null } = {}): ReactElement | null {
  return errorPanel(error, { navigate: () => undefined, onRouteClick: () => undefined, onContextSubmit: () => undefined, onRunsSubmit: () => undefined, onAction: () => undefined }, options);
}

function errorTitle(error: Pick<ApiError, "code" | "status">): string {
  if (isCursorResetError(error)) return "Reinicia el listado";
  if (error.code === "INVALID_QUERY") return "Revisa los datos de consulta";
  if (error.code === "RUN_NOT_FOUND") return "Verificación no encontrada";
  if (error.code === "IDEMPOTENCY_CONFLICT") return "Conflicto recuperable";
  if (error.code === "RATE_LIMITED") return "Demasiadas solicitudes";
  if ((error.status || 0) >= 500 || ["NETWORK_ERROR", "MALFORMED_RESPONSE"].includes(error.code)) return "Fallo técnico de consulta";
  return "No se pudo completar la consulta";
}

function loadingState(label = "Cargando…"): ReactElement {
  return <section className="loading-state" role="status" aria-live="polite" aria-busy="true"><span className="loading-bar" /><span className="loading-bar short" /><strong>{label}</strong><span>No se reutilizan valores de otra consulta.</span></section>;
}

function runsPage(state: AppState, actions: ViewActions): ReactElement {
  const envelope = state.page.envelope as Envelope<unknown> | null;
  const listError = state.runs.error;
  const canNext = hasUsableNextPage(state.runs);
  return (
    <>
      {runsFilters(state, actions)}
      <section className="runs-actions"><div><p className="eyebrow">CONTROL BFF</p><p>La creación registra una verificación propia. No inicia una importación de OW.</p></div><button className="button button-primary" type="button" data-action="create-run" disabled={state.runs.creating || isRetryBlocked(state.retryUntil)} onClick={() => actions.onAction("create-run")}>{state.runs.creating ? "Creando…" : "Nueva verificación"}</button></section>
      {errorPanel(state.runs.createError, actions, { action: "retry-create", retryUntil: state.retryUntil })}
      {errorPanel(listError, actions, { action: isCursorResetError(listError) ? "reset-runs" : "retry", retryUntil: state.retryUntil })}
       <section className="table-panel" aria-labelledby="runs-title">
        <div className="section-heading"><div><p className="eyebrow">PÁGINA EN MEMORIA</p><h2 id="runs-title">Historial agregado</h2></div><span className="section-aside">Cursor opaco · límite 2</span></div>
        {state.runs.items.length === 0 ? <div className="table-empty"><strong>No hay verificaciones para este filtro.</strong><span>No se interpreta como una importación ausente.</span></div> : <><div className="responsive-table-wrap desktop-table" role="region" tabIndex={0} aria-label="Tabla de verificaciones; desliza horizontalmente para verla completa"><table className="data-table run-table"><caption>Verificaciones propias de esta sesión</caption><thead><tr><th scope="col">Identificador</th><th scope="col">Estado</th><th scope="col">Conteos</th><th scope="col">Tiempo</th></tr></thead><tbody>{runRows(state.runs.items, state.context.timezone, actions)}</tbody></table></div><div className="compact-card-list mobile-only" role="list" aria-label="Verificaciones propias de esta sesión">{runCards(state.runs.items, state.context.timezone, actions)}</div></>}
         <div className="pager-row"><span>{state.runs.loadingMore ? "Cargando la siguiente página…" : state.runs.hasNext ? "Hay otra página disponible." : "Fin normal del listado."}</span><button className="button button-secondary" type="button" data-action="next-page" disabled={!canNext || state.runs.loadingMore || isRetryBlocked(state.retryUntil)} onClick={() => actions.onAction("next-page")}>Cargar la siguiente página</button></div>
      </section>
      {warningsPanel(envelope?.warnings || [], "Advertencias del listado")}
    </>
  );
}

function resultRow(result: VerificationResult): ReactElement {
  if (result.state === "mismatch") {
    return <div className="result-row result-warning"><div><span className="result-label">{METRIC_LABELS[result.metric] || result.metric}</span><strong>Diferencia cerrada</strong></div><div className="result-values"><span>Esperado <strong>{formatResultNumber(result.expected, result.unit)}</strong></span><span>Observado <strong>{formatResultNumber(result.observed, result.unit)}</strong></span></div></div>;
  }
  const resultState = result.state === "match" ? "value" : result.state;
  return <div className="result-row"><div><span className="result-label">{METRIC_LABELS[result.metric] || result.metric}</span><strong>{result.state === "match" ? "Coincidencia cerrada" : stateLabel(resultState)}</strong></div><span className="result-explanation">{RESULT_REASON_COPY[result.reasonCode || ""] || safeStateCopy(resultState).detail}</span></div>;
}

function detailPage(state: AppState, actions: ViewActions): ReactElement {
  const envelope = state.page.envelope as Envelope<{ verificationRun: VerificationRun }>;
  const run = envelope.data?.verificationRun;
  if (!run) return <>{errorPanel(new ApiError({ code: "MALFORMED_RESPONSE" }), actions)}</>;
  return (
    <>
      <div className="detail-back"><a href="/verify/runs" onClick={(event) => actions.onRouteClick(event, "/verify/runs")}>← Volver al historial</a></div>
      <section className="detail-hero"><div><p className="eyebrow">IDENTIFICADOR OPACO BFF</p><h2>{run.runKey}</h2><p>El identificador es una referencia de la vista; no es un identificador de OW.</p></div><div>{stateBadge(run.state)}</div></section>
      <section className="detail-grid"><div className="detail-panel"><p className="eyebrow">ESTADO</p><h3>{stateLabel(run.state)}</h3><p>{safeStateCopy(run.state).detail}</p><dl className="detail-list"><div><dt>Solicitada</dt><dd>{formatTimestamp(run.requestedAt, run.scope.timezone)}</dd></div><div><dt>Iniciada</dt><dd>{run.startedAt ? formatTimestamp(run.startedAt, run.scope.timezone) : "Aún no"}</dd></div><div><dt>Finalizada</dt><dd>{run.finishedAt ? formatTimestamp(run.finishedAt, run.scope.timezone) : "Pendiente"}</dd></div></dl></div><div className="detail-panel"><p className="eyebrow">ALCANCE</p><h3>{run.scope.date}</h3><p>Zona efectiva: <strong>{run.scope.timezone}</strong></p><div className="domain-chips">{run.scope.domains.map((domain) => <span key={domain}>{DOMAIN_LABELS[domain] || domain}</span>)}</div></div></section>
      <section className="counts-panel" aria-labelledby="detail-counts-title"><div className="section-heading compact-heading"><div><p className="eyebrow">RESUMEN DE PROCESO</p><h2 id="detail-counts-title">Conteos, sin datos brutos</h2></div></div>{runCounts(run.counts)}</section>
      {run.results && run.results.length > 0 ? <section className="results-panel" aria-labelledby="results-title"><div className="section-heading compact-heading"><div><p className="eyebrow">RESULTADOS DE COMPARACIÓN</p><h2 id="results-title">Hallazgos permitidos</h2></div></div><div className="result-list">{run.results.map((result, index) => <div key={`${result.metric}-${index}`}>{resultRow(result)}</div>)}</div></section> : null}
      {warningsPanel([...run.warnings, ...envelope.warnings], "Advertencias de la verificación")}
    </>
  );
}

function settingsPage(state: AppState): ReactElement {
  const envelope = state.page.envelope as Envelope<SettingsData>;
  const data = envelope.data;
  if (!data) return <>{loadingState("Ajustes no disponibles")}</>;
  const capabilities = Object.entries(data.capabilities);
  // A future pinned reference needs an explicit contract update before rendering.
  const owReference = "Sin referencia fijada";
  return (
    <>
      <section className="settings-grid"><div className="settings-card settings-emphasis"><p className="eyebrow">CONTRATO EN USO</p><h2>{data.contract}</h2><p>El modelo de vista es propio del BFF. No es una copia de las respuestas internas de OW.</p><div className="settings-stamp">ESQUEMA {data.versions.bffSchema}</div></div><div className="settings-card"><p className="eyebrow">REFERENCIA</p><h2>{owReference}</h2><p>La referencia reproducible de OW sigue pendiente. Esta vista usa datos sintéticos adaptados.</p><span className="pending-line">Pendiente: referencia reproducible</span></div><div className="settings-card"><p className="eyebrow">ESTADO TÉCNICO</p><h2>{stateLabel(data.technicalState)}</h2><p>Describe la capacidad del BFF para describir el contrato; no garantiza datos para cada capacidad.</p>{stateBadge("readyTechnical")}</div></section>
      <section className="capabilities-panel" aria-labelledby="capabilities-title"><div className="section-heading"><div><p className="eyebrow">MATRIZ PÚBLICA</p><h2 id="capabilities-title">Capacidades y límites</h2></div><span className="section-aside">Sin mutaciones</span></div><div className="capability-grid">{capabilities.map(([key, value]) => { const copy = CAPABILITY_COPY[key] || { label: key }; return <article className="capability-card" key={key}><span className="capability-marker" aria-hidden="true">{value === "not_verifiable" ? "?" : "~"}</span><div><h3>{copy.label}</h3><strong>{copy[value] || value}</strong><p>{value === "not_verifiable" ? "La API pública no permite cerrar esta afirmación." : "Solo se muestra el nivel agregado declarado."}</p></div></article>; })}</div></section>
      <aside className="scope-note" aria-label="Alcance de ajustes"><div className="scope-note-mark" aria-hidden="true">i</div><div><strong>GPS no es un mapa.</strong><p>La disponibilidad de una capacidad no autoriza solicitar, guardar o dibujar coordenadas.</p></div></aside>
    </>
  );
}

function accessPage(state: AppState): ReactElement {
  const sessionError = state.sessionError;
  const sessionData = state.session?.data;
  const access = sessionData?.accessState || (["ACCESS_BLOCKED", "FORBIDDEN"].includes(sessionError?.code || "") ? "blocked" : sessionError?.code === "ACCESS_PENDING" ? "pending" : "anonymous");
  const title = access === "blocked" ? "Acceso bloqueado" : access === "pending" ? "Acceso pendiente" : "Sesión requerida";
  const text = access === "blocked" ? "Esta cuenta no puede consultar esta vista. No se muestran detalles de pertenencia." : access === "pending" ? "La identidad existe, pero el acceso a la consulta aún no está habilitado." : "El BFF debe establecer una sesión antes de consultar datos. Esta vista no elige una cuenta ni inicia una autenticación por su cuenta.";
  return <section className="access-state" role="status" aria-live="polite"><div className="access-glyph" aria-hidden="true">{access === "blocked" ? "!" : access === "pending" ? "Pendiente" : "↗"}</div><p className="eyebrow">CONTROL DE ACCESO</p><h2>{title}</h2><p>{text}</p><div className="access-meta"><span>Estado: {access === "blocked" ? "bloqueado" : access === "pending" ? "pendiente" : "anónimo"}</span><span>Consulta: detenida</span></div>{sessionError?.requestId ? <small>Referencia de soporte: <code>{sessionError.requestId}</code></small> : null}</section>;
}

function pageContent(state: AppState, actions: ViewActions): ReactElement {
  if (state.sessionStatus === "loading") return <>{pageHeading(state)}{loadingState("Abriendo sesión")}</>;
  if (state.sessionError && !state.session) {
    const accessError = ["SESSION_REQUIRED", "SESSION_EXPIRED", "ACCESS_PENDING", "ACCESS_BLOCKED", "FORBIDDEN"].includes(state.sessionError.code);
    return <>{pageHeading(state)}{accessError ? accessPage(state) : errorPanel(state.sessionError, actions, { retryUntil: state.retryUntil })}</>;
  }
  if (!state.session?.data || !state.session.data.canReadVerification || state.session.data.accessState !== "active") return <>{pageHeading(state)}{accessPage(state)}</>;
  if (state.page.status === "loading") return <>{pageHeading(state)}{state.route.name === "runs" ? runsFilters(state, actions) : null}{loadingState()}</>;
  if (state.page.status === "error") {
    const input = state.route.name === "runs" ? runsFilters(state, actions) : ["overview", "sources"].includes(state.route.name) ? contextForm(state, actions) : null;
    return <>{pageHeading(state)}{input}{errorPanel(state.page.error, actions, { action: state.route.name === "runs" && isCursorResetError(state.page.error) ? "reset-runs" : "retry", retryUntil: state.retryUntil })}</>;
  }
  if (state.route.name === "overview" && state.page.envelope) return <>{pageHeading(state)}{overviewPage(state, actions)}</>;
  if (state.route.name === "sources" && state.page.envelope) return <>{pageHeading(state)}{sourcesPage(state, actions)}</>;
  if (state.route.name === "runs") return <>{pageHeading(state)}{runsPage(state, actions)}</>;
  if (state.route.name === "detail" && state.page.envelope) return <>{pageHeading(state)}{detailPage(state, actions)}</>;
  if (state.route.name === "settings" && state.page.envelope) return <>{pageHeading(state)}{settingsPage(state)}</>;
  return <>{pageHeading(state)}{errorPanel(new ApiError({ status: 404, code: "NOT_FOUND" }), actions)}</>;
}

function announcement(state: AppState): string {
  if (state.sessionStatus === "loading" || state.page.status === "loading") return "Cargando la consulta.";
  if (state.sessionError && !state.session) {
    if (state.sessionError.code === "RATE_LIMITED") return "Consulta limitada temporalmente.";
    if (["SESSION_REQUIRED", "SESSION_EXPIRED", "ACCESS_PENDING", "ACCESS_BLOCKED", "FORBIDDEN"].includes(state.sessionError.code)) return "No se pudo establecer el acceso.";
    return "La sesión no pudo completarse por un error técnico.";
  }
  if (state.page.status === "error") {
    if (state.page.error?.code === "INVALID_QUERY") return "Revisa los datos de consulta.";
    if (state.page.error?.code === "RATE_LIMITED") return "Consulta limitada temporalmente.";
    return "La consulta terminó con un error técnico.";
  }
  if (!state.session?.data || !state.session.data.canReadVerification || state.session.data.accessState !== "active") return "La consulta está detenida por el estado de acceso.";
  if (state.route.name === "overview") {
    const summary = (state.page.envelope as Envelope<OverviewData> | null)?.data?.summary || {};
    if (Object.keys(summary).length === 0) return "Ventana completa sin observaciones.";
    const warningCount = state.page.envelope?.warnings.length || 0;
    return warningCount > 0 ? `Resumen disponible con ${warningCount} advertencia${warningCount === 1 ? "" : "s"}.` : "Resumen disponible.";
  }
  if (state.route.name === "sources") {
    const count = ((state.page.envelope as Envelope<{ items: Source[] }> | null)?.data?.items.length || 0);
    return count === 0 ? "No hay fuentes para esta consulta." : `${count} fuente${count === 1 ? "" : "s"} disponible${count === 1 ? "" : "s"}.`;
  }
  if (state.route.name === "runs") return state.runs.items.length === 0 ? "No hay verificaciones para este filtro." : "Historial de verificaciones actualizado.";
  if (state.route.name === "detail") return "Detalle de verificación disponible.";
  if (state.route.name === "settings") return "Ajustes de lectura disponibles.";
  return "Vista actualizada.";
}

export function AppView({ state, actions }: { state: AppState; actions: ViewActions }): ReactElement {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Saltar al contenido</a>
      {renderHeader(state, actions)}
      <div className="app-body"><>{renderNav(state, actions)}</><main id="main-content" className="main-content" tabIndex={-1}>{pageContent(state, actions)}</main></div>
      <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true">{announcement(state)}</div>
    </div>
  );
}
