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

/** 随手备忘（右侧栏下部，单份 Markdown 文件，自动保存）。 */
export function useMemo() {
  return useQuery({ queryKey: ["memo"], queryFn: () => api<{ content: string }>("/memo") });
}

export function useSaveMemo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { content: string; expected?: string | null }) =>
      api<{ content: string }>("/memo", { method: "PUT", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memo"] }),
  });
}
