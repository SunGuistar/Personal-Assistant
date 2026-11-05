import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";

export interface NewsTopItem {
  id: number;
  title: string;
  url: string;
  source: string;
  topic: string;
  published_at: string;
  raw_summary: string;
  title_zh: string;
  summary_zh: string;
  translate_status: string;
  score: number;
  effective_score: number;
  rank: number;
}

export interface NewsTop {
  items: NewsTopItem[];
  total: number;
  generated_at: string;
}

export interface NewsStatus {
  last_refresh: {
    refreshed_at: string;
    new_items: number;
    sources: number;
    failures: { source: string; error: string }[];
  } | null;
  refresh_minutes: number;
  stale: boolean;
}

export interface JobStatus {
  id: number;
  kind: string;
  status: string;
  progress: number;
  result: Record<string, unknown> | null;
  error: string | null;
}

export function useNewsTop() {
  return useQuery({
    queryKey: ["news-top"],
    queryFn: () => api<NewsTop>("/news/top"),
    placeholderData: (previous) => previous,
  });
}

export function useNewsStatus() {
  return useQuery({
    queryKey: ["news-status"],
    queryFn: () => api<NewsStatus>("/news/status"),
  });
}

export function useRefreshNews() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ task_id: number; status: string }>("/news/refresh", { method: "POST", json: {} }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["news-top"] });
      qc.invalidateQueries({ queryKey: ["news-status"] });
    },
  });
}

export function useNewsJob(taskId: number | null) {
  return useQuery({
    queryKey: ["news-job", taskId],
    queryFn: () => api<JobStatus>(`/jobs/${taskId}`),
    enabled: taskId !== null,
    refetchInterval: (query) =>
      query.state.data && ["success", "failed"].includes(query.state.data.status) ? false : 1000,
  });
}
