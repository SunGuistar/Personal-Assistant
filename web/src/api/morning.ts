import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";

export interface MemoryItem {
  id: number;
  kind: string;
  content: string;
  enabled: boolean;
  confirmed: boolean;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface Evaluation {
  status: string;
  scores: Record<string, number> | null;
  composite: number | null;
  comment: string;
  rule_version: string;
}

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
  fact_check: { ok?: boolean; issues?: string[] } | null;
  generation_mode: string;
  created_at: string;
  evaluation: Evaluation | null;
}

export interface HistoryItem {
  id: number;
  report_date: string;
  version_no: number;
  is_primary: boolean;
  status: string;
  created_at: string;
  has_evaluation: boolean;
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
    queryKey: ["morning", "report", reportDate ?? "today", versionNo ?? 0],
    queryFn: () => {
      const qs = [
        reportDate && `report_date=${reportDate}`,
        versionNo && `version_no=${versionNo}`,
      ].filter(Boolean).join("&");
      return api<Report>(`/morning/report${qs ? `?${qs}` : ""}`);
    },
    retry: false,
    refetchInterval: 20000,
  });

export const useMorningHistory = () =>
  useQuery({ queryKey: ["morning", "history"], queryFn: () => api<{ items: HistoryItem[] }>("/morning/history") });

export const useMorningMemories = () =>
  useQuery({ queryKey: ["morning", "memory"], queryFn: () => api<MemoryItem[]>("/morning/memory") });

export function useCreateMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { kind: string; content: string; source?: string }) =>
      api<MemoryItem>("/morning/memory", { method: "POST", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["morning", "memory"] }),
  });
}

export function usePatchMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: number; enabled?: boolean; content?: string }) =>
      api<MemoryItem>(`/morning/memory/${args.id}`, {
        method: "PATCH",
        json: { enabled: args.enabled, content: args.content },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["morning", "memory"] }),
  });
}

export function useDeleteMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/morning/memory/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["morning", "memory"] }),
  });
}

export function useRegenerate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { mode: "reuse" | "full"; report_date?: string }) =>
      api<{ run_id: number }>("/morning/regenerate", { method: "POST", json: args }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["morning"] });
    },
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

/** 助手 SSE 对话：返回逐 token 回调；结束回调携带 proposals（Memory 提议需用户确认）。 */
export async function assistantChat(
  message: string,
  history: { role: string; content: string }[],
  onDelta: (delta: string) => void,
): Promise<{ content: string; proposals: { kind: string; content: string }[] }> {
  const resp = await fetch("/api/morning/assistant/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
  });
  if (!resp.ok || !resp.body) throw new Error("助手请求失败");
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let final: { content: string; proposals: { kind: string; content: string }[] } = {
    content: "",
    proposals: [],
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const evt of events) {
      const line = evt.trim();
      if (!line.startsWith("data:")) continue;
      try {
        const data = JSON.parse(line.slice(5));
        if (data.delta) onDelta(data.delta);
        if (data.done) final = { content: data.content ?? "", proposals: data.proposals ?? [] };
      } catch {
        // 忽略不完整帧
      }
    }
  }
  return final;
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
