import { useQuery } from "@tanstack/react-query";

import { api } from "../lib/api";
import { postSse, readSseEvents, SseEvent } from "../lib/sse";

export type { SseEvent };
export { postSse, readSseEvents };

export interface SourceStatus {
  running: boolean;
  base_url?: string;
  accounts?: unknown[];
  message?: string;
}

export interface DataRange {
  chat_id: string;
  display_name: string;
  message_count: number;
  min_date: string | null;
  max_date: string | null;
}

export interface Report {
  seq: number;
  chat_name: string;
  date: string;
  filename: string;
  created_at: number;
  size: number;
}

export interface JobStatus {
  id: number;
  kind: string;
  status: string;
  progress: number;
  result: Record<string, unknown> | null;
  error: string | null;
}

export function useSourceStatus(enabled = true) {
  return useQuery({
    queryKey: ["wechat-source-status"],
    queryFn: () => api<SourceStatus>("/wechat/source/status"),
    refetchInterval: 30_000,
    enabled,
    retry: 1,
  });
}

export function useDataRange() {
  return useQuery({
    queryKey: ["wechat-data-range"],
    queryFn: () => api<DataRange[]>("/wechat/data-range"),
    retry: 1,
  });
}

export function useReports(enabled: boolean) {
  return useQuery({
    queryKey: ["wechat-reports"],
    queryFn: () => api<Report[]>("/wechat/reports"),
    enabled,
  });
}

export function startSync(body: {
  chat_id?: string | null;
  display_name?: string;
  start?: string | null;
  end?: string | null;
}): Promise<{ task_id: number; status: string }> {
  return api("/wechat/sync", { method: "POST", json: body });
}

export function useJob(taskId: number | null) {
  return useQuery({
    queryKey: ["job", taskId],
    queryFn: () => api<JobStatus>(`/jobs/${taskId}`),
    enabled: taskId !== null,
    refetchInterval: (query) =>
      query.state.data?.status === "running" || query.state.data?.status === "pending"
        ? 1000
        : false,
  });
}

export interface ChatEvent {
  type: "token" | "summary_job" | "done" | "error";
  text?: string;
  task_id?: number;
  session_id?: number;
  message?: string;
}

/** POST /wechat/chat 并返回 SSE 字节流（复用 lib/sse）。 */
export async function postChat(message: string, sessionId: number | null): Promise<Response> {
  return postSse("/wechat/chat", { session_id: sessionId, message });
}

export async function* readChatEvents(response: Response): AsyncGenerator<ChatEvent> {
  for await (const event of readSseEvents(response)) {
    yield event as ChatEvent;
  }
}

export function getHistory(sessionId: number): Promise<{ messages: { role: string; content: string }[] }> {
  return api(`/wechat/chat/history?session_id=${sessionId}`);
}
