import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  CalendarPlus,
  Check,
  CheckCheck,
  CornerDownRight,
  History,
  Pencil,
  Plus,
  Star,
  Trash2,
} from "lucide-react";

import { Button } from "../components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { Input, Label, Textarea } from "../components/ui/input";
import { todayStr } from "../lib/api";
import {
  DailyTask,
  Plan,
  useCompletePlan,
  useCreatePlan,
  useCreateTask,
  useDailyTasks,
  useDeletePlan,
  useDeleteTask,
  useMoveTask,
  usePlanHistory,
  usePlans,
  useReorderPlans,
  useReorderTasks,
  useTaskHistory,
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

/** 重要行红色强调：浅红背景 + 左侧红色标识 + 红色标题。 */
function importantRowClass(isImportant: boolean): string {
  return isImportant ? "border-l-2 border-red-400 bg-red-50/60" : "border-l-2 border-transparent";
}

function importantTitleClass(isImportant: boolean, done: boolean): string {
  if (done) return "text-neutral-400 line-through";
  return isImportant ? "text-red-700" : "text-neutral-900";
}

function StarButton({
  important,
  onToggle,
}: {
  important: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      aria-label={important ? "取消重要" : "标记重要"}
      className={`p-1 ${important ? "text-red-500" : "text-neutral-300 hover:text-red-400"}`}
    >
      <Star className="h-4 w-4" fill={important ? "currentColor" : "none"} />
    </button>
  );
}

export function PlansPage() {
  const [date, setDate] = useState(todayStr());
  const { data: tasks = [], isLoading } = useDailyTasks(date);
  const { data: plans = [] } = usePlans();

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">计划管理</h1>
      <DateBar date={date} onChange={setDate} />
      <div className="grid gap-4 lg:grid-cols-2">
        <DailyPanel date={date} tasks={tasks} loading={isLoading} />
        <PlansPanel plans={plans} />
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
  const [historyOpen, setHistoryOpen] = useState(false);

  const submit = () => {
    const title = newTitle.trim();
    if (!title) return;
    createTask.mutate({ title }, { onSuccess: () => setNewTitle("") });
  };

  // 未完成任务自归属日期起持续显示；已完成任务只在归属日期显示。
  // 重要任务整体置顶（后端已按 重要>sort_order 排序，前端按分区切分保持顺序一致）。
  const overdue = tasks.filter((t) => t.task_date < date && !t.done);
  const todayTasks = tasks.filter((t) => t.task_date === date);
  const overdueIds = overdue.map((t) => t.id);
  const todayIds = todayTasks.map((t) => t.id);

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
        <Button size="sm" onClick={submit} disabled={!newTitle.trim()}>
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      {loading ? (
        <div className="py-6 text-center text-sm text-neutral-400">加载中…</div>
      ) : tasks.length === 0 ? (
        <div className="py-6 text-center text-sm text-neutral-400">这一天还没有任务</div>
      ) : (
        <>
          {overdue.length > 0 && (
            <>
              <div className="mb-1 px-2 text-xs font-medium text-neutral-400">未完成 · 来自更早日期</div>
              <ul className="mb-3 space-y-1">
                {overdue.map((task, index) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    date={date}
                    overdue
                    scope="overdue"
                    canUp={index > 0}
                    canDown={index < overdue.length - 1}
                    allIds={overdueIds}
                  />
                ))}
              </ul>
            </>
          )}
          <ul className="space-y-1">
            {todayTasks.map((task, index) => (
              <TaskRow
                key={task.id}
                task={task}
                date={date}
                scope="today"
                canUp={index > 0}
                canDown={index < todayTasks.length - 1}
                allIds={todayIds}
              />
            ))}
          </ul>
        </>
      )}
      <TaskHistoryDialog open={historyOpen} onOpenChange={setHistoryOpen} />
    </section>
  );
}

function TaskRow({
  task,
  date,
  overdue = false,
  scope,
  canUp,
  canDown,
  allIds,
}: {
  task: DailyTask;
  date: string;
  overdue?: boolean;
  scope: "today" | "overdue";
  canUp: boolean;
  canDown: boolean;
  allIds: number[];
}) {
  const updateTask = useUpdateTask(date);
  const deleteTask = useDeleteTask(date);
  const moveTask = useMoveTask(date);
  const reorder = useReorderTasks(date, scope);
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(task.title);
  const [moveOpen, setMoveOpen] = useState(false);
  const [moveDate, setMoveDate] = useState(todayStr(1));

  const toggleDone = () => {
    // 乐观更新：立即反映，失败回滚（TanStack Query 模式）
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

  const swap = (direction: -1 | 1) => {
    const index = allIds.indexOf(task.id);
    const target = index + direction;
    if (target < 0 || target >= allIds.length) return;
    const next = [...allIds];
    [next[index], next[target]] = [next[target], next[index]];
    reorder.mutate(next);
  };

  return (
    <li
      className={`flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-neutral-50 ${importantRowClass(task.is_important)}`}
    >
      <button
        onClick={toggleDone}
        aria-label={task.done ? "标记未完成" : "标记完成"}
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
      {editing ? (
        <form
          className="flex flex-1 gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            const title = draft.trim();
            if (title) updateTask.mutate({ id: task.id, title }, { onSuccess: () => setEditing(false) });
          }}
        >
          <Input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} />
          <Button size="sm" type="submit">
            保存
          </Button>
        </form>
      ) : (
        <>
          <span
            className={`flex-1 text-sm ${importantTitleClass(task.is_important, task.done)}`}
            onDoubleClick={() => {
              setDraft(task.title);
              setEditing(true);
            }}
          >
            {task.title}
            {overdue ? (
              <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-600">
                {task.task_date}
              </span>
            ) : (
              task.moved_from_date && (
                <span className="ml-2 text-xs text-neutral-400" title="来自移入">
                  ↳ {task.moved_from_date}
                </span>
              )
            )}
          </span>
          <button onClick={() => swap(-1)} disabled={!canUp} aria-label="上移" className="p-1 text-neutral-400 hover:text-neutral-700 disabled:opacity-30">
            <ArrowUp className="h-4 w-4" />
          </button>
          <button onClick={() => swap(1)} disabled={!canDown} aria-label="下移" className="p-1 text-neutral-400 hover:text-neutral-700 disabled:opacity-30">
            <ArrowDown className="h-4 w-4" />
          </button>
          <button
            onClick={() => {
              setMoveDate(todayStr(1));
              setMoveOpen(true);
            }}
            aria-label="移至其他日期"
            className="p-1 text-neutral-400 hover:text-neutral-700"
          >
            <CornerDownRight className="h-4 w-4" />
          </button>
          <button
            onClick={() => {
              setDraft(task.title);
              setEditing(true);
            }}
            aria-label="编辑"
            className="p-1 text-neutral-400 hover:text-neutral-700"
          >
            <Pencil className="h-4 w-4" />
          </button>
          <button
            onClick={() => confirm(`删除任务「${task.title}」？`) && deleteTask.mutate(task.id)}
            aria-label="删除"
            className="p-1 text-neutral-400 hover:text-red-600"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </>
      )}

      <Dialog open={moveOpen} onOpenChange={setMoveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>移动「{task.title}」</DialogTitle>
          </DialogHeader>
          <Label>目标日期</Label>
          <Input type="date" value={moveDate} onChange={(e) => setMoveDate(e.target.value)} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setMoveOpen(false)}>
              取消
            </Button>
            <Button
              onClick={() =>
                moveTask.mutate(
                  { id: task.id, target_date: moveDate },
                  { onSuccess: () => setMoveOpen(false) }
                )
              }
            >
              移动
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
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
                <Star
                  className={`h-3.5 w-3.5 shrink-0 ${task.is_important ? "text-red-500" : "text-neutral-200"}`}
                  fill={task.is_important ? "currentColor" : "none"}
                  aria-label={task.is_important ? "重要" : "普通"}
                />
                <span className="flex-1 text-sm">{task.title}</span>
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
      <div className="mt-1 pl-6 text-xs text-neutral-400">
        {plan.target_date ? `目标 ${plan.target_date}` : "未设目标日期"}
        {plan.description && ` · ${plan.description}`}
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
  const [targetDate, setTargetDate] = useState("");
  const [isImportant, setIsImportant] = useState(false);

  // 打开时按新建/编辑对象重置表单
  useEffect(() => {
    if (open) {
      setTitle(plan?.title ?? "");
      setDescription(plan?.description ?? "");
      setTargetDate(plan?.target_date ?? "");
      setIsImportant(plan?.is_important ?? false);
    }
  }, [open, plan]);

  const submit = () => {
    const body = {
      title: title.trim(),
      description,
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
