import { startTransition, useEffect, useRef, useState, type FormEvent, type MouseEvent, type ReactElement } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { ApiError, InvalidResponse, createIdempotencyKey, type IdempotencyKey } from "./api";
import { isRetryBlocked, retryGateRemaining, retryRequestKind, shouldHandleRouteClick } from "./controller-state";
import { isCursorResetError, dedupeRuns, hasUsableNextPage, resetRunsList } from "./runs";
import {
  queryKeys,
  useCreateRunMutation,
  useOverviewQuery,
  useRunDetailQuery,
  useRunsQuery,
  useSessionQuery,
  useSettingsQuery,
  useSourcesQuery
} from "./queries";
import { focusInvalidField } from "./validation";
import { AppView, type ViewAction, type ViewActions } from "./view";
import type {
  AppRoute,
  AppState,
  Envelope,
  PageState,
  RunsState,
} from "./types";

const DEFAULT_DATE = "2024-01-02";
const DEFAULT_TIMEZONE = "UTC";

type Context = { date: string; timezone: string };
type RunFilters = { from: string; to: string; state: string };

export function routeFromPath(pathname: string): AppRoute {
  if (pathname === "/" || pathname === "/verify") return { name: "overview", path: "/verify" };
  if (pathname === "/verify/sources") return { name: "sources", path: pathname };
  if (pathname === "/verify/runs") return { name: "runs", path: pathname };
  if (pathname === "/verify/settings") return { name: "settings", path: pathname };
  const detail = pathname.match(/^\/verify\/runs\/(verify-demo-[a-z0-9-]+)$/);
  if (detail) return { name: "detail", path: pathname, runKey: detail[1] };
  return { name: "unknown", path: pathname };
}

function emptyPage(): PageState {
  return { status: "idle", envelope: null, error: null };
}

function initialRuns(): RunsState {
  return {
    filters: { from: "", to: "", state: "" },
    items: [],
    nextCursor: null,
    hasNext: false,
    loadingMore: false,
    error: null,
    createError: null,
    createKey: null,
    seenCursors: new Set(),
    creating: false
  };
}

export function initialState(pathname = typeof window === "undefined" ? "/verify" : window.location.pathname): AppState {
  return {
    route: routeFromPath(pathname),
    context: { date: DEFAULT_DATE, timezone: DEFAULT_TIMEZONE },
    sessionStatus: "loading",
    session: null,
    sessionError: null,
    retryUntil: null,
    retryError: null,
    page: { status: "loading", envelope: null, error: null },
    runs: initialRuns()
  };
}

function asApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (error instanceof InvalidResponse) return new ApiError({ code: "MALFORMED_RESPONSE", retryable: false });
  return new ApiError({ code: "NETWORK_ERROR", retryable: true });
}

function useRateLimitGate(error: ApiError | null): number | null {
  const [retryUntil, setRetryUntil] = useState<number | null>(null);

  useEffect(() => {
    const delay = error?.code === "RATE_LIMITED" ? error.retryAfterMs : null;
    if (!Number.isFinite(delay) || (delay || 0) <= 0) {
      setRetryUntil(null);
      return undefined;
    }
    const deadline = Date.now() + (delay || 0);
    setRetryUntil(deadline);
    const timer = setTimeout(() => setRetryUntil(null), delay || 0);
    return () => clearTimeout(timer);
  }, [error?.code, error?.requestId, error?.retryAfterMs]);

  return retryUntil;
}

function queryError(error: unknown): ApiError | null {
  return error === null || error === undefined ? null : asApiError(error);
}

function isAuthError(error: ApiError | null): boolean {
  return error !== null && ([401, 403].includes(error.status) || ["SESSION_REQUIRED", "SESSION_EXPIRED", "ACCESS_PENDING", "ACCESS_BLOCKED", "FORBIDDEN"].includes(error.code));
}

function pageFromQuery<T>(query: { data?: Envelope<T>; error?: unknown; isPending: boolean; isFetching: boolean }, enabled: boolean): PageState {
  if (!enabled) return emptyPage();
  const error = queryError(query.error);
  if (query.isPending || query.isFetching) return { status: "loading", envelope: null, error: null };
  if (error) return { status: "error", envelope: null, error };
  return { status: "ready", envelope: query.data || null, error: null };
}

function routeQueryState(
  route: AppRoute,
  active: boolean,
  overviewQuery: ReturnType<typeof useOverviewQuery>,
  sourcesQuery: ReturnType<typeof useSourcesQuery>,
  settingsQuery: ReturnType<typeof useSettingsQuery>,
  detailQuery: ReturnType<typeof useRunDetailQuery>
): PageState {
  if (route.name === "overview") return pageFromQuery(overviewQuery, active);
  if (route.name === "sources") return pageFromQuery(sourcesQuery, active);
  if (route.name === "settings") return pageFromQuery(settingsQuery, active);
  if (route.name === "detail") return pageFromQuery(detailQuery, active);
  if (route.name === "unknown") return { status: "error", envelope: null, error: new ApiError({ status: 404, code: "NOT_FOUND" }) };
  return emptyPage();
}

function RouterScreen({ context, setContext }: { context: Context; setContext: (context: Context) => void }): ReactElement {
  const location = useLocation();
  const routerNavigate = useNavigate();
  const params = useParams<{ runKey?: string }>();
  const queryClient = useQueryClient();
  const routeFromLocation = routeFromPath(location.pathname);
  const route: AppRoute = routeFromLocation.name === "detail"
    ? { ...routeFromLocation, runKey: params.runKey || routeFromLocation.runKey }
    : routeFromLocation;
  const [filters, setFilters] = useState<RunFilters>({ from: "", to: "", state: "" });
  const [createKey, setCreateKey] = useState<IdempotencyKey | null>(null);
  const [createLocalError, setCreateLocalError] = useState<ApiError | null>(null);
  const focusMainAfterRender = useRef(false);
  const createController = useRef<AbortController | null>(null);

  const sessionQuery = useSessionQuery();
  const sessionError = queryError(sessionQuery.error);
  const session = sessionQuery.data;
  const sessionBusy = sessionQuery.isPending || sessionQuery.isFetching;
  const active = !sessionBusy && !sessionError && session?.data?.accessState === "active" && session.data.canReadVerification === true;
  const overviewQuery = useOverviewQuery(context, active && route.name === "overview");
  const sourcesQuery = useSourcesQuery(context, active && route.name === "sources");
  const settingsQuery = useSettingsQuery(active && route.name === "settings");
  const runsQuery = useRunsQuery(filters, context.timezone, active && route.name === "runs");
  const detailQuery = useRunDetailQuery(route.runKey, active && route.name === "detail");
  const createMutation = useCreateRunMutation(() => createController.current?.signal);

  const runsError = queryError(runsQuery.error);
  const detailError = queryError(detailQuery.error);
  const routePage = routeQueryState(route, active, overviewQuery, sourcesQuery, settingsQuery, detailQuery);
  const routeError = routePage.error || (route.name === "runs" ? runsError : detailError);
  const routeAuthError = isAuthError(routeError);
  const effectiveSession = routeAuthError || sessionError ? null : session;
  const effectiveSessionError = routeAuthError ? routeError : sessionError;
  const createError = createLocalError || queryError(createMutation.error);
  const retryError = effectiveSessionError || routeError || createError;
  const retryUntil = useRateLimitGate(retryError);
  const runPages = runsQuery.data?.pages || [];
  const runItems = dedupeRuns([], runPages.flatMap((page) => page.data?.items || []));
  const lastRunsEnvelope = runPages.length > 0 ? runPages[runPages.length - 1] : null;
  const lastRunsPage = lastRunsEnvelope?.data?.page;
  const seenCursors = new Set(
    (runsQuery.data?.pageParams || []).filter((cursor): cursor is string => typeof cursor === "string")
  );
  const runsPage: PageState = !active
    ? emptyPage()
    : runsQuery.isPending || (runsQuery.isFetching && !runsQuery.isFetchingNextPage)
      ? { status: "loading", envelope: null, error: null }
      : runsError && !runsQuery.data
        ? { status: "error", envelope: null, error: runsError }
        : { status: "ready", envelope: lastRunsEnvelope, error: null };
  const page = route.name === "runs" ? runsPage : routePage;

  useEffect(() => {
    return () => {
      createController.current?.abort();
      createController.current = null;
    };
  }, []);

  useEffect(() => {
    if (!focusMainAfterRender.current || page.status === "loading") return;
    focusMainAfterRender.current = false;
    const validationField = page.error?.code === "INVALID_QUERY"
      ? page.error.field
      : runsError?.code === "INVALID_QUERY"
        ? runsError.field
        : null;
    if (focusInvalidField(validationField)) return;
    document.getElementById("main-content")?.focus({ preventScroll: true });
  }, [location.pathname, page.status, page.error?.field, runsError?.field, runItems.length, runsQuery.isFetchingNextPage]);

  function navigate(path: string): void {
    if (location.pathname === path) return;
    focusMainAfterRender.current = true;
    startTransition(() => routerNavigate(path));
  }

  function onRouteClick(event: MouseEvent<HTMLAnchorElement>, path: string): void {
    if (shouldHandleRouteClick(event.nativeEvent)) {
      event.preventDefault();
      navigate(path);
    }
  }

  function onContextSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (isRetryBlocked(retryUntil)) return;
    const values = new FormData(event.currentTarget);
    focusMainAfterRender.current = true;
    setContext({ date: String(values.get("date") || DEFAULT_DATE), timezone: String(values.get("timezone") || DEFAULT_TIMEZONE) });
  }

  function onRunsSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (isRetryBlocked(retryUntil) || runsPage.status === "loading") return;
    const values = new FormData(event.currentTarget);
    focusMainAfterRender.current = true;
    setFilters({ from: String(values.get("from") || ""), to: String(values.get("to") || ""), state: String(values.get("state") || "") });
  }

  async function createRun({ newAttempt = false, retry = false }: { newAttempt?: boolean; retry?: boolean } = {}): Promise<void> {
    if (createMutation.isPending || isRetryBlocked(retryUntil)) return;
    let nextKey = createKey;
    try {
      if (newAttempt || (!retry && !nextKey)) nextKey = createIdempotencyKey();
    } catch (error) {
      setCreateLocalError(asApiError(error));
      return;
    }
    if (!nextKey) return;
    setCreateLocalError(null);
    createMutation.reset();
    createController.current?.abort();
    const controller = new AbortController();
    createController.current = controller;
    setCreateKey(nextKey);
    try {
      const envelope = await createMutation.mutateAsync({
        date: context.date,
        timezone: context.timezone,
        domains: ["activity", "sleep", "recovery", "body"],
        idempotencyKey: nextKey
      });
      if (controller.signal.aborted || createController.current !== controller) return;
      if (!envelope.data) throw new ApiError({ code: "MALFORMED_RESPONSE", retryable: false });
      setCreateKey(null);
      setCreateLocalError(null);
      navigate(`/verify/runs/${encodeURIComponent(envelope.data.verificationRun.runKey)}`);
    } catch (error) {
      if (controller.signal.aborted || createController.current !== controller) return;
      if (error instanceof Error && error.name === "AbortError") return;
      const safeError = asApiError(error);
      if (!safeError.retryable && safeError.code !== "IDEMPOTENCY_CONFLICT") setCreateKey(null);
    } finally {
      if (createController.current === controller) createController.current = null;
    }
  }

  function onAction(action: ViewAction): void {
    if (isRetryBlocked(retryUntil)) return;
    focusMainAfterRender.current = true;
    if (action === "next-page") {
      if (hasUsableNextPage({ hasNext: lastRunsPage?.hasNext === true, nextCursor: lastRunsPage?.nextCursor || null, seenCursors })) {
        void runsQuery.fetchNextPage();
      }
    } else if (action === "reset-runs") {
      void queryClient.resetQueries({ queryKey: queryKeys.runs(filters.from, filters.to, filters.state, context.timezone) });
    } else if (action === "retry") {
      if (routeAuthError) {
        void sessionQuery.refetch().then(() => {
          if (route.name === "overview") void overviewQuery.refetch();
          else if (route.name === "sources") void sourcesQuery.refetch();
          else if (route.name === "settings") void settingsQuery.refetch();
          else if (route.name === "runs") void runsQuery.refetch();
          else void detailQuery.refetch();
        });
      } else if (retryRequestKind({ session: effectiveSession || null, sessionError: effectiveSessionError } as AppState)) void sessionQuery.refetch();
      else if (route.name === "overview") void overviewQuery.refetch();
      else if (route.name === "sources") void sourcesQuery.refetch();
      else if (route.name === "settings") void settingsQuery.refetch();
      else if (route.name === "runs") void runsQuery.refetch();
      else void detailQuery.refetch();
    } else if (action === "retry-create") {
      void createRun({ retry: true });
    } else if (action === "create-run") {
      void createRun({ newAttempt: true });
    }
  }

  const runsState: RunsState = {
    filters,
    items: runItems,
    nextCursor: lastRunsPage?.nextCursor || null,
    hasNext: lastRunsPage?.hasNext === true,
    loadingMore: runsQuery.isFetchingNextPage,
    error: runsError,
    createError,
    createKey,
    seenCursors,
    creating: createMutation.isPending
  };
  const state: AppState = {
    route,
    context,
    sessionStatus: sessionBusy ? "loading" : "ready",
    session: effectiveSession || null,
    sessionError: effectiveSessionError,
    retryUntil,
    retryError,
    page,
    runs: runsState
  };
  const actions: ViewActions = { navigate, onRouteClick, onContextSubmit, onRunsSubmit, onAction };

  return <AppView state={state} actions={actions} />;
}

export default function App(): ReactElement {
  const [context, setContext] = useState<Context>({ date: DEFAULT_DATE, timezone: DEFAULT_TIMEZONE });

  return (
    <Routes>
      <Route path="/" element={<Navigate to="/verify" replace />} />
      <Route element={<RouterScreen context={context} setContext={setContext} />} path="/verify" />
      <Route element={<RouterScreen context={context} setContext={setContext} />} path="/verify/sources" />
      <Route element={<RouterScreen context={context} setContext={setContext} />} path="/verify/runs" />
      <Route element={<RouterScreen context={context} setContext={setContext} />} path="/verify/runs/:runKey" />
      <Route element={<RouterScreen context={context} setContext={setContext} />} path="/verify/settings" />
      <Route element={<RouterScreen context={context} setContext={setContext} />} path="*" />
    </Routes>
  );
}
