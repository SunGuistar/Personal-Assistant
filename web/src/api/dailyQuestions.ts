import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";

export interface DailyQuestion {
  id: number;
  question: string;
  answer: string;
}
export function useDailyQuestions() {
  return useQuery({ queryKey: ["daily_questions"], queryFn: () => api<DailyQuestion[]>("/daily_questions") });
}
export function useSaveDailyQuestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id?: number; question: string; answer: string }) =>
      api<DailyQuestion>(id === undefined ? "/daily_questions" : `/daily_questions/${id}`, {
        method: id === undefined ? "POST" : "PUT", json: body,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["daily_questions"] }),
  });
}
