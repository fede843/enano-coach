import {
  QueryClient,
  type InfiniteData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient
} from "@tanstack/react-query";

import {
  createVerificationRun,
  getOverview,
  getRunDetail,
  getRuns,
  getSession,
  getSettings,
  getSources,
  type ApiError,
  type IdempotencyKey
} from "./api";
import type {
  Envelope,
  OverviewData,
  RunsPageData,
  SessionData,
  SettingsData,
  Source,
  VerificationRun
} from "./types";

export const RUN_LIMIT = 2;

export const queryKeys = Object.freeze({
  session: ["session"] as const,
  overview: (date: string, timezone: string) => ["verification-overview", date, timezone] as const,
  sources: (date: string, timezone: string) => ["verification-sources", date, timezone] as const,
  settings: ["verification-settings"] as const,
  runs: (from: string, to: string, state: string, timezone: string) => ["verification-runs", from, to, state, timezone, RUN_LIMIT] as const,
  runDetail: (runKey: string) => ["verification-run", runKey] as const
});

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        gcTime: 0,
        staleTime: 0,
        refetchOnReconnect: false,
        refetchOnWindowFocus: false,
        retry: false
      },
      mutations: {
        retry: false
      }
    }
  });
}

export function useSessionQuery() {
  return useQuery<Envelope<SessionData>, ApiError>({
    queryKey: queryKeys.session,
    queryFn: ({ signal }) => getSession({ signal })
  });
}

export function useOverviewQuery(context: { date: string; timezone: string }, enabled: boolean) {
  return useQuery<Envelope<OverviewData>, ApiError>({
    queryKey: queryKeys.overview(context.date, context.timezone),
    queryFn: ({ signal }) => getOverview(context, { signal }),
    enabled
  });
}

export function useSourcesQuery(context: { date: string; timezone: string }, enabled: boolean) {
  return useQuery<Envelope<{ items: Source[] }>, ApiError>({
    queryKey: queryKeys.sources(context.date, context.timezone),
    queryFn: ({ signal }) => getSources(context, { signal }),
    enabled
  });
}

export function useSettingsQuery(enabled: boolean) {
  return useQuery<Envelope<SettingsData>, ApiError>({
    queryKey: queryKeys.settings,
    queryFn: ({ signal }) => getSettings({ signal }),
    enabled
  });
}

export function useRunsQuery(filters: { from: string; to: string; state: string }, timezone: string, enabled: boolean) {
  return useInfiniteQuery<Envelope<RunsPageData>, ApiError, InfiniteData<Envelope<RunsPageData>, string | null>, ReturnType<typeof queryKeys.runs>, string | null>({
    queryKey: queryKeys.runs(filters.from, filters.to, filters.state, timezone),
    queryFn: ({ pageParam, signal }) => getRuns({
      from: filters.from,
      to: filters.to,
      state: filters.state,
      limit: RUN_LIMIT,
      cursor: pageParam
    }, { signal }),
    initialPageParam: null,
    getNextPageParam: (lastPage) => {
      if (!lastPage.data?.page.hasNext) return undefined;
      return lastPage.data.page.nextCursor;
    },
    enabled
  });
}

export function useRunDetailQuery(runKey: string | undefined, enabled: boolean) {
  return useQuery<Envelope<{ verificationRun: VerificationRun }>, ApiError>({
    queryKey: queryKeys.runDetail(runKey || "unknown"),
    queryFn: ({ signal }) => getRunDetail(runKey || "", { signal }),
    enabled: enabled && runKey !== undefined
  });
}

export interface CreateRunInput {
  date: string;
  timezone: string;
  domains: string[];
  idempotencyKey: IdempotencyKey;
}

export function useCreateRunMutation(getSignal: () => AbortSignal | undefined) {
  const queryClient = useQueryClient();
  return useMutation<Envelope<{ verificationRun: VerificationRun }>, ApiError, CreateRunInput>({
    mutationFn: ({ date, timezone, domains, idempotencyKey }) => createVerificationRun({ date, timezone, domains, idempotencyKey }, { signal: getSignal() }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["verification-runs"] });
    }
  });
}
