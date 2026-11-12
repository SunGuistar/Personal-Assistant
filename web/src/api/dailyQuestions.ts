import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";

export interface DailyQuestion {
  id: number;
  question: string;
  answer: string;
  tags?: string;
  review_count: number;
  review_level: number;
  due_at: string | null;
}
export function useDailyQuestions() {
  return useQuery({ queryKey: ["daily_questions"], queryFn: () => api<DailyQuestion[]>("/daily_questions") });
}
export function useSaveDailyQuestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id?: number; question: string; answer: string; tags?: string }) =>
      api<DailyQuestion>(id === undefined ? "/daily_questions" : `/daily_questions/${id}`, {
        method: id === undefined ? "POST" : "PUT", json: body,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["daily_questions"] }),
  });
}

export function useReviewQuestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({id, remembered}: {id: number; remembered: boolean}) => api<DailyQuestion>(`/daily_questions/${id}/review`, {method: "POST", json: {remembered}}),
    onSuccess: () => qc.invalidateQueries({queryKey: ["daily_questions"]}),
  });
}
export function reviewQueue(items: DailyQuestion[], seen: number[], all = false) {
  const now = Date.now();
  return items.filter(q => !seen.includes(q.id) && (all || !q.due_at || Date.parse(q.due_at) <= now))
    .sort((a,b) => (a.due_at ? Date.parse(a.due_at) : Infinity) - (b.due_at ? Date.parse(b.due_at) : Infinity) || a.id-b.id);
}
