import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";

export interface Experience {
  id: number;
  title: string;
  problem: string;
  solution: string;
  tags: string;
  created_at: string;
  updated_at: string;
}
export type ExperienceInput = Pick<Experience, "title" | "problem" | "solution" | "tags">;

export function useExperiences() {
  return useQuery({ queryKey: ["experiences"], queryFn: () => api<Experience[]>("/experiences") });
}

export function useSaveExperience() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: ExperienceInput & { id?: number }) => api<Experience>(
      id === undefined ? "/experiences" : `/experiences/${id}`, { method: id === undefined ? "POST" : "PUT", json: body }),
    onSuccess: saved => {
      qc.setQueryData<Experience[]>(["experiences"], previous => [saved, ...(previous ?? []).filter(item => item.id !== saved.id)]);
      void qc.invalidateQueries({ queryKey: ["experiences"] });
    },
  });
}
