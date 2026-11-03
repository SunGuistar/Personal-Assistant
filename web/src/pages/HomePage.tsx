import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api, todayStr } from "../lib/api";
import { DailyTask } from "../api/plans";
import { BOOK_STATUS_LABELS, Book } from "../api/reading";

type HealthResponse = { status: string; service: string; version: string };

async function fetchHealth(): Promise<HealthResponse> {
  return api<HealthResponse>("/health");
}

function useTodayTasks() {
  return useQuery({
    queryKey: ["daily-tasks", todayStr()],
    queryFn: () => api<DailyTask[]>(`/tasks/daily?date=${todayStr()}`),
    retry: 1,
  });
}

function useReadingBooks() {
  return useQuery({
    queryKey: ["books", "reading"],
    queryFn: () => api<Book[]>("/books?status=reading"),
    retry: 1,
  });
}

export function HomePage() {
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, retry: 1 });
  const tasks = useTodayTasks();
  const reading = useReadingBooks();

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">首页工作台</h1>
      <div className="rounded-lg border border-neutral-200 bg-white p-4 text-sm">
        <div className="font-medium">后端服务状态</div>
        <div className="mt-1 text-neutral-600">
          {health.isLoading && "检查中…"}
          {health.isError && "后端未连接（请先启动服务）"}
          {health.data && `已连接 · ${health.data.service} v${health.data.version}`}
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <TodayPlanCard tasks={tasks.data} loading={tasks.isLoading} error={tasks.isError} />
        <ReadingCard books={reading.data} loading={reading.isLoading} error={reading.isError} />
        <PlaceholderCard title="最新资讯" note="阶段 4 起接入" to="/news" />
        <PlaceholderCard title="微信总结" note="阶段 3 起接入" to="/wechat" />
      </div>
    </div>
  );
}

function TodayPlanCard({
  tasks,
  loading,
  error,
}: {
  tasks?: DailyTask[];
  loading: boolean;
  error: boolean;
}) {
  const done = tasks?.filter((t) => t.done).length ?? 0;
  return (
    <Link
      to="/plans"
      className="rounded-lg border border-neutral-200 bg-white p-4 transition-shadow hover:shadow-sm"
    >
      <div className="text-sm font-medium">今日计划</div>
      <div className="mt-1 text-xs text-neutral-500">
        {loading && "加载中…"}
        {error && "后端未连接"}
        {!loading && !error && (tasks?.length ? `${done} / ${tasks.length} 已完成` : "今天还没有任务")}
      </div>
      {!loading && !error && tasks && tasks.length > 0 && (
        <ul className="mt-2 space-y-1">
          {tasks.slice(0, 4).map((task) => (
            <li key={task.id} className={`truncate text-xs ${task.done ? "text-neutral-400 line-through" : "text-neutral-600"}`}>
              · {task.title}
            </li>
          ))}
        </ul>
      )}
    </Link>
  );
}

function ReadingCard({
  books,
  loading,
  error,
}: {
  books?: Book[];
  loading: boolean;
  error: boolean;
}) {
  return (
    <Link
      to="/reading"
      className="rounded-lg border border-neutral-200 bg-white p-4 transition-shadow hover:shadow-sm"
    >
      <div className="text-sm font-medium">正在阅读</div>
      <div className="mt-1 text-xs text-neutral-500">
        {loading && "加载中…"}
        {error && "后端未连接"}
        {!loading && !error && (books?.length ? `${books.length} 本在读` : "没有在读的书")}
      </div>
      {!loading && !error && books && books.length > 0 && (
        <ul className="mt-2 space-y-1">
          {books.slice(0, 4).map((book) => (
            <li key={book.id} className="truncate text-xs text-neutral-600">
              · {book.title}
              <span className="ml-1 text-neutral-400">（{BOOK_STATUS_LABELS[book.status]}）</span>
            </li>
          ))}
        </ul>
      )}
    </Link>
  );
}

function PlaceholderCard({ title, note, to }: { title: string; note: string; to: string }) {
  return (
    <Link
      to={to}
      className="rounded-lg border border-dashed border-neutral-300 bg-white p-4 transition-shadow hover:shadow-sm"
    >
      <div className="text-sm font-medium text-neutral-700">{title}</div>
      <div className="mt-1 text-xs text-neutral-400">{note}</div>
    </Link>
  );
}
