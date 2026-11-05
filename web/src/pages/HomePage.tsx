import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { MessageSquareText } from "lucide-react";

import { api, todayStr } from "../lib/api";
import { DailyTask } from "../api/plans";
import { BOOK_STATUS_LABELS, Book } from "../api/reading";
import { useNewsTop } from "../api/news";
import { TopNewsList } from "../components/news/TopNewsList";
import { CleanupBanner } from "./CleanupPage";
import { Button } from "../components/ui/button";

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
  const news = useNewsTop();

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">首页工作台</h1>
        <Button asChild size="sm">
          <Link to="/wechat">
            <MessageSquareText className="h-4 w-4" /> 微信总结
          </Link>
        </Button>
      </div>
      <CleanupBanner />
      <div className="rounded-lg border border-neutral-200 bg-white p-4 text-sm">
        <div className="font-medium">后端服务状态</div>
        <div className="mt-1 text-neutral-600">
          {health.isLoading && "检查中…"}
          {health.isError && "后端未连接（请先启动服务）"}
          {health.data && `已连接 · ${health.data.service} v${health.data.version}`}
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <TodayPlanCard tasks={tasks.data} loading={tasks.isLoading} error={tasks.isError} />
        <ReadingCard books={reading.data} loading={reading.isLoading} error={reading.isError} />
      </div>
      <section className="rounded-lg border border-neutral-200 bg-white p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold">近期热门资讯 TOP 10</h2>
          <Link to="/news" className="text-xs text-neutral-400 hover:text-neutral-700">
            查看资讯导航 →
          </Link>
        </div>
        <TopNewsList items={news.data?.items} loading={news.isLoading} error={news.isError} />
      </section>
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
  const today = todayStr();
  // X/Y 统计口径 = 计划管理"今天"视图中看到的全部任务（当日 + 更早日期未完成）
  const total = tasks?.length ?? 0;
  const doneCount = tasks?.filter((t) => t.done).length ?? 0;
  // 只展示未完成的重要任务（按计划管理排序展示，逾期带日期徽标）
  const importantPending = tasks?.filter((t) => !t.done && t.is_important) ?? [];

  return (
    <Link
      to="/plans"
      className="block rounded-lg border border-neutral-200 bg-white p-4 transition-shadow hover:shadow-sm"
    >
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">计划管理</div>
        <span className="text-xs text-neutral-400">查看全部 →</span>
      </div>
      <div className="mt-2 text-xs font-medium text-neutral-600">今日计划</div>
      <div className="mt-0.5 text-xs text-neutral-500">
        {loading && "加载中…"}
        {error && "后端未连接"}
        {!loading && !error && `${doneCount}/${total} 已完成`}
      </div>
      {!loading && !error && importantPending.length > 0 && (
        <ul className="mt-2 space-y-1">
          {importantPending.map((task) => (
            <li key={task.id} className="flex items-center gap-1 text-xs">
              <span className="min-w-0 flex-1 truncate text-red-700">· {task.title}</span>
              {task.task_date !== today && (
                <span className="shrink-0 rounded bg-amber-50 px-1 py-0.5 text-[10px] text-amber-600">
                  {task.task_date}
                </span>
              )}
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
      className="block rounded-lg border border-neutral-200 bg-white p-4 transition-shadow hover:shadow-sm"
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
