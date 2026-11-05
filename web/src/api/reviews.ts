import { useQuery } from "@tanstack/react-query";

import { api } from "../lib/api";
import { postSse, readSseEvents } from "../lib/sse";

export interface BasisItem {
  source_type: string;
  source_id: number;
  reason: string;
  fact: string;
}

export interface Suggestion {
  id: number;
  review_id: number;
  seq: number;
  content: string;
  basis: BasisItem[];
  is_general: boolean;
  status: "pending" | "accepted" | "modified" | "rejected";
  final_content: string | null;
  reject_reason: string;
  resolved_at: string | null;
}

export interface ReviewMessage {
  id: number;
  role: string;
  content: string;
  created_at: string;
}

export interface ReviewDetail {
  id: number;
  week_start: string;
  week_end: string;
  status: "draft" | "confirmed";
  stats: {
    week_start: string;
    week_end: string;
    tasks: {
      belonging: { total: number; done: number };
      done_in_week: { total: number; carried_in_done: { total: number } };
      created_in_week: number;
      overdue_at_week_end: { total: number };
    };
    plans: { active: { total: number }; completed_in_week: unknown[] };
    memos: { total: number; stale: number };
    reading: { reading: unknown[]; notes_added_in_week: number };
  };
  analysis_md: string;
  user_notes: string;
  has_report: boolean;
  confirmed_at: string | null;
  suggestions?: Suggestion[];
  pending_suggestions?: number;
}

export function createOrGetReview(weekStart: string | null): Promise<ReviewDetail> {
  return api("/reviews", { method: "POST", json: { week_start: weekStart } });
}

export function listReviews(): Promise<ReviewDetail[]> {
  return api("/reviews");
}

export function getReview(id: number): Promise<ReviewDetail> {
  return api(`/reviews/${id}`);
}

export function getReviewMessages(id: number): Promise<{ messages: ReviewMessage[] }> {
  return api(`/reviews/${id}/messages`);
}

export function getReviewReport(id: number): Promise<{ status: string; report_md: string | null }> {
  return api(`/reviews/${id}/report`);
}

export function updateDraft(
  id: number,
  body: { analysis_md?: string; user_notes?: string }
): Promise<ReviewDetail> {
  return api(`/reviews/${id}`, { method: "PUT", json: body });
}

export function resolveSuggestion(
  id: number,
  body: { action: string; final_content?: string; reject_reason?: string }
): Promise<Suggestion> {
  return api(`/reviews/suggestions/${id}`, { method: "PUT", json: body });
}

export function confirmReview(
  id: number,
  body: { analysis_md?: string; user_notes?: string }
): Promise<ReviewDetail> {
  return api(`/reviews/${id}/confirm`, { method: "POST", json: body });
}

export function postReviewChat(id: number, message: string): Promise<Response> {
  return postSse(`/reviews/${id}/chat`, { message });
}

export function postSuggestGenerate(id: number): Promise<Response> {
  return postSse(`/reviews/${id}/suggestions/generate`);
}

export { readSseEvents };

/** 历史周报列表（进入页面时加载一次）。 */
export function useReviews() {
  return useQuery({
    queryKey: ["reviews"],
    queryFn: listReviews,
    retry: 1,
  });
}
