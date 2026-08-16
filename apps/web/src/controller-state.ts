import type { AppState } from "./types";

export function retryRequestKind(state: Pick<AppState, "session" | "sessionError">): "session" | "route" {
  return state.sessionError && !state.session ? "session" : "route";
}

export function retryGateRemaining(retryUntil: number | null, now = Date.now()): number {
  if (!Number.isFinite(retryUntil) || !Number.isFinite(now)) {
    return 0;
  }
  return Math.max(0, (retryUntil || 0) - now);
}

export function isRetryBlocked(retryUntil: number | null, now = Date.now()): boolean {
  return retryGateRemaining(retryUntil, now) > 0;
}

export function shouldHandleRouteClick(event: Pick<MouseEvent, "button" | "metaKey" | "ctrlKey" | "shiftKey" | "altKey">): boolean {
  return event.button === 0
    && event.metaKey !== true
    && event.ctrlKey !== true
    && event.shiftKey !== true
    && event.altKey !== true;
}
