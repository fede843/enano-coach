import type { ApiError } from "./api";
import type { RunsState, RunItem } from "./types";

export function isValidCursor(cursor: unknown): cursor is string {
  return typeof cursor === "string"
    && cursor.length > 0
    && cursor.length <= 256
    && !/[\u0000-\u001f\u007f]/.test(cursor);
}

const CURSOR_RESET_CODES = new Set(["INVALID_CURSOR", "CURSOR_CONTEXT_MISMATCH", "CURSOR_EXPIRED"]);

export function isCursorResetError(error: Pick<ApiError, "code"> | null | undefined): boolean {
  return CURSOR_RESET_CODES.has(error?.code || "");
}

export function hasUsableNextPage({
  hasNext,
  nextCursor,
  seenCursors
}: Pick<RunsState, "hasNext" | "nextCursor" | "seenCursors">): boolean {
  return hasNext === true
    && isValidCursor(nextCursor)
    && !seenCursors.has(nextCursor);
}

export function dedupeRuns(existing: RunItem[], incoming: RunItem[]): RunItem[] {
  const seen = new Set<string>();
  const merged: RunItem[] = [];
  for (const item of [...existing, ...incoming]) {
    if (!item || typeof item.runKey !== "string" || seen.has(item.runKey)) {
      continue;
    }
    seen.add(item.runKey);
    merged.push(item);
  }
  return merged;
}

export function resetRunsList(runs: RunsState): RunsState {
  return {
    ...runs,
    items: [],
    nextCursor: null,
    hasNext: false,
    loadingMore: false,
    error: null,
    createError: null,
    creating: false,
    seenCursors: new Set()
  };
}
