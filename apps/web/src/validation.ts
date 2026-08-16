const VALIDATION_FIELD_IDS = Object.freeze({
  date: "context-date",
  timezone: "context-timezone",
  from: "runs-from",
  to: "runs-to",
  state: "runs-state"
} as const);

export function validationFieldId(field: string | null | undefined): string | null {
  if (!field || !Object.prototype.hasOwnProperty.call(VALIDATION_FIELD_IDS, field)) {
    return null;
  }
  return VALIDATION_FIELD_IDS[field as keyof typeof VALIDATION_FIELD_IDS];
}

export function validationErrorId(field: string | null | undefined): string | null {
  const controlId = validationFieldId(field);
  return controlId ? `${controlId}-error` : null;
}

export function focusInvalidField(field: string | null | undefined): boolean {
  const controlId = validationFieldId(field);
  if (!controlId || typeof document === "undefined") {
    return false;
  }
  const control = document.getElementById(controlId);
  if (!control || typeof control.focus !== "function") {
    return false;
  }
  control.focus({ preventScroll: true });
  return true;
}
