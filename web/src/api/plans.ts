import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";

export interface Plan {
  id: number;
  title: string;
  description: string;
  goal: string | null;
  status: string;
  target_date: string | null;
  is_important: boolean;
  sort_order: number;
  completed_at: string | null;
  created_at?: string;
}

export type TaskType = "daily" | "feature_add" | "feature_optimize" | "idea";

/** 任务类型展示名（顺序即排序顺序） */
export const TASK_TYPE_LABELS: Record<TaskType, string> = {
  daily: "日常",
  feature_add: "功能添加",
  feature_optimize: "功能优化",
  idea: "奇思妙想",
};

export const TASK_TYPES = Object.keys(TASK_TYPE_LABELS) as TaskType[];

export interface DailyTask {
  id: number;
  task_date: string;
  title: string;
  content: string | null;
  task_type: TaskType;
  done: boolean;
  sort_order: number;
  is_important: boolean;
  completed_at: string | null;
  moved_from_date: string | null;
}

export function usePlans() {
  return useQuery({ queryKey: ["plans"], queryFn: () => api<Plan[]>("/plans") });
}

export function usePlanHistory(enabled: boolean) {
  return useQuery({
    queryKey: ["plans", "history"],
    queryFn: () => api<Plan[]>("/plans/history"),
    enabled,
  });
}

export function useDailyTasks(date: string) {
  return useQuery({
    queryKey: ["daily-tasks", date],
    queryFn: () => api<DailyTask[]>(`/tasks/daily?date=${date}`),
  });
}

export function useTaskHistory(date: string | null, enabled: boolean) {
  const params = date ? `?date=${date}` : "";
  return useQuery({
    queryKey: ["tasks", "history", date],
    queryFn: () => api<DailyTask[]>(`/tasks/history${params}`),
    enabled,
  });
}

export function useCreatePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; description?: string; goal?: string | null; target_date?: string | null; is_important?: boolean }) =>
      api<Plan>("/plans", { method: "POST", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plans"] }),
  });
}

export function useUpdatePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Partial<Plan>) =>
      api<Plan>(`/plans/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["plans", "history"] });
    },
  });
}

export function useCompletePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<Plan>(`/plans/${id}/complete`, { method: "POST", json: {} }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["plans", "history"] });
    },
  });
}

export function useDeletePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/plans/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["plans", "history"] });
      qc.invalidateQueries({ queryKey: ["daily-tasks"] });
    },
  });
}

export function useReorderPlans() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ordered_ids: number[]) =>
      api<Plan[]>("/plans/reorder", { method: "PUT", json: { ordered_ids } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plans"] }),
  });
}

export function useCreateTask(date: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; content?: string | null; task_type?: TaskType; is_important?: boolean }) =>
      api<DailyTask>("/tasks", { method: "POST", json: { task_date: date, ...body } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["daily-tasks", date] }),
  });
}

export function useUpdateTask(_date: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Partial<Pick<DailyTask, "title" | "content" | "done" | "task_type" | "is_important">>) =>
      api<DailyTask>(`/tasks/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => {
      // 逾期任务会出现在多个日期视图中：失效全部日期列表，避免"保存后标题未变"
      qc.invalidateQueries({ queryKey: ["daily-tasks"] });
      qc.invalidateQueries({ queryKey: ["tasks", "history"] });
      qc.invalidateQueries({ queryKey: ["plans"] });
    },
  });
}

export function useDeleteTask(_date: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/tasks/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["daily-tasks"] });
      qc.invalidateQueries({ queryKey: ["tasks", "history"] });
      qc.invalidateQueries({ queryKey: ["plans"] });
    },
  });
}

export function useTaskToMemo(date: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<{ id: number }>(`/tasks/${id}/to_memo`, { method: "POST", json: {} }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["daily-tasks", date] });
      qc.invalidateQueries({ queryKey: ["daily-tasks"] });
      qc.invalidateQueries({ queryKey: ["memos"] });
      qc.invalidateQueries({ queryKey: ["tasks", "history"] });
    },
  });
}


