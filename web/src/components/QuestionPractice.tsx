import { useEffect, useState, useId } from "react";
import { type DailyQuestion, reviewQueue, useDailyQuestions, useReviewQuestion, useDailyQuestionRound, useReviewDailyRound } from "../api/dailyQuestions";
import { Button } from "./ui/button";

export function QuestionPractice({ compact = false }: { compact?: boolean }) {
  const answerId = useId();
  const questions = useDailyQuestionRound();
  const library = useDailyQuestions();
  const [expanded, setExpanded] = useState<number | null>(null);
  const [roundQueue, setRoundQueue] = useState<DailyQuestion[] | null>(null);
  const dailyReview = useReviewDailyRound();
  const extraReview = useReviewQuestion();
  const review = roundQueue === null ? dailyReview : extraReview;
  const queue = roundQueue ?? questions.data?.queue ?? [];
  const current = queue[0];
  useEffect(() => {
    setRoundQueue(null);
    setExpanded(null);
  }, [questions.data?.review_date]);
  useEffect(() => { setExpanded(null); }, [questions.data?.version]);

  return <section className={compact ? "flex min-h-0 flex-col" : "flex min-h-0 flex-col rounded-xl border bg-white p-4"} aria-label={compact ? "每日一问" : "记忆练习"}>
    <div className="flex items-center justify-between px-3 py-2">
      <div className="flex items-center gap-2">
        <h2 className="text-xs font-semibold text-neutral-700">{compact ? "每日一问" : "今日复习"}</h2>
        {questions.isSuccess && <span className="text-xs text-neutral-500">已完成 {questions.data.completed}/{questions.data.total}</span>}
      </div>
      <div className="flex items-center gap-3">
        <button className="text-xs text-blue-600" disabled={questions.isFetching || library.isFetching || review.isPending} onClick={() => { setExpanded(null); void questions.refetch(); void library.refetch(); }}>刷新题库</button>
        {compact && <a href="/knowledge" className="text-xs text-blue-600">复习知识库</a>}
      </div>
    </div>
    <div className="min-h-0 overflow-y-auto px-3 pb-3">
      {roundQueue !== null && <p className="mb-2 text-xs text-neutral-500">额外练习 <button className="ml-2 text-blue-600" disabled={review.isPending} onClick={() => { setRoundQueue(null); setExpanded(null); extraReview.reset(); }}>返回今日</button></p>}
      {questions.isLoading ? <p className="py-4 text-center text-xs text-neutral-400">加载中…</p>
        : questions.isError ? <div role="alert" className="text-xs text-red-600">问答加载失败 <button onClick={() => void questions.refetch()}>重试</button></div>
        : current ? <div className="rounded-md border border-neutral-200 p-2">
          <button disabled={review.isPending} className="w-full whitespace-pre-wrap break-words text-left text-base leading-7" aria-expanded={expanded === current.id}
            aria-controls={`${answerId}-${current.id}`} onClick={() => { review.reset(); setExpanded(expanded === current.id ? null : current.id); }}>
            {current.question}
            <span className="mt-1 block text-xs text-neutral-500">{expanded === current.id ? "收起答案" : "展开答案"}</span>
          </button>
          {current.tags && <p className="mt-1 text-xs text-neutral-500">{current.tags}</p>}
          {expanded === current.id && <>
            <div id={`${answerId}-${current.id}`} className="mt-2 whitespace-pre-wrap break-words border-t pt-2 text-base leading-7 text-neutral-600">{current.answer}</div>
            <div className="mt-3 flex gap-2">{[false, true].map(remembered => <Button key={String(remembered)} size="sm"
              variant={remembered ? "default" : "outline"} disabled={review.isPending}
              onClick={() => {
                if (roundQueue !== null) extraReview.mutate({ id: current.id, remembered }, { onSuccess: updated => {
                  setRoundQueue(remembered ? queue.slice(1) : [...queue.slice(1), updated]); setExpanded(null);
                } });
                else if (questions.data) dailyReview.mutate({ question_id: current.id, remembered,
                  review_date: questions.data.review_date, version: questions.data.version }, { onSuccess: () => setExpanded(null) });
              }}>{remembered ? "记住了" : "没记住"}</Button>)}</div>
            {review.isError && <p role="alert" className="mt-2 text-xs text-red-600">复习记录保存失败，请重试。</p>}
          </>}
        </div>
        : <div className="space-y-2 py-3 text-center">
          <p className="text-xs text-neutral-400">{!questions.data?.has_questions ? "还没有知识，前往知识库记录问答。"
            : roundQueue !== null ? "本轮全部记住了。"
            : questions.data.total > 0 ? "今日题目全部记住了。" : "今日暂无待复习或新题，新题明日纳入。"}</p>
          {questions.data?.has_questions && <Button size="sm" variant="outline" disabled={library.isFetching || library.isError || !library.data} onClick={() => { setRoundQueue(reviewQueue(library.data ?? [], [], true)); setExpanded(null); extraReview.reset(); }}>再练一轮</Button>}
        </div>}
    </div>
  </section>;
}
