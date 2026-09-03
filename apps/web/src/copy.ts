export const NAV_ITEMS = [
  { route: "/verify", label: "Verificación", shortLabel: "Día", mark: "01" },
  { route: "/verify/sources", label: "Fuentes", shortLabel: "Fuentes", mark: "02" },
  { route: "/verify/runs", label: "Verificaciones", shortLabel: "Historial", mark: "03" },
  { route: "/verify/settings", label: "Ajustes", shortLabel: "Ajustes", mark: "04" }
] as const;

export const PAGE_COPY = {
  overview: {
    eyebrow: "VERIFICACIÓN / 01",
    title: "Registro diario",
    description: "Una lectura puntual, su cobertura y los límites que la acompañan."
  },
  sources: {
    eyebrow: "PROVENIENCIA / 02",
    title: "Fuentes visibles",
    description: "Inventario sanitizado. Disponible no significa que haya datos."
  },
  runs: {
    eyebrow: "HISTORIAL / 03",
    title: "Verificaciones de lectura",
    description: "Estados agregados del control BFF, no una importación de OW."
  },
  detail: {
    eyebrow: "DETALLE / VERIFICACIÓN",
    title: "Resultado agregado",
    description: "Solo el alcance, el estado, los conteos y los hallazgos permitidos."
  },
  settings: {
    eyebrow: "CONTRATO / 04",
    title: "Ajustes de lectura",
    description: "Versiones y capacidades declaradas, sin formularios ni secretos."
  }
} as const;

export const TIMEZONES = [
  "America/Argentina/Buenos_Aires",
  "UTC",
  "Europe/Madrid",
  "America/New_York",
  "America/Los_Angeles",
  "Asia/Tokyo"
] as const;

export const RUN_FILTER_STATES = [
  { value: "", label: "Todos los estados" },
  { value: "persisted", label: "Confirmada" },
  { value: "partial", label: "Parcial" },
  { value: "pending", label: "Pendiente" },
  { value: "failed", label: "Fallida" },
  { value: "cancelled", label: "Cancelada" },
  { value: "skipped", label: "Omitida" },
  { value: "completed_with_findings", label: "Con hallazgos" },
  { value: "not_verifiable", label: "No verificable" },
  { value: "inconclusive", label: "Inconclusa" }
] as const;

export const METRIC_ORDER = [
  "steps",
  "distanceMeters",
  "activeCaloriesKcal",
  "sleepDurationSeconds",
  "recoveryScore",
  "stress",
  "heartRate"
] as const;

export type MetricKey = typeof METRIC_ORDER[number];

export const METRIC_LABELS: Record<string, string> = {
  steps: "Pasos",
  distanceMeters: "Distancia",
  activeCaloriesKcal: "Calorías activas",
  sleepDurationSeconds: "Sueño publicado",
  recoveryScore: "Recuperación",
  stress: "Estrés",
  heartRate: "Frecuencia cardíaca"
};

export const METRIC_DOMAINS: Record<string, string> = {
  steps: "Actividad",
  distanceMeters: "Actividad",
  activeCaloriesKcal: "Actividad",
  sleepDurationSeconds: "Sueño",
  recoveryScore: "Recuperación",
  stress: "Contrato",
  heartRate: "Proveniencia"
};

export const SOURCE_CAPABILITY_LABELS: Record<string, string> = {
  activity: "Actividad",
  body: "Composición corporal",
  heart_rate: "Frecuencia cardíaca",
  sleep: "Sueño"
};

export const DOMAIN_LABELS: Record<string, string> = {
  activity: "Actividad",
  body: "Composición corporal",
  recovery: "Recuperación",
  sleep: "Sueño",
  sources: "Fuentes",
  workouts: "Entrenamientos"
};

export const RESULT_REASON_COPY: Record<string, string> = {
  CURSOR_EXPIRED: "El cursor expiró.",
  NO_PUBLIC_WORKOUT_DETAIL: "No hay detalle público de entrenamiento."
};

export const SAFE_WARNING_COPY: Record<string, string> = {
  BODY_RELATIVE_TO_NOW: "Los datos corporales son relativos al momento de consulta, no a la fecha lógica.",
  CURSOR_EXPIRED: "La página expiró; reinicia el listado.",
  INCONCLUSIVE: "No se pudo cerrar la comparación porque faltó una página.",
  MISMATCH: "El hecho observado no coincide con el esperado.",
  NOT_VERIFIABLE: "La API pública no ofrece el esquema necesario para esta afirmación.",
  PARTIAL_COVERAGE: "La ventana solo tiene observaciones parciales.",
  SOURCE_AMBIGUOUS: "No hay una fuente única para esta lectura.",
  UNSUPPORTED: "La capacidad solicitada no está disponible en el contrato.",
  UPSTREAM_LIMITED: "La fuente limitó el alcance de la consulta."
};

export const STATE_COPY = {
  empty: { label: "Sin datos", tone: "neutral", detail: "Ventana completa sin observaciones." },
  value: { label: "Observado", tone: "good", detail: "Observación numérica válida recibida." },
  zero: { label: "Cero real", tone: "accent", detail: "Cero confirmado por el contrato." },
  null: { label: "Sin medición", tone: "neutral", detail: "El campo está presente como nulo." },
  partial: { label: "Parcial", tone: "warn", detail: "Solo una parte de la ventana está cubierta." },
  unsupported: { label: "No soportado", tone: "neutral", detail: "No hay capacidad pública para esta lectura." },
  ready: { label: "Disponible", tone: "good", detail: "Fuente única con proveniencia suficiente." },
  pending: { label: "Pendiente", tone: "warn", detail: "Proceso no terminal; no confirma persistencia." },
  completed_with_findings: { label: "Con hallazgos", tone: "warn", detail: "Resultado terminal con una diferencia cerrada." },
  error: { label: "Error", tone: "bad", detail: "Fallo técnico; no es una ventana vacía." },
  source_ambiguous: { label: "Fuente ambigua", tone: "warn", detail: "No se elige una fuente en silencio." },
  not_verifiable: { label: "No verificable", tone: "neutral", detail: "La API disponible no puede probar esta afirmación." },
  inconclusive: { label: "Inconclusa", tone: "warn", detail: "La consulta no pudo cerrarse." },
  persisted: { label: "Confirmada", tone: "good", detail: "Verificación terminal sin hallazgos." },
  failed: { label: "Fallida", tone: "bad", detail: "El proceso terminó con error." },
  cancelled: { label: "Cancelada", tone: "neutral", detail: "El proceso no confirma persistencia completa." },
  skipped: { label: "Omitida", tone: "neutral", detail: "La operación no se ejecutó para el alcance." },
  readyTechnical: { label: "Lista", tone: "good", detail: "El contrato puede describirse." }
} as const;

export const CAPABILITY_COPY: Record<string, Record<string, string>> = {
  gps: {
    label: "GPS / rutas",
    aggregate_only: "Solo disponibilidad agregada",
    not_verifiable: "No verificable"
  },
  workoutDetails: {
    label: "Detalle de entrenamiento",
    aggregate_only: "Solo agregado",
    not_verifiable: "No verificable"
  },
  segments: {
    label: "Segmentos",
    aggregate_only: "Solo agregado",
    not_verifiable: "No verificable"
  },
  hrZones: {
    label: "Zonas de frecuencia cardíaca",
    aggregate_only: "Solo agregado",
    not_verifiable: "No verificable"
  }
};
