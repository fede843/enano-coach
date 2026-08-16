import { METRIC_LABELS, SAFE_WARNING_COPY, STATE_COPY } from "./copy";
import type { Metric, Warning } from "./types";

export function safeStateCopy(state: string) {
  return STATE_COPY[state as keyof typeof STATE_COPY] || STATE_COPY.error;
}

export function stateLabel(state: string): string {
  return safeStateCopy(state).label;
}

export function warningText(warning: Pick<Warning, "code"> | null | undefined): string {
  return SAFE_WARNING_COPY[warning?.code || ""] || "Advertencia sin detalle público.";
}

export function metricLabel(key: string): string {
  return METRIC_LABELS[key] || "Lectura";
}

export function formatNumber(value: number | null | undefined, maximumFractionDigits = 0): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "Sin medición";
  }
  return new Intl.NumberFormat("es-ES", { maximumFractionDigits }).format(value);
}

export function formatMetricValue(metric: Metric | null | undefined): { value: string; unit: string; isValue: boolean } {
  if (!metric || metric.value === null || metric.value === undefined) {
    return { value: metric?.state === "empty" ? "Sin datos" : "Sin medición", unit: "", isValue: false };
  }
  if (metric.unit === "meters") {
    return { value: formatNumber(metric.value / 1000, 1), unit: "km", isValue: true };
  }
  if (metric.unit === "seconds") {
    const minutes = metric.value / 60;
    if (minutes >= 60) {
      return { value: formatNumber(minutes / 60, 1), unit: "h", isValue: true };
    }
    return { value: formatNumber(minutes, 0), unit: "min", isValue: true };
  }
  if (metric.unit === "count") {
    return { value: formatNumber(metric.value), unit: "", isValue: true };
  }
  if (metric.unit === null) {
    return { value: formatNumber(metric.value, 1), unit: "", isValue: true };
  }
  return { value: formatNumber(metric.value, 1), unit: metric.unit, isValue: true };
}

export function formatMetricDetail(key: string, metric: Metric | null | undefined): string {
  if (!metric) {
    return "No hay un campo para esta lectura.";
  }
  if (metric.state === "partial") {
    const fraction = metric.coverage?.observedFraction;
    const percent = typeof fraction === "number" ? formatNumber(fraction * 100, 0) : "No disponible";
    return `${percent}% observado; la ventana no está completa.`;
  }
  if (metric.state === "source_ambiguous") {
    return "Lectura recibida, pero la atribución de fuente es ambigua.";
  }
  if (metric.state === "unsupported") {
    return "No soportado por esta fuente; no se estima ni se reintenta.";
  }
  if (metric.state === "empty") {
    return "Ventana completa sin observaciones.";
  }
  if (metric.state === "null") {
    return "Sin medición: el contrato conservó el valor nulo.";
  }
  if (metric.state === "error") {
    return "Fallo técnico; no se afirma un total diario.";
  }
  if (metric.state === "pending") {
    return "Proceso pendiente; no se afirma un total diario.";
  }
  if (metric.state === "inconclusive") {
    return "La consulta no pudo cerrarse; no se afirma un total diario.";
  }
  if (metric.state === "not_verifiable") {
    return "La API disponible no puede probar esta lectura ni su total diario.";
  }
  if (key === "heartRate" && ["value", "zero"].includes(metric.state)) {
    return "Lectura escalar; no se calcula un estadístico adicional.";
  }
  if (metric.isDailyTotal === true) {
    return "Total diario declarado; no se vuelve a sumar.";
  }
  if (metric.isDailyTotal === null) {
    return "Semántica de total diario no declarada.";
  }
  return metric.isDailyTotal === false ? "Lectura no marcada como total diario." : safeStateCopy(metric.state).detail;
}

export function formatCount(value: number | null | undefined): string {
  return value === null || value === undefined ? "Sin dato" : formatNumber(value);
}

export function formatTimestamp(value: string | null | undefined, timezone = "UTC"): string {
  if (!value) {
    return "Sin fecha";
  }
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) {
    return "Fecha no disponible";
  }
  try {
    return new Intl.DateTimeFormat("es-ES", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: timezone
    }).format(date);
  } catch {
    return "Fecha no disponible";
  }
}

export function formatUtcTimestamp(value: string | null | undefined): string {
  return value ? `${value} UTC` : "Sin momento de generación";
}

export function formatCoverageFraction(coverage: Metric["coverage"]): string {
  if (!coverage || typeof coverage.observedFraction !== "number") {
    return "Cobertura no disponible";
  }
  return `${formatNumber(coverage.observedFraction * 100, 0)}% observado`;
}

export function formatResultNumber(value: number | null | undefined, unit?: string): string {
  if (value === null || value === undefined) {
    return "Sin dato";
  }
  return `${formatNumber(value, unit === "count" ? 0 : 1)}${unit ? ` ${unit}` : ""}`;
}
