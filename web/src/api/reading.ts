import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";

export interface Book {
  is_important: boolean;
  id: number;
  title: string;
  author: string;
  note: string;
  status: string;
  note_count: number;
}

export interface BookNote {
  id: number;
  book_id: number;
  filename: string;
  size: number;
  uploaded_at: string;
}

export const BOOK_STATUS_LABELS: Record<string, string> = {
  todo: "待读",
  reading: "正在读",
  done: "已读",
};

export function useBooks(status: string | null = null) {
  return useQuery({
    queryKey: ["books", status],
    queryFn: () => api<Book[]>(status ? `/books?status=${status}` : "/books"),
  });
}

export function useCreateBook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; author?: string; note?: string; status?: string }) =>
      api<Book>("/books", { method: "POST", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["books"] }),
  });
}

export function useUpdateBook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Partial<Book>) =>
      api<Book>(`/books/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["books"] }),
  });
}

export function useDeleteBook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/books/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["books"] }),
  });
}

export function useNotes(bookId: number | null) {
  return useQuery({
    queryKey: ["book-notes", bookId],
    queryFn: () => api<BookNote[]>(`/books/${bookId}/notes`),
    enabled: bookId !== null,
  });
}

export function useUploadNote(bookId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api<BookNote>(`/books/${bookId}/notes`, { method: "POST", body: form });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["book-notes", bookId] });
      qc.invalidateQueries({ queryKey: ["books"] });
    },
  });
}

export function useDeleteNote(bookId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (noteId: number) =>
      api<void>(`/books/${bookId}/notes/${noteId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["book-notes", bookId] });
      qc.invalidateQueries({ queryKey: ["books"] });
    },
  });
}

export const NOTE_EXTENSIONS = [".pdf", ".png", ".jpg", ".jpeg"];

export function isNoteFileAllowed(name: string): boolean {
  const lower = name.toLowerCase();
  return NOTE_EXTENSIONS.some((ext) => lower.endsWith(ext));
}
