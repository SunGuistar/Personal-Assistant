import { useEffect, useRef, useState } from "react";
import { BookOpen, FileText, Pencil, Plus, Trash2, Upload } from "lucide-react";

import { ApiError } from "../lib/api";
import { Button } from "../components/ui/button";
import { StarButton, importantRowClass } from "../components/StarButton";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { Input, Label, Select, Textarea } from "../components/ui/input";
import {
  Book,
  BOOK_STATUS_LABELS,
  isNoteFileAllowed,
  useBooks,
  useCreateBook,
  useDeleteBook,
  useDeleteNote,
  useNotes,
  useUpdateBook,
  useUploadNote,
} from "../api/reading";

const FILTERS: Array<{ value: string | null; label: string }> = [
  { value: null, label: "全部" },
  { value: "todo", label: "待读" },
  { value: "reading", label: "正在读" },
  { value: "done", label: "已读" },
];

export function ReadingPage() {
  const [filter, setFilter] = useState<string | null>(null);
  const { data: books = [], isLoading } = useBooks(filter);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Book | null>(null);
  const [notesBook, setNotesBook] = useState<Book | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const showMessage = (text: string) => {
    setMessage(text);
    window.setTimeout(() => setMessage(null), 4000);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">阅读管理</h1>
        <Button
          size="sm"
          className="ml-auto"
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
        >
          <Plus className="h-4 w-4" /> 添加书籍
        </Button>
      </div>

      <div className="flex gap-1">
        {FILTERS.map((item) => (
          <Button
            key={item.label}
            size="sm"
            variant={filter === item.value ? "default" : "outline"}
            onClick={() => setFilter(item.value)}
          >
            {item.label}
          </Button>
        ))}
      </div>

      {message && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {message}
        </div>
      )}

      {isLoading ? (
        <div className="py-8 text-center text-sm text-neutral-400">加载中…</div>
      ) : books.length === 0 ? (
        <div className="py-8 text-center text-sm text-neutral-400">还没有书籍，点击右上角添加</div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {books.map((book) => (
            <BookCard
              key={book.id}
              book={book}
              onEdit={() => {
                setEditing(book);
                setFormOpen(true);
              }}
              onManageNotes={() => setNotesBook(book)}
              onBlocked={(text) => showMessage(text)}
            />
          ))}
        </div>
      )}

      <BookFormDialog open={formOpen} onOpenChange={setFormOpen} book={editing} />
      <NotesDialog book={notesBook} onClose={() => setNotesBook(null)} />
    </div>
  );
}

function BookCard({
  book,
  onEdit,
  onManageNotes,
  onBlocked,
}: {
  book: Book;
  onEdit: () => void;
  onManageNotes: () => void;
  onBlocked: (message: string) => void;
}) {
  const deleteBook = useDeleteBook();
  const updateBook = useUpdateBook();

  const attemptDelete = () => {
    // 前端预检：有笔记直接提示（与后端 409 规则一致的文案）
    if (book.note_count > 0) {
      onBlocked("该书籍存在关联笔记，请先删除全部笔记后再删除书籍。");
      return;
    }
    if (!confirm(`确定删除书籍「${book.title}」？`)) return;
    deleteBook.mutate(book.id, {
      onError: (error) => {
        if (error instanceof ApiError && error.code === "book_has_notes") {
          onBlocked(error.message);
        } else {
          onBlocked(error.message || "删除失败");
        }
      },
    });
  };

  return (
    <div className={`rounded-lg border border-neutral-200 bg-white p-4 ${importantRowClass(book.is_important)}`}>
      <div className="flex items-start gap-2">
        <StarButton
          important={book.is_important}
          onToggle={() => updateBook.mutate({ id: book.id, is_important: !book.is_important })}
        />
        <BookOpen className="mt-1.5 h-4 w-4 shrink-0 text-neutral-400" />
        <div className="min-w-0 flex-1">
          <div className={`truncate text-sm font-medium ${book.is_important ? "text-red-700" : ""}`}>{book.title}</div>
          <div className="truncate text-xs text-neutral-500">{book.author || "未知作者"}</div>
        </div>
        <span className="shrink-0 rounded bg-neutral-100 px-1.5 py-0.5 text-xs text-neutral-600">
          {BOOK_STATUS_LABELS[book.status] ?? book.status}
        </span>
      </div>
      {book.note && <p className="mt-2 line-clamp-2 text-xs text-neutral-500">{book.note}</p>}
      <div className="mt-3 flex items-center gap-1 text-xs text-neutral-500">
        <FileText className="h-3.5 w-3.5" /> 笔记 {book.note_count} 份
        <span className="ml-auto flex gap-1">
          <Button size="sm" variant="ghost" onClick={onManageNotes}>
            笔记
          </Button>
          <Button size="sm" variant="ghost" onClick={onEdit}>
            <Pencil className="h-3.5 w-3.5" />
          </Button>
          <Button size="sm" variant="ghost" onClick={attemptDelete} aria-label="删除书籍">
            <Trash2 className="h-3.5 w-3.5 text-red-500" />
          </Button>
        </span>
      </div>
    </div>
  );
}

function BookFormDialog({
  open,
  onOpenChange,
  book,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  book: Book | null;
}) {
  const createBook = useCreateBook();
  const updateBook = useUpdateBook();
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [note, setNote] = useState("");
  const [status, setStatus] = useState("todo");

  useEffect(() => {
    if (open) {
      setTitle(book?.title ?? "");
      setAuthor(book?.author ?? "");
      setNote(book?.note ?? "");
      setStatus(book?.status ?? "todo");
    }
  }, [open, book]);

  const submit = () => {
    if (!title.trim()) return;
    const body = { title: title.trim(), author, note, status };
    const mutation = book ? updateBook : createBook;
    const payload = book ? { id: book.id, ...body } : body;
    mutation.mutate(payload as never, { onSuccess: () => onOpenChange(false) });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{book ? "编辑书籍" : "添加书籍"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>书名</Label>
            <Input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>作者</Label>
              <Input value={author} onChange={(e) => setAuthor(e.target.value)} />
            </div>
            <div>
              <Label>状态</Label>
              <Select value={status} onChange={(e) => setStatus(e.target.value)}>
                {Object.entries(BOOK_STATUS_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <div>
            <Label>备注</Label>
            <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={submit} disabled={!title.trim()}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function NotesDialog({ book, onClose }: { book: Book | null; onClose: () => void }) {
  const { data: notes = [] } = useNotes(book?.id ?? null);
  const uploadNote = useUploadNote(book?.id ?? 0);
  const deleteNote = useDeleteNote(book?.id ?? 0);
  const fileInput = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<{ id: number; filename: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pickFile = () => fileInput.current?.click();

  const onFileChosen = (file: File | undefined) => {
    setError(null);
    if (!file || !book) return;
    if (!isNoteFileAllowed(file.name)) {
      setError("仅支持 PDF / PNG / JPG 格式的笔记文件");
      return;
    }
    uploadNote.mutate(file, {
      onError: (e) => setError(e instanceof ApiError ? e.message : "上传失败"),
    });
  };

  return (
    <Dialog open={book !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>「{book?.title}」的笔记</DialogTitle>
        </DialogHeader>
        {error && (
          <div className="mb-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}
        <input
          ref={fileInput}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg"
          className="hidden"
          data-testid="note-file-input"
          onChange={(e) => {
            onFileChosen(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        {notes.length === 0 ? (
          <div className="py-4 text-center text-sm text-neutral-400">
            还没有笔记。在云记中导出 PDF/PNG 后在此上传。
          </div>
        ) : (
          <ul className="space-y-1">
            {notes.map((note) => (
              <li key={note.id} className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-neutral-50">
                <FileText className="h-4 w-4 shrink-0 text-neutral-400" />
                <button
                  className="flex-1 truncate text-left text-sm text-neutral-700 hover:underline"
                  onClick={() => setPreview({ id: note.id, filename: note.filename })}
                >
                  {note.filename}
                </button>
                <span className="text-xs text-neutral-400">{(note.size / 1024).toFixed(0)} KB</span>
                <button
                  aria-label="删除笔记"
                  className="p-1 text-neutral-400 hover:text-red-600"
                  onClick={() =>
                    confirm(`删除笔记「${note.filename}」？该操作同时删除文件，且不可恢复。`) &&
                    deleteNote.mutate(note.id)
                  }
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={pickFile} disabled={uploadNote.isPending}>
            <Upload className="h-4 w-4" /> {uploadNote.isPending ? "上传中…" : "上传笔记"}
          </Button>
        </DialogFooter>
      </DialogContent>

      <PreviewDialog preview={preview} onClose={() => setPreview(null)} />
    </Dialog>
  );
}

function PreviewDialog({
  preview,
  onClose,
}: {
  preview: { id: number; filename: string } | null;
  onClose: () => void;
}) {
  const isImage = preview ? /\.(png|jpe?g)$/i.test(preview.filename) : false;
  const src = preview ? `/api/notes/${preview.id}/file` : "";
  return (
    <Dialog open={preview !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{preview?.filename}</DialogTitle>
        </DialogHeader>
        {preview && (
          <div className="max-h-[70vh] overflow-auto">
            {isImage ? (
              <img src={src} alt={preview.filename} className="mx-auto max-w-full" />
            ) : (
              <iframe src={src} title={preview.filename} className="h-[65vh] w-full border-0" />
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
