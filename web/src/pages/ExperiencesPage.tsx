import { useState } from "react";
import { NotebookPen, Search } from "lucide-react";
import { Experience, ExperienceInput, useExperiences, useSaveExperience } from "../api/experiences";
import { Button } from "../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { cn } from "../lib/utils";
import { ApiError } from "../lib/api";

const empty: ExperienceInput = { title: "", problem: "", solution: "", tags: "" };
function tagsOf(value: string) { return value.split(/[,，、;；\n]+/).map(tag => tag.trim()).filter(Boolean); }

export function ExperiencesPage() {
  const query = useExperiences();
  const save = useSaveExperience();
  const [search, setSearch] = useState("");
  const [tag, setTag] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [editing, setEditing] = useState<number | null | undefined>(undefined);
  const [form, setForm] = useState<ExperienceInput>(empty);
  const items = query.data ?? [];
  const tags = Array.from(new Set(items.flatMap(item => tagsOf(item.tags)))).sort();
  const filtered = items.filter(item => (!tag || tagsOf(item.tags).includes(tag)) &&
    `${item.title} ${item.problem} ${item.solution} ${item.tags}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const current = filtered.find(item => item.id === selected) ?? filtered[0];
  function edit(item?: Experience) {
    setEditing(item?.id ?? null);
    setForm(item ? { title: item.title, problem: item.problem, solution: item.solution, tags: item.tags } : empty);
    save.reset();
  }
  return <div className="mx-auto max-w-6xl space-y-5">
    <header className="flex items-center justify-between">
      <div><h1 className="text-2xl font-semibold">经验库</h1><p className="mt-2 text-sm text-neutral-500">记下工作中遇到的问题和解决方法，方便下次查阅。</p></div>
      <Button onClick={() => edit()}><NotebookPen className="mr-2 h-4 w-4" />记录经验</Button>
    </header>
    <div className="flex gap-3">
      <label className="flex flex-1 items-center gap-2 rounded-lg border bg-white px-3"><Search className="h-4 w-4 text-neutral-400" /><input aria-label="搜索经验" className="w-full bg-transparent py-2 outline-none" placeholder="搜索标题、问题、解决方法或标签" value={search} onChange={event => setSearch(event.target.value)} /></label>
      <select aria-label="筛选经验标签" className="max-w-48 rounded-lg border bg-white px-3" value={tag} onChange={event => setTag(event.target.value)}><option value="">全部标签</option>{tags.map(value => <option key={value}>{value}</option>)}</select>
    </div>
    {query.isPending ? <p role="status" className="text-sm text-neutral-500">正在加载经验记录…</p>
      : query.isError ? <div role="alert">{query.error instanceof ApiError && query.error.code === "experiences_schema_missing" ? query.error.message : "经验库加载失败。"}<Button variant="outline" onClick={() => void query.refetch()}>重试</Button></div>
      : !current ? <div className="rounded-xl border border-dashed p-12 text-center text-neutral-500">{items.length ? "没有匹配的经验，试试其他关键词或标签。" : "还没有经验记录，点击“记录经验”保存第一条问题与解决方法。"}</div>
      : <div className="grid grid-cols-[minmax(220px,1fr)_minmax(0,2fr)] gap-5">
        <section aria-label="经验列表" className="space-y-2"><p className="mb-3 text-xs text-neutral-500">共 {filtered.length} 条经验 · 最近更新优先</p>
          {filtered.map(item => <button key={item.id} onClick={() => setSelected(item.id)} aria-pressed={current.id === item.id} className={cn("w-full rounded-lg border bg-white p-4 text-left", current.id === item.id ? "border-neutral-900 ring-1 ring-neutral-900" : "border-neutral-200 hover:border-neutral-400")}>
            <span className="block break-words font-medium">{item.title}</span><span className="mt-2 line-clamp-2 block break-words text-sm text-neutral-500">{item.problem}</span><span className="mt-3 block break-words text-xs text-neutral-400">{tagsOf(item.tags).join(" · ") || "未分类"}</span>
          </button>)}
        </section>
        <article aria-label="经验详情" className="min-w-0 rounded-xl border bg-white p-6">
          <div className="flex items-start justify-between gap-4"><h2 className="break-words text-xl font-semibold">{current.title}</h2><Button variant="outline" onClick={() => edit(current)}>编辑</Button></div>
          <p className="mt-2 break-words text-xs text-neutral-400">更新于 {new Date(current.updated_at).toLocaleString()} {current.tags && ` · ${tagsOf(current.tags).join(" · ")}`}</p>
          <h3 className="mb-3 mt-7 font-medium">遇到的问题</h3><p className="whitespace-pre-wrap break-words text-sm leading-7 text-neutral-700">{current.problem}</p>
          <h3 className="mb-3 mt-7 font-medium">解决方法</h3><p className="whitespace-pre-wrap break-words text-sm leading-7 text-neutral-700">{current.solution}</p>
        </article>
      </div>}
    <Dialog open={editing !== undefined} onOpenChange={open => { if (!open && !save.isPending) setEditing(undefined); }}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto" aria-describedby={undefined}><DialogHeader><DialogTitle>{editing === null ? "记录经验" : "编辑经验"}</DialogTitle></DialogHeader>
        <form className="space-y-4" onSubmit={event => { event.preventDefault(); save.mutate({ ...form, id: editing ?? undefined }, { onSuccess: saved => { setSelected(saved.id); setSearch(""); setTag(""); setEditing(undefined); } }); }}>
          <label className="block text-sm">标题<input required maxLength={200} value={form.title} onChange={event => setForm({ ...form, title: event.target.value })} className="mt-1 w-full rounded border p-2" placeholder="一句话概括问题" /></label>
          <label className="block text-sm">遇到的问题<textarea required rows={4} maxLength={50000} value={form.problem} onChange={event => setForm({ ...form, problem: event.target.value })} className="mt-1 w-full rounded border p-2" placeholder="当时的场景、现象或报错" /></label>
          <label className="block text-sm">解决方法<textarea required rows={6} maxLength={50000} value={form.solution} onChange={event => setForm({ ...form, solution: event.target.value })} className="mt-1 w-full rounded border p-2" placeholder="有效的处理步骤、原因或注意事项" /></label>
          <label className="block text-sm">标签（可选）<input maxLength={200} value={form.tags} onChange={event => setForm({ ...form, tags: event.target.value })} className="mt-1 w-full rounded border p-2" placeholder="例如：Python，数据库，Windows" /></label>
          {save.isError && <p role="alert" className="text-sm text-red-600">保存失败，内容已保留，请重试。</p>}
          <div className="flex justify-end gap-2"><Button type="button" variant="outline" disabled={save.isPending} onClick={() => setEditing(undefined)}>取消</Button><Button type="submit" disabled={save.isPending || !form.title.trim() || !form.problem.trim() || !form.solution.trim()}>{save.isPending ? "保存中…" : "保存"}</Button></div>
        </form>
      </DialogContent>
    </Dialog>
  </div>;
}
