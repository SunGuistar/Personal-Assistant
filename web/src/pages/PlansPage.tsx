import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  CalendarPlus,
  Check,
  CornerDownRight,
  Pencil,
  Plus,
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
import { Input, Label, Select, Textarea } from "../components/ui/input";
import { todayStr } from "../lib/api";
import {
  DailyTask,
  Plan,
  useCreatePlan,
  useCreateTask,
  useDailyTasks,
  useDeletePlan,
  useDeleteTask,
  useMoveTask,
  usePlans,
  useReorderTasks,
  useUpdatePlan,
  useUpdateTask,
} from "../api/plans";

const PLAN_STATUS_LABELS: Record<string, string> = {
  in_progress: "进行中",
  completed: "已完成",
  on_hold: "已搁置",
};

function dateLabel(date: string): string {
  const today = todayStr();
  const tomorrow = todayStr(1);
  const yesterday = todayStr(-1);
  if (date === today) return "今天";
  if (date === tomorrow) return "明天";
  if (date === yesterday) return "昨天";
  return date;
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
        <DailyPanel date={date} tasks={tasks} loading={isLoading} plans={plans} />
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
  plans,
}: {
  date: string;
  tasks: DailyTask[];
  loading: boolean;
  plans: Plan[];
}) {
  const createTask = useCreateTask(date);
  const [newTitle, setNewTitle] = useState("");
  const [newPlanId, setNewPlanId] = useState<string>("");

  const submit = () => {
    const title = newTitle.trim();
    if (!title) return;
    createTask.mutate(
      { title, plan_id: newPlanId ? Number(newPlanId) : null },
      { onSuccess: () => setNewTitle("") }
    );
  };

  // 未完成任务自归属日期起持续显示；已完成任务只在归属日期显示
  const overdue = tasks.filter((t) => t.task_date < date && !t.done);
  const todayTasks = tasks.filter((t) => t.task_date === date);
  const todayIds = todayTasks.map((t) => t.id);

  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-4">
      <h2 className="mb-3 text-sm font-semibold">每日计划 · {date}</h2>
      <div className="mb-3 flex gap-2">
        <Input
          placeholder="添加任务，回车确认"
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        <Select
          value={newPlanId}
          onChange={(e) => setNewPlanId(e.target.value)}
          className="w-32 shrink-0"
          aria-label="关联长期计划"
        >
          <option value="">无关联</option>
          {plans.map((plan) => (
            <option key={plan.id} value={plan.id}>
              {plan.title}
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
        <>
          {overdue.length > 0 && (
            <>
              <div className="mb-1 px-2 text-xs font-medium text-neutral-400">未完成 · 来自更早日期</div>
              <ul className="mb-3 space-y-1">
                {overdue.map((task) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    date={date}
                    plans={plans}
                    overdue
                    canUp={false}
                    canDown={false}
                    allIds={[]}
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
                plans={plans}
                canUp={index > 0}
                canDown={index < todayTasks.length - 1}
                allIds={todayIds}
              />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function TaskRow({
  task,
  date,
  plans,
  overdue = false,
  canUp,
  canDown,
  allIds,
}: {
  task: DailyTask;
  date: string;
  plans: Plan[];
  overdue?: boolean;
  canUp: boolean;
  canDown: boolean;
  allIds: number[];
}) {
  const updateTask = useUpdateTask(date);
  const deleteTask = useDeleteTask(date);
  const moveTask = useMoveTask(date);
  const reorder = useReorderTasks(date);
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

  const plan = plans.find((p) => p.id === task.plan_id);

  return (
    <li className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-neutral-50">
      <button
        onClick={toggleDone}
        aria-label={task.done ? "标记未完成" : "标记完成"}
        className={`flex h-5 w-5 shrink-0 items-center justify-center rounded border ${
          task.done ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-300"
        }`}
      >
        {task.done && <Check className="h-3.5 w-3.5" />}
      </button>
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
            className={`flex-1 text-sm ${task.done ? "text-neutral-400 line-through" : ""}`}
            onDoubleClick={() => {
              setDraft(task.title);
              setEditing(true);
            }}
          >
            {task.title}
            {plan && (
              <span className="ml-2 rounded bg-neutral-100 px-1.5 py-0.5 text-xs text-neutral-500">
                {plan.title}
              </span>
            )}
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
          {!overdue && (
            <>
              <button onClick={() => swap(-1)} disabled={!canUp} aria-label="上移" className="p-1 text-neutral-400 hover:text-neutral-700 disabled:opacity-30">
                <ArrowUp className="h-4 w-4" />
              </button>
              <button onClick={() => swap(1)} disabled={!canDown} aria-label="下移" className="p-1 text-neutral-400 hover:text-neutral-700 disabled:opacity-30">
                <ArrowDown className="h-4 w-4" />
              </button>
            </>
          )}
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

function PlansPanel({ plans }: { plans: Plan[] }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Plan | null>(null);

  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">长期计划</h2>
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
      {plans.length === 0 ? (
        <div className="py-6 text-center text-sm text-neutral-400">还没有长期计划</div>
      ) : (
        <ul className="space-y-2">
          {plans.map((plan) => (
            <PlanCard key={plan.id} plan={plan} onEdit={() => { setEditing(plan); setOpen(true); }} />
          ))}
        </ul>
      )}
      <PlanDialog open={open} onOpenChange={setOpen} plan={editing} />
    </section>
  );
}

function PlanCard({ plan, onEdit }: { plan: Plan; onEdit: () => void }) {
  const deletePlan = useDeletePlan();
  const updatePlan = useUpdatePlan();

  return (
    <li className="rounded-md border border-neutral-200 p-3">
      <div className="flex items-center gap-2">
        <span className="flex-1 truncate text-sm font-medium">{plan.title}</span>
        <Select
          value={plan.status}
          onChange={(e) => updatePlan.mutate({ id: plan.id, status: e.target.value })}
          className="h-7 w-24 text-xs"
          aria-label="计划状态"
        >
          {Object.entries(PLAN_STATUS_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
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
      <div className="mt-1 text-xs text-neutral-400">
        {plan.target_date ? `目标 ${plan.target_date}` : "未设目标日期"}
        {plan.description && ` · ${plan.description}`}
      </div>
    </li>
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
  const [status, setStatus] = useState("in_progress");
  const [targetDate, setTargetDate] = useState("");

  // 打开时按新建/编辑对象重置表单
  useEffect(() => {
    if (open) {
      setTitle(plan?.title ?? "");
      setDescription(plan?.description ?? "");
      setStatus(plan?.status ?? "in_progress");
      setTargetDate(plan?.target_date ?? "");
    }
  }, [open, plan]);

  const submit = () => {
    const body = {
      title: title.trim(),
      description,
      status,
      target_date: targetDate || null,
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
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>状态</Label>
              <Select value={status} onChange={(e) => setStatus(e.target.value)}>
                {Object.entries(PLAN_STATUS_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label>目标日期（可选）</Label>
              <Input type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} />
            </div>
          </div>
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
