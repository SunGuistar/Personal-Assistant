import { useState } from "react";
import { DailyQuestion, useDailyQuestions, useSaveDailyQuestion } from "../api/dailyQuestions";
import { QuestionPractice } from "../components/QuestionPractice";
import { Button } from "../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { cn } from "../lib/utils";

export function KnowledgePage() {
  const [tab, setTab] = useState<"review" | "questions">("review");
  const query = useDailyQuestions();
  const save = useSaveDailyQuestion();
  const [editing, setEditing] = useState<number | null | undefined>(undefined);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [tags, setTags] = useState("");
  const [search, setSearch] = useState("");
  const items = query.data ?? [];
  const fresh = items.filter(q => !q.due_at).length;
  const due = items.filter(q => q.due_at && Date.parse(q.due_at) <= Date.now()).length;
  function edit(item?: DailyQuestion) {
    setEditing(item?.id ?? null); setQuestion(item?.question ?? ""); setAnswer(item?.answer ?? ""); setTags(item?.tags ?? ""); save.reset();
  }
  return <div className="mx-auto max-w-5xl space-y-6">
    <header className="flex items-center justify-between"><div><h1 className="text-2xl font-semibold">知识库</h1><p className="mt-2 text-neutral-500">先回忆，再看答案。总计 {items.length} · 新题 {fresh} · 待复习 {due}</p></div><Button onClick={() => edit()}>记录问答</Button></header>
    <nav aria-label="知识库视图" className="flex gap-1 border-b border-neutral-200 pt-2 dark:border-neutral-800">
      {([["review", "今日复习"], ["questions", "全部问答"]] as const).map(([key, label]) => <button
        key={key} onClick={() => setTab(key)} aria-current={tab === key ? "page" : undefined}
        className={cn("rounded-t-md px-4 py-2 text-sm", tab === key
          ? "bg-neutral-900 text-neutral-50 dark:bg-neutral-100 dark:text-neutral-900"
          : "text-neutral-600 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-800")}
      >{label}</button>)}
    </nav>
    {query.isError && <p role="alert">知识库加载失败，请点击刷新重试。</p>}
    {tab === "review" && <QuestionPractice />}
    {editing !== undefined && <QuestionEditor editing={editing} onClose={() => setEditing(undefined)}>
    <form className="space-y-3 rounded-xl border bg-white p-5" onSubmit={e => {e.preventDefault(); save.mutate({id: editing ?? undefined, question, answer, tags}, {onSuccess: () => setEditing(undefined)});}}>
      {editing === null && <h2 className="font-semibold">记录问答</h2>}
      <label className="block">问题<textarea className="mt-1 block w-full rounded border p-2" required maxLength={500} value={question} onChange={e=>setQuestion(e.target.value)} /></label>
      <label className="block">答案<textarea className="mt-1 block w-full rounded border p-2" required rows={5} maxLength={50000} value={answer} onChange={e=>setAnswer(e.target.value)} /></label>
      <label className="block">标签<input className="ml-2 rounded border p-2" maxLength={200} placeholder="例如：Python、工作" value={tags} onChange={e=>setTags(e.target.value)} /></label>
      {save.isError && <p role="alert" className="text-red-600">保存失败，请重试。</p>}
      <div className="flex gap-2"><Button disabled={save.isPending || !question.trim() || !answer.trim()} type="submit">保存</Button><Button type="button" variant="outline" onClick={()=>setEditing(undefined)}>取消</Button></div>
    </form></QuestionEditor>}
    {tab === "questions" && <section className="space-y-3"><h2 className="text-lg font-semibold">全部问答</h2><input aria-label="搜索知识" className="w-full rounded border p-2" placeholder="搜索问题、答案或标签" value={search} onChange={e=>setSearch(e.target.value)} />
      {items.filter(q => `${q.question} ${q.answer} ${q.tags ?? ""}`.toLowerCase().includes(search.toLowerCase())).map(q => <article key={q.id} className="rounded-lg border bg-white p-4"><div className="flex items-start justify-between gap-4"><span className="whitespace-pre-wrap break-words font-medium">{q.question}</span><Button variant="outline" onClick={()=>edit(q)}>编辑</Button></div><p className="mt-1 text-xs text-neutral-500">{q.tags} · 已练 {q.review_count ?? 0} 次 · 记住 {q.remembered_count ?? 0} 次 · 没记住 {q.forgotten_count ?? 0} 次 · {q.due_at ? `下次复习 ${new Date(q.due_at).toLocaleString()}` : "新题"}</p><details className="mt-2"><summary className="cursor-pointer text-sm text-neutral-500">答案</summary><p className="mt-2 whitespace-pre-wrap break-words">{q.answer}</p></details></article>)}
    </section>}
  </div>;
}

function QuestionEditor({ editing, onClose, children }: { editing: number | null; onClose: () => void; children: React.ReactNode }) {
  if (editing === null) return <>{children}</>;
  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto" aria-describedby={undefined}>
      <DialogHeader><DialogTitle>编辑问答</DialogTitle></DialogHeader>
      {children}
    </DialogContent>
  </Dialog>;
}
