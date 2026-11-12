import { useEffect, useRef, useState } from "react";
import { BookOpen, Download, ExternalLink, FileText, LayoutGrid, LayoutList, Pencil, PenLine, Plus, Trash2, Upload } from "lucide-react";

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
  BOOK_STATUS_BADGE_CLASS,
  BOOK_STATUS_LABELS,
  BOOK_TYPE_BADGE_CLASS,
  BOOK_TYPE_LABELS,
  BOOK_TYPES,
  isNoteFileAllowed,
  useBooks,
  useCreateBook,
  useCreateMdNote,
  useDeleteBook,
  useDeleteNote,
  useNotes,
  useUpdateBook,
  useUploadNote,
} from "../api/reading";

const FILTERS: Array<{ value: string | null; label: string }> = [
  { value: null, label: "全部" },
  { value: "todo", label: "未读" },
  { value: "reading", label: "正在读" },
  { value: "done", label: "已读" },
];

type ViewMode = "list" | "card";

const VIEW_KEY = "hub.reading.view";

function statusBadgeClass(status: string): string {
  return BOOK_STATUS_BADGE_CLASS[status] ?? "bg-neutral-100 text-neutral-500";
}

function typeBadgeClass(bookType: string): string {
  return BOOK_TYPE_BADGE_CLASS[bookType] ?? "bg-neutral-100 text-neutral-500";
}

export function ReadingPage() {
  const [filter, setFilter] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const { data: books = [], isLoading } = useBooks(filter, typeFilter);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Book | null>(null);
  const [notesBook, setNotesBook] = useState<Book | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  // 展示模式：默认列表，切换存 localStorage，不影响阅读数据
  const [view, setView] = useState<ViewMode>(() =>
    localStorage.getItem(VIEW_KEY) === "card" ? "card" : "list"
  );

  const switchView = (next: ViewMode) => {
    setView(next);
    localStorage.setItem(VIEW_KEY, next);
  };

  const showMessage = (text: string) => {
    setMessage(text);
    window.setTimeout(() => setMessage(null), 4000);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">阅读管理</h1>
        <div className="ml-auto flex items-center gap-2">
          <div className="flex gap-1">
            <Button
              size="sm"
              variant={view === "list" ? "default" : "outline"}
              onClick={() => switchView("list")}
              aria-label="列表展示"
              title="列表展示"
            >
              <LayoutList className="h-4 w-4" />
            </Button>
            <Button
              size="sm"
              variant={view === "card" ? "default" : "outline"}
              onClick={() => switchView("card")}
              aria-label="卡片展示"
              title="卡片展示"
            >
              <LayoutGrid className="h-4 w-4" />
            </Button>
          </div>
          <Button
            size="sm"
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            <Plus className="h-4 w-4" /> 添加书籍
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
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
        <span className="h-4 w-px bg-neutral-200" aria-hidden />
        {/* 类型筛选：展示并快速过滤 书籍/文章/视频/随笔 */}
        <div className="flex gap-1">
          <Button
            size="sm"
            variant={typeFilter === null ? "default" : "outline"}
            onClick={() => setTypeFilter(null)}
          >
            全部类型
          </Button>
          {BOOK_TYPES.map((t) => (
            <Button
              key={t}
              size="sm"
              variant={typeFilter === t ? "default" : "outline"}
              onClick={() => setTypeFilter(t)}
            >
              {BOOK_TYPE_LABELS[t]}
            </Button>
          ))}
        </div>
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
      ) : view === "list" ? (
        <ul className="space-y-1">
          {books.map((book) => (
            <BookRow
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
        </ul>
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

/** 书名区块：较大字体的原标题 + 行内类型徽标 + 可选中文翻译（无翻译时不占位）。 */
function BookTitle({ book, className = "" }: { book: Book; className?: string }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1.5">
        <span className={`truncate text-base font-semibold ${book.is_important ? "text-red-700" : ""} ${className}`}>
          {book.title}
        </span>
        <span className={`shrink-0 rounded px-1.5 py-0.5 text-[11px] ${typeBadgeClass(book.book_type)}`}>
          {BOOK_TYPE_LABELS[book.book_type] ?? book.book_type}
        </span>
      </div>
      {book.title_cn && <div className="truncate text-xs text-neutral-500">译：{book.title_cn}</div>}
      {book.author && <div className="truncate text-xs text-neutral-500">{book.author}</div>}
    </div>
  );
}

function BookActions({
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
    <span className="flex shrink-0 items-center gap-1">
      {/* 链接只给跳转入口，具体内容（URL 文本）不在展示栏渲染；仅放行 http/https */}
      {/^https?:\/\//i.test(book.url) && (
        <a
          href={book.url}
          target="_blank"
          rel="noreferrer noopener"
          aria-label="打开链接"
          title="打开链接"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-neutral-500 hover:bg-neutral-100"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      )}
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
  );
}

function BookRow({
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
  const updateBook = useUpdateBook();
  return (
    <li
      className={`flex items-center gap-2 rounded-md border border-neutral-200 bg-white px-3 py-2 ${importantRowClass(book.is_important)}`}
    >
      <StarButton
        important={book.is_important}
        onToggle={() => updateBook.mutate({ id: book.id, is_important: !book.is_important })}
      />
      <BookOpen className="h-4 w-4 shrink-0 text-neutral-400" />
      <div className="min-w-0 flex-1">
        <BookTitle book={book} />
        {book.note && <div className="truncate text-xs text-neutral-500">备注：{book.note}</div>}
      </div>
      <span className={`shrink-0 rounded px-1.5 py-0.5 text-xs ${statusBadgeClass(book.status)}`}>
        {BOOK_STATUS_LABELS[book.status] ?? book.status}
      </span>
      <span className="hidden shrink-0 text-xs text-neutral-400 md:inline">笔记 {book.note_count}</span>
      <BookActions book={book} onEdit={onEdit} onManageNotes={onManageNotes} onBlocked={onBlocked} />
    </li>
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
  const updateBook = useUpdateBook();

  return (
    <div className={`rounded-lg border border-neutral-200 bg-white p-4 ${importantRowClass(book.is_important)}`}>
      <div className="flex items-start gap-2">
        <StarButton
          important={book.is_important}
          onToggle={() => updateBook.mutate({ id: book.id, is_important: !book.is_important })}
        />
        <BookOpen className="mt-1 h-4 w-4 shrink-0 text-neutral-400" />
        <div className="min-w-0 flex-1">
          <BookTitle book={book} />
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <span className={`rounded px-1.5 py-0.5 text-xs ${statusBadgeClass(book.status)}`}>
            {BOOK_STATUS_LABELS[book.status] ?? book.status}
          </span>
          <span className={`rounded px-1.5 py-0.5 text-[11px] ${typeBadgeClass(book.book_type)}`}>
            {BOOK_TYPE_LABELS[book.book_type] ?? book.book_type}
          </span>
        </div>
      </div>
      {book.note && <p className="mt-2 line-clamp-2 text-xs text-neutral-500">{book.note}</p>}
      <div className="mt-3 flex items-center gap-1 text-xs text-neutral-500">
        <FileText className="h-3.5 w-3.5" /> 笔记 {book.note_count} 份
        <span className="ml-auto">
          <BookActions book={book} onEdit={onEdit} onManageNotes={onManageNotes} onBlocked={onBlocked} />
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
  const [titleCn, setTitleCn] = useState("");
  const [bookType, setBookType] = useState("book");
  const [author, setAuthor] = useState("");
  const [note, setNote] = useState("");
  const [url, setUrl] = useState("");
  const [status, setStatus] = useState("todo");

  useEffect(() => {
    if (open) {
      setTitle(book?.title ?? "");
      setTitleCn(book?.title_cn ?? "");
      setBookType(book?.book_type ?? "book");
      setAuthor(book?.author ?? "");
      setNote(book?.note ?? "");
      setUrl(book?.url ?? "");
      setStatus(book?.status ?? "todo");
    }
  }, [open, book]);

  const submit = () => {
    if (!title.trim()) return;
    const body = { title: title.trim(), title_cn: titleCn.trim(), book_type: bookType, author, note, url: url.trim(), status };
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
          <div>
            <Label>标题翻译（中文，可选）</Label>
            <Input value={titleCn} placeholder="原标题的中文翻译，单独保存展示" onChange={(e) => setTitleCn(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>作者</Label>
              <Input value={author} onChange={(e) => setAuthor(e.target.value)} />
            </div>
            <div>
              <Label>类型</Label>
              <Select value={bookType} onChange={(e) => setBookType(e.target.value)} aria-label="阅读类型">
                {BOOK_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {BOOK_TYPE_LABELS[t]}
                  </option>
                ))}
              </Select>
            </div>
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
          <div>
            <Label>备注</Label>
            <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <div>
            <Label>链接（可选）</Label>
            <Input value={url} placeholder="https://…（仅记录与跳转，不在展示栏显示内容）" onChange={(e) => setUrl(e.target.value)} />
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
  const [editorOpen, setEditorOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pickFile = () => fileInput.current?.click();

  const onFileChosen = (file: File | undefined) => {
    setError(null);
    if (!file || !book) return;
    if (!isNoteFileAllowed(file.name)) {
      setError("仅支持 PDF / PNG / JPG / MD / Jnotes 格式的笔记文件");
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
          accept=".pdf,.png,.jpg,.jpeg,.md,.jnotes"
          className="hidden"
          data-testid="note-file-input"
          onChange={(e) => {
            onFileChosen(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        {notes.length === 0 ? (
          <div className="py-4 text-center text-sm text-neutral-400">
            还没有笔记。可上传 PDF / PNG / JPG / MD 文件或云记 Jnotes（自动转 PDF），也可在线编写 Markdown 笔记。
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
          <Button variant="outline" onClick={() => setEditorOpen(true)}>
            <PenLine className="h-4 w-4" /> 在线写笔记
          </Button>
          <Button variant="outline" onClick={pickFile} disabled={uploadNote.isPending}>
            <Upload className="h-4 w-4" /> {uploadNote.isPending ? "上传中…" : "上传笔记"}
          </Button>
        </DialogFooter>
      </DialogContent>

      <MdNoteEditorDialog bookId={book?.id ?? 0} open={editorOpen} onClose={() => setEditorOpen(false)} />
      <PreviewDialog preview={preview} onClose={() => setPreview(null)} />
    </Dialog>
  );
}

function MdNoteEditorDialog({
  bookId,
  open,
  onClose,
}: {
  bookId: number;
  open: boolean;
  onClose: () => void;
}) {
  const createMdNote = useCreateMdNote(bookId);
  const [filename, setFilename] = useState("");
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setFilename("");
    setContent("");
    setError(null);
  };

  const save = () => {
    if (!content.trim()) {
      setError("笔记内容不能为空");
      return;
    }
    createMdNote.mutate(
      { filename: filename.trim(), content },
      {
        onSuccess: () => {
          reset();
          onClose();
        },
        onError: (e) => setError(e instanceof ApiError ? e.message : "保存失败"),
      }
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          reset();
          onClose();
        }
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>在线写笔记（Markdown）</DialogTitle>
        </DialogHeader>
        {error && (
          <div className="mb-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}
        <div className="space-y-3">
          <div>
            <Label htmlFor="md-note-filename">笔记名称（可留空，自动加 .md 后缀）</Label>
            <Input
              id="md-note-filename"
              value={filename}
              maxLength={200}
              placeholder="例如：第一章读后感"
              onChange={(e) => setFilename(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="md-note-content">内容（Markdown）</Label>
            <Textarea
              id="md-note-content"
              rows={12}
              value={content}
              placeholder={"# 标题\n\n- 要点\n\n正文…"}
              className="font-mono text-sm"
              onChange={(e) => setContent(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={createMdNote.isPending}>
            取消
          </Button>
          <Button onClick={save} disabled={createMdNote.isPending}>
            {createMdNote.isPending ? "保存中…" : "保存笔记"}
          </Button>
        </DialogFooter>
      </DialogContent>
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
      <DialogContent className="max-w-6xl">
        <DialogHeader>
          <DialogTitle>{preview?.filename}</DialogTitle>
        </DialogHeader>
        {preview && (
          <div className="max-h-[85vh] overflow-auto">
            {isImage ? (
              <img src={src} alt={preview.filename} className="mx-auto max-w-full" />
            ) : (
              <iframe src={src} title={preview.filename} className="h-[82vh] w-full border-0" />
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" asChild>
            <a href={`${src}?download=1`} download={preview?.filename}>
              <Download className="h-4 w-4" /> 下载
            </a>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
