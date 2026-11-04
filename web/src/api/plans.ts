import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";

export interface Plan {
  id: number;
  title: string;
  description: string;
  status: string;
  target_date: string | null;
}

export interface DailyTask {
  id: number;
  plan_id: number | null;
  task_date: string;
  title: string;
  done: boolean;
  sort_order: number;
  moved_from_date: string | null;
}

export function usePlans() {
  return useQuery({ queryKey: ["plans"], queryFn: () => api<Plan[]>("/plans") });
}

export function useDailyTasks(date: string) {
  return useQuery({
    queryKey: ["daily-tasks", date],
    queryFn: () => api<DailyTask[]>(`/tasks/daily?date=${date}`),
  });
}

export function useCreatePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; description?: string; target_date?: string | null }) =>
      api<Plan>("/plans", { method: "POST", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plans"] }),
  });
}

export function useUpdatePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Partial<Plan>) =>
      api<Plan>(`/plans/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plans"] }),
  });
}

export function useDeletePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/plans/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plans"] }),
  });
}

export function useCreateTask(date: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; plan_id?: number | null }) =>
      api<DailyTask>("/tasks", { method: "POST", json: { task_date: date, ...body } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["daily-tasks", date] }),
  });
}

export function useUpdateTask(date: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Partial<Pick<DailyTask, "title" | "done" | "plan_id">>) =>
      api<DailyTask>(`/tasks/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["daily-tasks", date] });
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
