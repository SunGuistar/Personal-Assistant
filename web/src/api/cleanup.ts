import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";

export interface KeepReason {
  chunk_id: string;
  reason: string;
}

export interface Candidate {
  id: number;
  review_id: number;
  chat_id: string;
  chat_name: string;
  msg_date: string;
  snapshot_count: number;
  normalized_count: number;
  chunk_delete_count: number;
  chunk_keep_count: number;
  keep_reasons: KeepReason[];
  size_estimate: number;
  state: string;
  error: string;
}

export interface Review {
  id: number;
  week_id: string;
  status: string;
  confirmed_at: string | null;
  reviewed_at: string | null;
  candidates: Candidate[];
}

export interface CleanupStatus {
  banner: { review_id: number; week_id: string; status: string; candidate_groups: number } | null;
  reviews: Review[];
}

export function useCleanupStatus() {
  return useQuery({ queryKey: ["cleanup-status"], queryFn: () => api<CleanupStatus>("/cleanup/status") });
}

export function useCleanupReview(reviewId: number | null) {
  return useQuery({
    queryKey: ["cleanup-review", reviewId],
    queryFn: () => api<Review>(`/cleanup/reviews/${reviewId}`),
    enabled: reviewId !== null,
  });
}

export function useDismissReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reviewId: number) =>
      api<Review>(`/cleanup/reviews/${reviewId}/dismiss`, { method: "POST", json: {} }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cleanup-status"] }),
  });
}

export function useSkipReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reviewId: number) =>
      api<Review>(`/cleanup/reviews/${reviewId}/skip`, { method: "POST", json: {} }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cleanup-status"] });
      qc.invalidateQueries({ queryKey: ["cleanup-review"] });
    },
  });
}

export function useConfirmReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ reviewId, candidateIds }: { reviewId: number; candidateIds: number[] }) =>
      api<Review>(`/cleanup/reviews/${reviewId}/confirm`, { method: "POST", json: { candidate_ids: candidateIds } }),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["cleanup-review", v.reviewId] });
      qc.invalidateQueries({ queryKey: ["cleanup-status"] });
    },
  });
}

export function useExecuteCleanup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reviewId: number) =>
      api<{ task_id: number; status: string }>("/cleanup/execute", { method: "POST", json: { review_id: reviewId } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cleanup-review"] }),
  });
}

export function useRetryCandidates() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ reviewId, candidateIds }: { reviewId: number; candidateIds: number[] }) =>
      api<Review>("/cleanup/retry", { method: "POST", json: { review_id: reviewId, candidate_ids: candidateIds } }),
    onSuccess: (_d, v) => qc.invalidateQueries({ queryKey: ["cleanup-review", v.reviewId] }),
  });
}

export function useCleanupJob(taskId: number | null) {
  return useQuery({
    queryKey: ["cleanup-job", taskId],
    queryFn: () => api<{ id: number; kind: string; status: string; progress: number; result: { deleted_groups?: number; failed_groups?: number } | null; error: string | null }>(`/jobs/${taskId}`),
    enabled: taskId !== null,
    refetchInterval: (query) =>
      query.state.data && ["success", "failed"].includes(query.state.data.status) ? false : 1000,
  });
}
