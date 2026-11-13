import { useState } from "react";
import { reviewQueue, useDailyQuestions, useReviewQuestion } from "../../api/dailyQuestions";
import { Button } from "../ui/button";

export function DailyQuestionsPanel() {
  const questions = useDailyQuestions();
  const [expanded, setExpanded] = useState<number | null>(null);
  const [seen, setSeen] = useState<number[]>([]);
  const [all, setAll] = useState(false);
  const review = useReviewQuestion();
  const items = questions.data ?? [];
  const current = reviewQueue(items, seen, all)[0];

  return <section className="flex min-h-0 flex-col" aria-label="每日一问">
    <div className="flex items-center justify-between px-3 py-2">
      <h2 className="text-xs font-semibold text-neutral-700">每日一问</h2>
      <a href="/knowledge" className="text-xs text-blue-600">复习知识库</a>
    </div>
    <div className="min-h-0 overflow-y-auto px-3 pb-3">
      {questions.isLoading ? <p className="py-4 text-center text-xs text-neutral-400">加载中…</p>
        : questions.isError ? <div role="alert" className="text-xs text-red-600">问答加载失败 <button onClick={() => void questions.refetch()}>重试</button></div>
        : current ? <div className="rounded-md border border-neutral-200 p-2">
          <button disabled={review.isPending} className="w-full whitespace-pre-wrap break-words text-left text-base leading-7" aria-expanded={expanded === current.id}
            aria-controls={`daily-answer-${current.id}`} onClick={() => { review.reset(); setExpanded(expanded === current.id ? null : current.id); }}>
            {current.question}
            <span className="mt-1 block text-xs text-neutral-500">{expanded === current.id ? "收起答案" : "展开答案"}</span>
          </button>
          {expanded === current.id && <>
            <div id={`daily-answer-${current.id}`} className="mt-2 whitespace-pre-wrap break-words border-t pt-2 text-base leading-7 text-neutral-600">{current.answer}</div>
            <div className="mt-3 flex gap-2">{[false, true].map(remembered => <Button key={String(remembered)} size="sm"
              variant={remembered ? "default" : "outline"} disabled={review.isPending}
              onClick={() => review.mutate({ id: current.id, remembered }, { onSuccess: () => {
                setSeen(previous => [...previous, current.id]); setExpanded(null);
              } })}>{remembered ? "记住了" : "没记住"}</Button>)}</div>
            {review.isError && <p role="alert" className="mt-2 text-xs text-red-600">复习记录保存失败，请重试。</p>}
          </>}
        </div>
        : <div className="space-y-2 py-3 text-center">
          <p className="text-xs text-neutral-400">{items.length ? "本轮已完成，暂无待复习或新题。" : "还没有知识，前往知识库记录问答。"}</p>
          {items.length > 0 && <Button size="sm" variant="outline" onClick={() => { setSeen([]); setAll(true); setExpanded(null); review.reset(); }}>再练一轮</Button>}
        </div>}
    </div>
  </section>;
}
