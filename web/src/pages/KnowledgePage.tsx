import { useState } from "react";
import { DailyQuestion, reviewQueue, useDailyQuestions, useReviewQuestion, useSaveDailyQuestion } from "../api/dailyQuestions";
import { Button } from "../components/ui/button";
import { cn } from "../lib/utils";

export function KnowledgePage() {
  const [tab, setTab] = useState<"review" | "questions">("review");
  const query = useDailyQuestions();
  const save = useSaveDailyQuestion();
  const review = useReviewQuestion();
  const [seen, setSeen] = useState<number[]>([]);
  const [all, setAll] = useState(false);
  const [revealed, setRevealed] = useState<number | null>(null);
  const [editing, setEditing] = useState<number | null | undefined>(undefined);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [tags, setTags] = useState("");
  const [search, setSearch] = useState("");
  const items = query.data ?? [];
  const current = reviewQueue(items, seen, all)[0];
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
    {tab === "review" && <section aria-label="记忆练习" className="space-y-4 rounded-xl border bg-white p-6">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">{all ? "自由练习" : "今日复习"}</h2><Button variant="outline" disabled={query.isFetching || review.isPending} onClick={() => { setRevealed(null); void query.refetch(); }}>刷新题库</Button></div>
      {query.isLoading ? <p>加载中…</p> : current ? <>
        <p className="whitespace-pre-wrap break-words text-xl">{current.question}</p>
        {current.tags && <p className="text-sm text-neutral-500">{current.tags}</p>}
        {revealed !== current.id ? <Button onClick={() => { review.reset(); setRevealed(current.id); }}>查看答案</Button> : <>
          <div className="whitespace-pre-wrap break-words rounded-lg bg-neutral-50 p-4 text-lg">{current.answer}</div>
          <div className="flex gap-3">{[false,true].map(remembered => <Button key={String(remembered)} variant={remembered ? "default" : "outline"} disabled={review.isPending} onClick={() => review.mutate({id: current.id, remembered}, {onSuccess: () => {setSeen(s => [...s,current.id]); setRevealed(null);}})}>{remembered ? "记住了" : "没记住"}</Button>)}</div>
        </>}
        {review.isError && <p role="alert" className="text-red-600">复习记录保存失败，请重试。</p>}
      </> : <div className="space-y-3"><p>{items.length ? "本轮已完成。刷新可获取新题，或再练一轮。" : "还没有知识，先记录一个问题和答案吧。"}</p>{items.length > 0 && <Button onClick={() => {setSeen([]); setAll(true); setRevealed(null);}}>再练一轮</Button>}</div>}
      <p className="text-xs text-neutral-500">优先到期复习，再学新题。记住后按1、3、7、14、30天复习；没记住10分钟后再试。</p>
    </section>}
    {editing !== undefined && <form className="space-y-3 rounded-xl border bg-white p-5" onSubmit={e => {e.preventDefault(); save.mutate({id: editing ?? undefined, question, answer, tags}, {onSuccess: () => setEditing(undefined)});}}>
      <h2 className="font-semibold">{editing === null ? "记录问答" : "编辑问答"}</h2>
      <label className="block">问题<textarea className="mt-1 block w-full rounded border p-2" required maxLength={500} value={question} onChange={e=>setQuestion(e.target.value)} /></label>
      <label className="block">答案<textarea className="mt-1 block w-full rounded border p-2" required rows={5} maxLength={50000} value={answer} onChange={e=>setAnswer(e.target.value)} /></label>
      <label className="block">标签<input className="ml-2 rounded border p-2" maxLength={200} placeholder="例如：Python、工作" value={tags} onChange={e=>setTags(e.target.value)} /></label>
      {save.isError && <p role="alert" className="text-red-600">保存失败，请重试。</p>}
      <div className="flex gap-2"><Button disabled={save.isPending || !question.trim() || !answer.trim()} type="submit">保存</Button><Button type="button" variant="outline" onClick={()=>setEditing(undefined)}>取消</Button></div>
    </form>}
    {tab === "questions" && <section className="space-y-3"><h2 className="text-lg font-semibold">全部问答</h2><input aria-label="搜索知识" className="w-full rounded border p-2" placeholder="搜索问题、答案或标签" value={search} onChange={e=>setSearch(e.target.value)} />
      {items.filter(q => `${q.question} ${q.answer} ${q.tags ?? ""}`.toLowerCase().includes(search.toLowerCase())).map(q => <article key={q.id} className="rounded-lg border bg-white p-4"><div className="flex items-start justify-between gap-4"><span className="whitespace-pre-wrap break-words font-medium">{q.question}</span><Button variant="outline" onClick={()=>edit(q)}>编辑</Button></div><p className="mt-1 text-xs text-neutral-500">{q.tags} · 已练 {q.review_count ?? 0} 次 · {q.due_at ? `下次复习 ${new Date(q.due_at).toLocaleString()}` : "新题"}</p><details className="mt-2"><summary className="cursor-pointer text-sm text-neutral-500">答案</summary><p className="mt-2 whitespace-pre-wrap break-words">{q.answer}</p></details></article>)}
    </section>}
  </div>;
}
