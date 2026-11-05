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

export interface DailyTask {
  id: number;
  task_date: string;
  title: string;
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
    mutationFn: (body: { title: string; is_important?: boolean }) =>
      api<DailyTask>("/tasks", { method: "POST", json: { task_date: date, ...body } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["daily-tasks", date] }),
  });
}

export function useUpdateTask(date: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Partial<Pick<DailyTask, "title" | "done" | "is_important">>) =>
      api<DailyTask>(`/tasks/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["daily-tasks", date] });
      qc.invalidateQueries({ queryKey: ["tasks", "history"] });
      qc.invalidateQueries({ queryKey: ["plans"] });
    },
  });
}

export function useDeleteTask(date: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/tasks/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["daily-tasks", date] });
      qc.invalidateQueries({ queryKey: ["tasks", "history"] });
      qc.invalidateQueries({ queryKey: ["plans"] });
    },
  });
}

export function useMoveTask(fromDate: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, target_date }: { id: number; target_date: string }) =>
      api<DailyTask>(`/tasks/${id}/move`, { method: "POST", json: { target_date } }),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["daily-tasks", fromDate] });
      qc.invalidateQueries({ queryKey: ["daily-tasks", variables.target_date] });
    },
  });
}

export function useReorderTasks(date: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ordered_ids: number[]) =>
      api<DailyTask[]>("/tasks/reorder", { method: "PUT", json: { date, ordered_ids } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["daily-tasks", date] }),
  });
}
