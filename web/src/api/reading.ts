import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";

export interface Book {
  is_important: boolean;
  id: number;
  title: string;
  title_cn: string; // 标题中文翻译（可空）
  book_type: string; // book/article/video/essay
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
  todo: "未读",
  reading: "正在读",
  done: "已读",
};

/** 阅读类型（新增/编辑可选）。 */
export const BOOK_TYPE_LABELS: Record<string, string> = {
  book: "书籍",
  article: "文章",
  video: "视频",
  essay: "随笔",
};

export const BOOK_TYPES = Object.keys(BOOK_TYPE_LABELS);

/** 类型徽标配色：书籍=天蓝、文章=紫、视频=玫红、随笔=琥珀（与状态徽标错开）。 */
export const BOOK_TYPE_BADGE_CLASS: Record<string, string> = {
  book: "bg-sky-50 text-sky-700",
  article: "bg-violet-50 text-violet-700",
  video: "bg-rose-50 text-rose-600",
  essay: "bg-amber-50 text-amber-700",
};

/** 状态徽标配色：正在读=蓝、未读=中性灰、已读=绿（与页面中性风格协调，三色易区分）。 */
export const BOOK_STATUS_BADGE_CLASS: Record<string, string> = {
  reading: "bg-blue-50 text-blue-600",
  todo: "bg-neutral-100 text-neutral-500",
  done: "bg-green-50 text-green-600",
};

export function useBooks(status: string | null = null, bookType: string | null = null) {
  return useQuery({
    queryKey: ["books", status, bookType],
    queryFn: () => {
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (bookType) params.set("book_type", bookType);
      const qs = params.toString();
      return api<Book[]>(qs ? `/books?${qs}` : "/books");
    },
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

export function useCreateMdNote(bookId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { filename: string; content: string }) =>
      api<BookNote>(`/books/${bookId}/notes/md`, { method: "POST", json: body }),
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

export const NOTE_EXTENSIONS = [".pdf", ".png", ".jpg", ".jpeg", ".md", ".jnotes"];

export function isNoteFileAllowed(name: string): boolean {
  const lower = name.toLowerCase();
  return NOTE_EXTENSIONS.some((ext) => lower.endsWith(ext));
}
