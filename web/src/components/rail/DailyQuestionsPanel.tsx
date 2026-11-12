import { useState } from "react";
import { Pencil, Plus } from "lucide-react";
import { DailyQuestion, useDailyQuestions, useSaveDailyQuestion } from "../../api/dailyQuestions";
import { Button } from "../ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../ui/dialog";
import { Label, Textarea } from "../ui/input";

export function DailyQuestionsPanel() {
  const questions = useDailyQuestions();
  const save = useSaveDailyQuestion();
  const [expanded, setExpanded] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<DailyQuestion | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const edit = (item: DailyQuestion | null) => {
    setEditing(item);
    setQuestion(item?.question ?? "");
    setAnswer(item?.answer ?? "");
    save.reset();
    setOpen(true);
  };
  return (
    <section className="flex min-h-0 flex-col" aria-label="每日一问">
      <div className="flex items-center justify-between px-3 py-2">
        <h2 className="text-xs font-semibold text-neutral-700">每日一问</h2>
        <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={() => edit(null)}>
          <Plus className="h-3.5 w-3.5" /> 新增
        </Button>
      </div>
      <div className="min-h-0 overflow-y-auto px-3 pb-3">
        {questions.isLoading ? <p className="py-4 text-center text-xs text-neutral-400">加载中…</p>
          : questions.isError ? <div role="alert" className="text-xs text-red-600">问答加载失败 <button onClick={() => questions.refetch()}>重试</button></div>
          : !questions.data?.length ? <p className="py-4 text-center text-xs text-neutral-400">还没有每日一问</p>
          : <ul className="space-y-2">{questions.data.map(item => (
            <li key={item.id} className="rounded-md border border-neutral-200 p-2">
              <div className="flex items-start gap-2">
                <button className="min-w-0 flex-1 whitespace-pre-wrap break-words text-left text-sm" aria-expanded={expanded === item.id}
                  aria-controls={`daily-answer-${item.id}`} onClick={() => setExpanded(expanded === item.id ? null : item.id)}>{item.question}</button>
                <button aria-label={`编辑问题：${item.question}`} className="p-0.5 text-neutral-400 hover:text-neutral-700" onClick={() => edit(item)}><Pencil className="h-3.5 w-3.5" /></button>
              </div>
              {expanded === item.id && <div id={`daily-answer-${item.id}`} className="mt-2 whitespace-pre-wrap break-words border-t pt-2 text-sm text-neutral-600">{item.answer}</div>}
            </li>
          ))}</ul>}
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editing ? "编辑每日一问" : "新增每日一问"}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label htmlFor="daily-question">问题</Label><Textarea id="daily-question" autoFocus rows={2} maxLength={500} value={question} onChange={e => setQuestion(e.target.value)} /></div>
            <div><Label htmlFor="daily-answer">答案</Label><Textarea id="daily-answer" rows={6} maxLength={50000} value={answer} onChange={e => setAnswer(e.target.value)} /></div>
            {save.isError && <p role="alert" className="text-sm text-red-600">保存失败，请重试。</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>取消</Button>
            <Button disabled={!question.trim() || !answer.trim() || save.isPending} onClick={() => save.mutate({ id: editing?.id, question: question.trim(), answer: answer.trim() }, { onSuccess: () => setOpen(false) })}>{save.isPending ? "保存中…" : "保存"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
