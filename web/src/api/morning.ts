import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";

export interface Report {
  id: number;
  report_date: string;
  version_no: number;
  is_primary: boolean;
  status: string;
  title: string;
  sections: Record<string, unknown>;
  content_md: string;
  window_start: string;
  window_end: string;
  snapshot_id: string;
  generation_mode: string;
  created_at: string;
}

export interface HistoryItem {
  id: number;
  report_date: string;
  version_no: number;
  is_primary: boolean;
  status: string;
  created_at: string;
}

export interface StatusOut {
  db_ok: boolean;
  mr_schema_version: number;
  schedule_enabled: boolean;
  today: string;
  today_run: {
    id: number;
    status: string;
    error: string | null;
    started_at: string | null;
    finished_at: string | null;
  } | null;
  news_counts: { domestic: number; international: number; ai: number };
}

export const useMorningStatus = () =>
  useQuery({ queryKey: ["morning", "status"], queryFn: () => api<StatusOut>("/morning/status"), refetchInterval: 15000 });

export const useMorningReport = (reportDate?: string, versionNo?: number) =>
  useQuery({
    queryKey: ["morning", "report", reportDate ?? "latest", versionNo ?? 0],
    queryFn: () => {
      const qs = [
        reportDate && `report_date=${reportDate}`,
        versionNo && `version_no=${versionNo}`,
      ].filter(Boolean).join("&");
      return api<Report | null>(`/morning/report${qs ? `?${qs}` : ""}`);
    },
    retry: false,
    refetchInterval: 20000,
  });

export const useMorningHistory = () =>
  useQuery({ queryKey: ["morning", "history"], queryFn: () => api<{ items: HistoryItem[] }>("/morning/history") });

export function useRegenerate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { report_date?: string }) =>
      api<{ run_id: number }>("/morning/regenerate", { method: "POST", json: args }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["morning"] });
    },
  });
}

export function useReassemble() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (version_id: number) => api<{ run_id: number }>("/morning/reassemble", {
      method: "POST", json: { version_id },
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["morning"] }); },
  });
}

export function useRunCollect() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (report_date?: string) =>
      api<{ run_id: number }>(`/morning/runs/collect${report_date ? `?report_date=${report_date}` : ""}`, {
        method: "POST",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["morning"] }),
  });
}

// ---------- 进度面板 ----------

export type StageStatus =
  | "pending" | "running" | "success" | "warning"
  | "failed" | "skipped" | "interrupted";

export interface StageInfo {
  stage: string;
  title: string;
  group: string | null;
  status: StageStatus;
  summary: string;
  reason: string;
  started_at: string | null;
  finished_at: string | null;
  elapsed_ms: number | null;
  attempts: number;
  last_event_at: string | null;
  data: Record<string, unknown> | null;
}

export interface RecentEvent {
  id: number;
  at: string;
  stage: string;
  level: string;
  message: string;
}

export interface ProgressSnapshot {
  run: {
    id: number;
    run_date: string;
    kind: string;
    status: string;
    error: string | null;
    started_at: string | null;
    finished_at: string | null;
  } | null;
  stages: StageInfo[];
  recent: RecentEvent[];
  done_count: number;
  total_count: number;
  server_now: string;
  stall_seconds: number;
  seq: number;
  active?: boolean;
}

export const fetchProgress = (runId: number) =>
  api<ProgressSnapshot>(`/morning/progress?run_id=${runId}`);

export const fetchActiveProgress = (reportDate?: string) =>
  api<ProgressSnapshot>(`/morning/progress/active${reportDate ? `?report_date=${reportDate}` : ""}`);

export const stopRun = (runId: number) =>
  api<{ run_id: number; status: string; note?: string }>(`/morning/runs/${runId}/stop`, {
    method: "POST",
  });

export interface TokenUsageItem {
  node: string;
  input_tokens: number | null;
  output_tokens: number | null;
  cache_hit_tokens?: number | null;
  cache_miss_tokens?: number | null;
}

export const useMorningUsage = (runId: number, active: boolean) =>
  useQuery({
    queryKey: ["morning", "usage", runId],
    queryFn: () => api<{ items: TokenUsageItem[] }>(`/morning/usage?run_id=${runId}`),
    refetchInterval: active ? 5000 : false,
  });

export interface NewsReference {
  id: number;
  title: string;
  source_url: string | null;
  content_hash: string | null;
  category: string;
  is_important: boolean;
}

export const useReportNews = (versionId: number) => useQuery({
  queryKey: ["morning", "report-news", versionId],
  queryFn: () => api<{ items: NewsReference[] }>(`/morning/report/${versionId}/news`),
});

export function useNewsImportance() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, is_important }: { id: number; is_important: boolean }) =>
      api<NewsReference>(`/morning/news/${id}/importance`, { method: "PATCH", json: { is_important } }),
    onSuccess: (updated) => {
      qc.setQueriesData<{ items: NewsReference[] }>({ queryKey: ["morning", "report-news"] }, (old) =>
        old ? { items: old.items.map((item) => item.id === updated.id ||
          (updated.content_hash && item.content_hash === updated.content_hash)
          ? { ...item, is_important: updated.is_important } : item) } : old);
      void qc.invalidateQueries({ queryKey: ["morning", "report-news"] });
      void qc.invalidateQueries({ queryKey: ["morning", "favorites"] });
    },
  });
}

export interface FavoriteNews extends NewsReference {
  summary: string | null;
  note: string;
  is_highlighted: boolean;
}

export const useFavoriteNews = () => useQuery({
  queryKey: ["morning", "favorites"],
  queryFn: () => api<{ items: FavoriteNews[] }>("/morning/favorites"),
  refetchInterval: 20000,
});

export function useUpdateFavoriteNews() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...changes }: { id: number; note?: string; is_highlighted?: boolean }) =>
      api<FavoriteNews>(`/morning/favorites/${id}`, { method: "PATCH", json: changes }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["morning", "favorites"] }); },
  });
}
