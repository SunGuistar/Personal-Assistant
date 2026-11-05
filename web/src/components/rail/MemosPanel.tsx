import { useState } from "react";
import { ListChecks, Plus } from "lucide-react";

import { Button } from "../ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import { Input, Label, Select, Textarea } from "../ui/input";
import { RecordCard } from "./RecordCard";
import { TASK_TYPES, TASK_TYPE_LABELS, TaskType } from "../../api/plans";
import { todayStr } from "../../lib/api";
import {
  Memo,
  useCreateMemo,
  useDeleteMemo,
  useMemoToTask,
  useMemos,
  useReorderMemos,
  useUpdateMemo,
} from "../../api/infos";

function MemoDialog({
  open,
  onOpenChange,
  memo,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  memo: Memo | null;
}) {
  const createMemo = useCreateMemo();
  const updateMemo = useUpdateMemo();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  const [prevOpen, setPrevOpen] = useState(false);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setTitle(memo?.title ?? "");
      setContent(memo?.content ?? "");
    }
  }

  const submit = () => {
    const trimmed = title.trim();
    if (!trimmed) return;
    if (memo) {
      updateMemo.mutate({ id: memo.id, title: trimmed, content }, { onSuccess: () => onOpenChange(false) });
    } else {
      createMemo.mutate({ title: trimmed, content }, { onSuccess: () => onOpenChange(false) });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{memo ? "编辑随手备忘" : "新增随手备忘"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>标题</Label>
            <Input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div>
            <Label>内容（支持基础 Markdown）</Label>
            <Textarea rows={4} value={content} onChange={(e) => setContent(e.target.value)} />
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

/** 随手备忘 → 每日任务 的确认弹窗（默认今天/日常/非重要，可改）。 */
function MemoToTaskDialog({
  memo,
  onClose,
}: {
  memo: Memo;
  onClose: () => void;
}) {
  const memoToTask = useMemoToTask();
  const [targetDate, setTargetDate] = useState(todayStr());
  const [taskType, setTaskType] = useState<TaskType>("daily");
  const [isImportant, setIsImportant] = useState(false);

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>转为每日任务</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-neutral-500">
          「{memo.title}」将转为每日任务并从备忘中移除；内容将保存到任务备注。
        </p>
        <div className="space-y-3">
          <div>
            <Label>执行日期</Label>
            <Input type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} />
          </div>
          <div>
            <Label>任务类型</Label>
            <Select value={taskType} onChange={(e) => setTaskType(e.target.value as TaskType)}>
              {TASK_TYPES.map((t) => (
                <option key={t} value={t}>
                  {TASK_TYPE_LABELS[t]}
                </option>
              ))}
            </Select>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={isImportant} onChange={(e) => setIsImportant(e.target.checked)} className="accent-red-500" />
            标记为重要
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            disabled={memoToTask.isPending}
            onClick={() =>
              memoToTask.mutate(
                { id: memo.id, target_date: targetDate, task_type: taskType, is_important: isImportant },
                { onSuccess: onClose }
              )
            }
          >
            转换
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** 右侧栏下部：随手备忘（约 60% 高度，独立滚动；可转为每日任务）。 */
export function MemosPanel() {
  const { data: memos = [] } = useMemos();
  const reorder = useReorderMemos();
  const deleteMemo = useDeleteMemo();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Memo | null>(null);
  const [converting, setConverting] = useState<Memo | null>(null);
  const ids = memos.map((m) => m.id);

  const swap = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= ids.length) return;
    const next = [...ids];
    [next[index], next[target]] = [next[target], next[index]];
    reorder.mutate(next);
  };

  return (
    <section className="flex min-h-0 flex-[3] flex-col">
      <div className="flex items-center justify-between px-3 py-2">
        <h2 className="text-xs font-semibold text-neutral-700">随手备忘</h2>
        <Button
          size="sm"
          variant="outline"
          className="h-6 px-2 text-xs"
          onClick={() => {
            setEditing(null);
            setDialogOpen(true);
          }}
        >
          <Plus className="h-3.5 w-3.5" /> 新增
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {memos.length === 0 ? (
          <div className="py-4 text-center text-xs text-neutral-400">还没有随手备忘</div>
        ) : (
          <ul className="space-y-2">
            {memos.map((memo, index) => (
              <RecordCard
                key={memo.id}
                title={memo.title}
                content={memo.content}
                canUp={index > 0}
                canDown={index < memos.length - 1}
                onMove={(direction) => swap(index, direction)}
                onEdit={() => {
                  setEditing(memo);
                  setDialogOpen(true);
                }}
                onDelete={() => deleteMemo.mutate(memo.id)}
                deleteConfirm={`删除随手备忘「${memo.title}」？`}
                extraAction={
                  <button
                    onClick={() => setConverting(memo)}
                    aria-label="转为每日任务"
                    title="转为每日任务"
                    className="p-0.5 text-neutral-400 hover:text-green-600"
                  >
                    <ListChecks className="h-3.5 w-3.5" />
                  </button>
                }
              />
            ))}
          </ul>
        )}
      </div>
      <MemoDialog open={dialogOpen} onOpenChange={setDialogOpen} memo={editing} />
      {converting && <MemoToTaskDialog memo={converting} onClose={() => setConverting(null)} />}
    </section>
  );
}
