import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";

export interface NewsItem {
  id: number;
  title: string;
  url: string;
  source: string;
  source_id: number | null;
  topic: string;
  published_at: string;
  raw_summary: string;
  norm_heat: number;
  score: number;
  is_favorite: boolean;
  is_read: boolean;
  fetched_at: string;
  created_at: string;
  updated_at: string;
}

export interface NewsSource {
  id: number;
  name: string;
  kind: string;
  endpoint: string;
  enabled: boolean;
  weight: number;
  created_at: string;
  updated_at: string;
}

export interface NewsItemList {
  items: NewsItem[];
  total: number;
  page: number;
  page_size: number;
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

export interface NewsQueryParams {
  page?: number;
  page_size?: number;
  topic?: string;
  source?: string;
  sort?: "latest" | "top";
  since?: string;
  until?: string;
  favorite?: boolean;
  unread?: boolean;
}

function buildQuery(params: NewsQueryParams): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function useNewsItems(params: NewsQueryParams) {
  return useQuery({
    queryKey: ["news-items", params],
    queryFn: () => api<NewsItemList>(`/news/items${buildQuery(params)}`),
    placeholderData: (previous) => previous,
  });
}

export function useNewsSources() {
  return useQuery({
    queryKey: ["news-sources"],
    queryFn: () => api<NewsSource[]>("/news/sources"),
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
      qc.invalidateQueries({ queryKey: ["news-items"] });
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

export function useUpdateNewsItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; is_favorite?: boolean; is_read?: boolean }) =>
      api<NewsItem>(`/news/items/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["news-items"] });
    },
  });
}
