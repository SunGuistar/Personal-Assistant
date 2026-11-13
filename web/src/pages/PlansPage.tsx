import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  CalendarPlus,
  Check,
  CheckCheck,
  History,
  NotebookPen,
  Pencil,
  Plus,
  Star,
  Trash2,
} from "lucide-react";

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
import { todayStr } from "../lib/api";
import { ImportantInfosPanel } from "../components/rail/ImportantInfosPanel";
import { DailyQuestionsPanel } from "../components/rail/DailyQuestionsPanel";
import { MemosPanel } from "../components/rail/MemosPanel";
import { CleanupBanner } from "./CleanupPage";
import { MorningReportBanner } from "../components/MorningReportBanner";
import {
  DailyTask,
  Plan,
  TASK_TYPE_BADGE_CLASS,
  TASK_TYPE_LABELS,
  TASK_TYPES,
  TaskType,
  useCompletePlan,
  useCreatePlan,
  useCreateTask,
  useDailyTasks,
  useDeletePlan,
  useDeleteTask,
  usePlanHistory,
  usePlans,
  useReorderPlans,
  useTaskHistory,
  useTaskToMemo,
  useUpdatePlan,
  useUpdateTask,
} from "../api/plans";

function dateLabel(date: string): string {
  const today = todayStr();
  const tomorrow = todayStr(1);
  const yesterday = todayStr(-1);
  if (date === today) return "今天";
  if (date === tomorrow) return "明天";
  if (date === yesterday) return "昨天";
  return date;
}

function completedAtLabel(completedAt: string | null): string {
  return completedAt ?? "完成时间未知";
}

function importantTitleClass(isImportant: boolean, done: boolean): string {
  if (done) return "text-neutral-400 line-through";
  return isImportant ? "text-red-700" : "text-neutral-900";
}

/** 任务类型徽标配色（复用 api/plans 的 TASK_TYPE_BADGE_CLASS）。 */

export function PlansPage() {
  const [date, setDate] = useState(todayStr());
  const { data: tasks = [], isLoading } = useDailyTasks(date);
  const { data: plans = [] } = usePlans();

  return (
    <div className="space-y-4">
      <MorningReportBanner />
      <h1 className="text-xl font-semibold">计划管理</h1>
      <CleanupBanner />
      <DateBar date={date} onChange={setDate} />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="grid gap-4 self-start xl:grid-cols-2 lg:col-span-2">
          <DailyPanel date={date} tasks={tasks} loading={isLoading} />
          <PlansPanel plans={plans} />
        </div>
        {/* 重要信息与随手备忘仅在此页面展示（原为全局右栏） */}
        <div className="flex flex-col gap-4">
          <div className="flex max-h-[38vh] flex-col overflow-hidden rounded-lg border border-neutral-200 bg-white">
            <ImportantInfosPanel />
          </div>
          <div className="flex max-h-[60vh] flex-col overflow-hidden rounded-lg border border-neutral-200 bg-white">
            <MemosPanel />
          </div>
          <div className="flex max-h-[40vh] flex-col overflow-hidden rounded-lg border border-neutral-200 bg-white">
            <DailyQuestionsPanel />
          </div>
        </div>
      </div>
    </div>
  );
}

function DateBar({ date, onChange }: { date: string; onChange: (d: string) => void }) {
  const offset = (days: number) => {
    const base = new Date(date);
    base.setDate(base.getDate() + days);
    onChange(base.toISOString().slice(0, 10));
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" onClick={() => offset(-1)}>
        前一天
      </Button>
      <Button variant={date === todayStr() ? "default" : "outline"} size="sm" onClick={() => onChange(todayStr())}>
        今天
      </Button>
      <Button variant="outline" size="sm" onClick={() => offset(1)}>
        后一天
      </Button>
      <Input
        type="date"
        value={date}
        onChange={(event) => onChange(event.target.value)}
        className="w-40"
        aria-label="选择日期"
      />
      <span className="text-sm text-neutral-500">{dateLabel(date)}</span>
    </div>
  );
}

function DailyPanel({
  date,
  tasks,
  loading,
}: {
  date: string;
  tasks: DailyTask[];
  loading: boolean;
}) {
  const createTask = useCreateTask(date);
  const [newTitle, setNewTitle] = useState("");
  const [newType, setNewType] = useState<TaskType>("daily");
  const [historyOpen, setHistoryOpen] = useState(false);

  const submit = () => {
    const title = newTitle.trim();
    if (!title) return;
    createTask.mutate({ title, task_type: newType }, { onSuccess: () => setNewTitle("") });
  };

  // 统一待办列表（后端已按 未完成优先>重要>类型>sort_order 排序）：
  // 今日 + 更早日期未完成可自由穿插；已完成置底；逾期任务带原始日期徽标。

  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">每日计划 · {date}</h2>
        <Button size="sm" variant="outline" onClick={() => setHistoryOpen(true)}>
          <History className="h-4 w-4" /> 历史
        </Button>
      </div>
      <div className="mb-3 flex gap-2">
        <Input
          placeholder="添加任务，回车确认"
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        <Select
          value={newType}
          onChange={(e) => setNewType(e.target.value as TaskType)}
          className="w-28 shrink-0 text-xs"
          aria-label="任务类型"
        >
          {TASK_TYPES.map((t) => (
            <option key={t} value={t}>
              {TASK_TYPE_LABELS[t]}
            </option>
          ))}
        </Select>
        <Button size="sm" onClick={submit} disabled={!newTitle.trim()}>
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      {loading ? (
        <div className="py-6 text-center text-sm text-neutral-400">加载中…</div>
      ) : tasks.length === 0 ? (
        <div className="py-6 text-center text-sm text-neutral-400">这一天还没有任务</div>
      ) : (
        <ul className="space-y-1">
          {tasks.map((task) => (
            <TaskRow key={task.id} task={task} date={date} />
          ))}
        </ul>
      )}
      <TaskHistoryDialog open={historyOpen} onOpenChange={setHistoryOpen} />
    </section>
  );
}

function TaskRow({ task, date }: { task: DailyTask; date: string }) {
  const updateTask = useUpdateTask(date);
  const deleteTask = useDeleteTask(date);
  const taskToMemo = useTaskToMemo(date);
  const qc = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);

  const toggleDone = () => {
    // 乐观更新：立即反映，失败回滚（完成/取消完成均可反复切换）
    const key = ["daily-tasks", date];
    const previous = qc.getQueryData<DailyTask[]>(key);
    qc.setQueryData<DailyTask[]>(key, (old) =>
      old?.map((t) => (t.id === task.id ? { ...t, done: !t.done } : t))
    );
    updateTask.mutate(
      { id: task.id, done: !task.done },
      { onError: () => qc.setQueryData(key, previous) }
    );
  };

  return (
    <li
      className={`flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-neutral-50 ${importantRowClass(task.is_important)}`}
    >
      <button
        onClick={toggleDone}
        aria-label={task.done ? "取消完成" : "标记完成"}
        title={task.done ? "取消完成（回到未完成列表）" : "标记完成"}
        className={`flex h-5 w-5 shrink-0 items-center justify-center rounded border ${
          task.done ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-300"
        }`}
      >
        {task.done && <Check className="h-3.5 w-3.5" />}
      </button>
      <StarButton
        important={task.is_important}
        onToggle={() => updateTask.mutate({ id: task.id, is_important: !task.is_important })}
      />
      <span
        className={`min-w-0 flex-1 text-sm ${importantTitleClass(task.is_important, task.done)}`}
        onDoubleClick={() => setEditOpen(true)}
      >
        <span className="break-words">{task.title}</span>
        <span className={`ml-2 rounded px-1.5 py-0.5 text-[11px] ${TASK_TYPE_BADGE_CLASS[task.task_type]}`}>
          {TASK_TYPE_LABELS[task.task_type]}
        </span>
        {task.task_date !== date && (
          <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-600">
            {task.task_date}
          </span>
        )}
        {task.task_date === date && task.moved_from_date && (
          <span className="ml-2 text-xs text-neutral-400" title="来自移入">
            ↳ {task.moved_from_date}
          </span>
        )}
        {task.content && (
          <span className="mt-0.5 block break-words text-xs font-normal text-neutral-400 line-clamp-2">
            {task.content}
          </span>
        )}
      </span>
      {!task.done && (
        <>
          <button
            onClick={() =>
              confirm(`将任务「${task.title}」转为随手备忘？任务将从列表中移除。`) &&
              taskToMemo.mutate(task.id)
            }
            aria-label="转为随手备忘"
            title="转为随手备忘"
            className="p-1 text-neutral-400 hover:text-green-600"
          >
            <NotebookPen className="h-4 w-4" />
          </button>
        </>
      )}
      <button onClick={() => setEditOpen(true)} aria-label="编辑" className="p-1 text-neutral-400 hover:text-neutral-700">
        <Pencil className="h-4 w-4" />
      </button>
      <button
        onClick={() => confirm(`删除任务「${task.title}」？`) && deleteTask.mutate(task.id)}
        aria-label="删除"
        className="p-1 text-neutral-400 hover:text-red-600"
      >
        <Trash2 className="h-4 w-4" />
      </button>

      <TaskEditDialog task={task} open={editOpen} onOpenChange={setEditOpen} />
    </li>
  );
}

/** 任务编辑弹窗：标题、内容/备注、任务类型、重要标记。 */
function TaskEditDialog({
  task,
  open,
  onOpenChange,
}: {
  task: DailyTask;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const updateTask = useUpdateTask(task.task_date);
  const [title, setTitle] = useState(task.title);
  const [content, setContent] = useState(task.content ?? "");
  const [taskType, setTaskType] = useState<TaskType>(task.task_type);
  const [isImportant, setIsImportant] = useState(task.is_important);

  // 打开时按当前任务重置
  const [prevOpen, setPrevOpen] = useState(false);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setTitle(task.title);
      setContent(task.content ?? "");
      setTaskType(task.task_type);
      setIsImportant(task.is_important);
    }
  }

  const submit = () => {
    const trimmed = title.trim();
    if (!trimmed) return;
    updateTask.mutate(
      { id: task.id, title: trimmed, content, task_type: taskType, is_important: isImportant },
      { onSuccess: () => onOpenChange(false) }
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>编辑任务</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>标题</Label>
            <Input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div>
            <Label>内容/备注</Label>
            <Textarea rows={3} value={content} onChange={(e) => setContent(e.target.value)} />
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
            <input
              type="checkbox"
              checked={isImportant}
              onChange={(e) => setIsImportant(e.target.checked)}
              className="accent-red-500"
            />
            标记为重要
          </label>
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

/** 每日计划历史：已完成任务（含完成时间、归属日期、重要状态），可按日期筛选。 */
function TaskHistoryDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const updateTask = useUpdateTask(todayStr());
  const [filterDate, setFilterDate] = useState("");
  const history = useTaskHistory(filterDate || null, open);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>每日计划 · 历史完成记录</DialogTitle>
        </DialogHeader>
        <div className="mb-3 flex items-center gap-2">
          <Label>按日期筛选</Label>
          <Input
            type="date"
            value={filterDate}
            onChange={(e) => setFilterDate(e.target.value)}
            className="w-40"
            aria-label="历史日期筛选"
          />
          {filterDate && (
            <Button size="sm" variant="outline" onClick={() => setFilterDate("")}>
              全部
            </Button>
          )}
        </div>
        {history.isLoading ? (
          <div className="py-6 text-center text-sm text-neutral-400">加载中…</div>
        ) : !history.data || history.data.length === 0 ? (
          <div className="py-6 text-center text-sm text-neutral-400">没有已完成的历史记录</div>
        ) : (
          <ul className="max-h-80 space-y-1 overflow-y-auto">
            {history.data.map((task) => (
              <li
                key={task.id}
                className={`flex items-center gap-2 rounded-md px-2 py-1.5 ${importantRowClass(task.is_important)}`}
              >
                <button
                  onClick={() => updateTask.mutate({ id: task.id, done: false })}
                  aria-label={`取消完成 ${task.title}`}
                  title="取消完成（回到未完成列表）"
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded border border-neutral-900 bg-neutral-900 text-white"
                >
                  <Check className="h-3.5 w-3.5" />
                </button>
                <Star
                  className={`h-3.5 w-3.5 shrink-0 ${task.is_important ? "text-red-500" : "text-neutral-200"}`}
                  fill={task.is_important ? "currentColor" : "none"}
                  aria-label={task.is_important ? "重要" : "普通"}
                />
                <span className="flex-1 break-words text-sm">{task.title}</span>
                <span className="text-xs text-neutral-400">所属 {task.task_date}</span>
                <span className="text-xs text-neutral-400">{completedAtLabel(task.completed_at)}</span>
              </li>
            ))}
          </ul>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PlansPanel({ plans }: { plans: Plan[] }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Plan | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const reorder = useReorderPlans();
  const planIds = plans.map((p) => p.id);

  const swap = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= planIds.length) return;
    const next = [...planIds];
    [next[index], next[target]] = [next[target], next[index]];
    reorder.mutate(next);
  };

  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">长期计划</h2>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setHistoryOpen(true)}>
            <History className="h-4 w-4" /> 历史
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setEditing(null);
              setOpen(true);
            }}
          >
            <Plus className="h-4 w-4" /> 新建
          </Button>
        </div>
      </div>
      {plans.length === 0 ? (
        <div className="py-6 text-center text-sm text-neutral-400">还没有长期计划</div>
      ) : (
        <ul className="space-y-2">
          {plans.map((plan, index) => (
            <PlanCard
              key={plan.id}
              plan={plan}
              canUp={index > 0}
              canDown={index < plans.length - 1}
              onMove={(direction) => swap(index, direction)}
              onEdit={() => {
                setEditing(plan);
                setOpen(true);
              }}
            />
          ))}
        </ul>
      )}
      <PlanDialog open={open} onOpenChange={setOpen} plan={editing} />
      <PlanHistoryDialog open={historyOpen} onOpenChange={setHistoryOpen} />
    </section>
  );
}

function PlanCard({
  plan,
  canUp,
  canDown,
  onMove,
  onEdit,
}: {
  plan: Plan;
  canUp: boolean;
  canDown: boolean;
  onMove: (direction: -1 | 1) => void;
  onEdit: () => void;
}) {
  const deletePlan = useDeletePlan();
  const updatePlan = useUpdatePlan();
  const completePlan = useCompletePlan();
  const [confirmOpen, setConfirmOpen] = useState(false);

  return (
    <li className={`rounded-md border border-neutral-200 p-3 ${importantRowClass(plan.is_important)}`}>
      <div className="flex items-center gap-2">
        <StarButton
          important={plan.is_important}
          onToggle={() => updatePlan.mutate({ id: plan.id, is_important: !plan.is_important })}
        />
        <span className={`flex-1 truncate text-sm font-medium ${plan.is_important ? "text-red-700" : ""}`}>
          {plan.title}
        </span>
        <button onClick={() => onMove(-1)} disabled={!canUp} aria-label="上移计划" className="p-1 text-neutral-400 hover:text-neutral-700 disabled:opacity-30">
          <ArrowUp className="h-4 w-4" />
        </button>
        <button onClick={() => onMove(1)} disabled={!canDown} aria-label="下移计划" className="p-1 text-neutral-400 hover:text-neutral-700 disabled:opacity-30">
          <ArrowDown className="h-4 w-4" />
        </button>
        <button
          onClick={() => setConfirmOpen(true)}
          aria-label="标记完成"
          className="p-1 text-neutral-400 hover:text-green-600"
        >
          <CheckCheck className="h-4 w-4" />
        </button>
        <button onClick={onEdit} aria-label="编辑计划" className="p-1 text-neutral-400 hover:text-neutral-700">
          <Pencil className="h-4 w-4" />
        </button>
        <button
          onClick={() =>
            confirm(`删除长期计划「${plan.title}」？其每日任务将保留并解除关联。`) &&
            deletePlan.mutate(plan.id)
          }
          aria-label="删除计划"
          className="p-1 text-neutral-400 hover:text-red-600"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-1 space-y-0.5 pl-6 text-xs text-neutral-400">
        {plan.target_date && <div>目标 {plan.target_date}</div>}
        {plan.description && <div>{plan.description}</div>}
        {plan.goal && <div className="whitespace-pre-wrap text-neutral-500">具体目标：{plan.goal}</div>}
      </div>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>标记完成</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-neutral-600">确认将该长期计划标记为已完成吗？完成后将移入历史计划。</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              取消
            </Button>
            <Button
              onClick={() =>
                completePlan.mutate(plan.id, { onSuccess: () => setConfirmOpen(false) })
              }
            >
              确认完成
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  );
}

/** 长期计划历史：已完成的计划（完成时间未知显示"完成时间未知"），可删除。 */
function PlanHistoryDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const deletePlan = useDeletePlan();
  const history = usePlanHistory(open);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>长期计划 · 历史</DialogTitle>
        </DialogHeader>
        {history.isLoading ? (
          <div className="py-6 text-center text-sm text-neutral-400">加载中…</div>
        ) : !history.data || history.data.length === 0 ? (
          <div className="py-6 text-center text-sm text-neutral-400">还没有历史计划</div>
        ) : (
          <ul className="max-h-80 space-y-1 overflow-y-auto">
            {history.data.map((plan) => (
              <li
                key={plan.id}
                className={`flex items-center gap-2 rounded-md border border-neutral-100 px-2 py-1.5 ${importantRowClass(plan.is_important)}`}
              >
                <Star
                  className={`h-3.5 w-3.5 shrink-0 ${plan.is_important ? "text-red-500" : "text-neutral-200"}`}
                  fill={plan.is_important ? "currentColor" : "none"}
                  aria-label={plan.is_important ? "重要" : "普通"}
                />
                <div className="min-w-0 flex-1">
                  <div className={`truncate text-sm ${plan.is_important ? "text-red-700" : ""}`}>
                    {plan.title}
                  </div>
                  <div className="text-xs text-neutral-400">
                    完成于 {completedAtLabel(plan.completed_at)} · 创建于 {plan.created_at?.slice(0, 10) ?? "未知"}
                    {plan.description && ` · ${plan.description}`}
                    {plan.goal && (
                      <div className="mt-0.5 whitespace-pre-wrap text-neutral-500">具体目标：{plan.goal}</div>
                    )}
                  </div>
                </div>
                <button
                  onClick={() =>
                    confirm(`删除历史计划「${plan.title}」？关联的每日任务将保留并解除关联。`) &&
                    deletePlan.mutate(plan.id)
                  }
                  aria-label="删除历史计划"
                  className="p-1 text-neutral-400 hover:text-red-600"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PlanDialog({
  open,
  onOpenChange,
  plan,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  plan: Plan | null;
}) {
  const createPlan = useCreatePlan();
  const updatePlan = useUpdatePlan();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [goal, setGoal] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [isImportant, setIsImportant] = useState(false);

  // 打开时按新建/编辑对象重置表单
  useEffect(() => {
    if (open) {
      setTitle(plan?.title ?? "");
      setDescription(plan?.description ?? "");
      setGoal(plan?.goal ?? "");
      setTargetDate(plan?.target_date ?? "");
      setIsImportant(plan?.is_important ?? false);
    }
  }, [open, plan]);

  const submit = () => {
    const body = {
      title: title.trim(),
      description,
      goal: goal.trim() || null,
      target_date: targetDate || null,
      is_important: isImportant,
    };
    if (!body.title) return;
    const mutation = plan ? updatePlan : createPlan;
    const payload = plan ? { id: plan.id, ...body } : body;
    mutation.mutate(payload as never, { onSuccess: () => onOpenChange(false) });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{plan ? "编辑长期计划" : "新建长期计划"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>标题</Label>
            <Input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div>
            <Label>描述</Label>
            <Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div>
            <Label>具体目标（可选）</Label>
            <Textarea rows={2} value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="例如：每天阅读 20 分钟英文文章" />
          </div>
          <div>
            <Label>目标日期（可选）</Label>
            <Input type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={isImportant}
              onChange={(e) => setIsImportant(e.target.checked)}
              className="accent-red-500"
            />
            <Star
              className={`h-4 w-4 ${isImportant ? "text-red-500" : "text-neutral-300"}`}
              fill={isImportant ? "currentColor" : "none"}
            />
            标记为重要（置顶显示）
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={submit} disabled={!title.trim()}>
            <CalendarPlus className="h-4 w-4" /> 保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
