import { useQuery } from "@tanstack/react-query";

import { api } from "../lib/api";

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

/** POST /wechat/chat 并返回 SSE 字节流（EventSource 只支持 GET，故用 fetch 手动解析）。 */
export async function postChat(message: string, sessionId: number | null): Promise<Response> {
  const response = await fetch("/api/wechat/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!response.ok || !response.body) {
    throw new Error(`对话请求失败: HTTP ${response.status}`);
  }
  return response;
}

export async function* readChatEvents(response: Response): AsyncGenerator<ChatEvent> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const line = block.split("\n").find((l) => l.startsWith("data: "));
      if (line) yield JSON.parse(line.slice(6)) as ChatEvent;
    }
  }
}

export function getHistory(sessionId: number): Promise<{ messages: { role: string; content: string }[] }> {
  return api(`/wechat/chat/history?session_id=${sessionId}`);
}
