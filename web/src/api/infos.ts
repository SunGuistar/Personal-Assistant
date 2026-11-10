import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";

/** 重要信息（右侧栏上部，SQLite 多条长期保存）。 */
export interface ImportantInfo {
  id: number;
  title: string;
  content: string;
  sort_order: number;
}

export function useInfos() {
  return useQuery({ queryKey: ["infos"], queryFn: () => api<ImportantInfo[]>("/infos") });
}

export function useCreateInfo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; content?: string }) =>
      api<ImportantInfo>("/infos", { method: "POST", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["infos"] }),
  });
}

export function useUpdateInfo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Partial<Pick<ImportantInfo, "title" | "content">>) =>
      api<ImportantInfo>(`/infos/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["infos"] }),
  });
}

export function useDeleteInfo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/infos/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["infos"] }),
  });
}

export function useReorderInfos() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ordered_ids: number[]) =>
      api<ImportantInfo[]>("/infos/reorder", { method: "PUT", json: { ordered_ids } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["infos"] }),
  });
}

/** 随手备忘（SQLite 多条记录，与重要信息概念独立）。 */
export interface Memo {
  id: number;
  title: string;
  content: string;
  /** 任务类型（与每日任务同一套；空=存量未保存，展示/转换时按 daily 回退）。 */
  task_type?: string;
  sort_order: number;
}

export function useMemos() {
  return useQuery({ queryKey: ["memos"], queryFn: () => api<Memo[]>("/memos") });
}

export function useCreateMemo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; content?: string; task_type?: string }) =>
      api<Memo>("/memos", { method: "POST", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memos"] }),
  });
}

export function useUpdateMemo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Partial<Pick<Memo, "title" | "content" | "task_type">>) =>
      api<Memo>(`/memos/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memos"] }),
  });
}

export function useDeleteMemo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/memos/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memos"] }),
  });
}

export function useReorderMemos() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ordered_ids: number[]) =>
      api<Memo[]>("/memos/reorder", { method: "PUT", json: { ordered_ids } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memos"] }),
  });
}

/** 随手备忘 → 每日任务（移动语义，一键转换：默认今天，恢复备忘保存的计划类型）。 */
export function useMemoToTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id }: { id: number }) =>
      api<unknown>(`/memos/${id}/to_task`, { method: "POST", json: {} }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memos"] });
      qc.invalidateQueries({ queryKey: ["daily-tasks"] });
    },
  });
}
