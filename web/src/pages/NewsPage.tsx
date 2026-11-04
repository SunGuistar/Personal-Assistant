import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, RefreshCw, Star } from "lucide-react";

import { Button } from "../components/ui/button";
import { Select } from "../components/ui/input";
import { todayStr } from "../lib/api";
import {
  NewsItem,
  useNewsItems,
  useNewsJob,
  useNewsSources,
  useNewsStatus,
  useRefreshNews,
  useUpdateNewsItem,
} from "../api/news";

export const TOPIC_LABELS: Record<string, string> = {
  ai: "AI 大模型",
  agent: "AI Agent",
  ai_coding: "AI 编程",
  python: "Python",
  typescript: "TypeScript",
  engineering: "软件工程",
  opensource: "开源项目",
  other: "其他",
};

const TIME_RANGES = [
  { value: "", label: "全部时间" },
  { value: "1", label: "最近 1 天" },
  { value: "3", label: "最近 3 天" },
  { value: "7", label: "最近 7 天" },
];

function sinceFromRange(range: string): string | undefined {
  if (!range) return undefined;
  return todayStr(-Number(range));
}

function relativeTime(iso: string): string {
  const then = new Date(iso);
  const diffMinutes = Math.max(Math.floor((Date.now() - then.getTime()) / 60000), 0);
  if (diffMinutes < 60) return `${diffMinutes} 分钟前`;
  if (diffMinutes < 60 * 24) return `${Math.floor(diffMinutes / 60)} 小时前`;
  return `${Math.floor(diffMinutes / (60 * 24))} 天前`;
}

export function NewsPage() {
  const [topic, setTopic] = useState("");
  const [source, setSource] = useState("");
  const [range, setRange] = useState("3");
  const [sort, setSort] = useState<"latest" | "top">("top");
  const [taskId, setTaskId] = useState<number | null>(null);
  const qc = useQueryClient();

  const items = useNewsItems({
    page: 1,
    page_size: 50,
    topic: topic || undefined,
    source: source || undefined,
    sort,
    since: sinceFromRange(range),
  });
  const sources = useNewsSources();
  const status = useNewsStatus();
  const refresh = useRefreshNews();
  const job = useNewsJob(taskId);

  // 进入页面时：数据不新鲜则自动触发一次刷新（后台任务，不阻塞列表）
  useEffect(() => {
    if (status.data?.stale && taskId === null && !refresh.isPending) {
      refresh.mutate(undefined, { onSuccess: (data) => setTaskId(data.task_id) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status.data?.stale]);

  useEffect(() => {
    if (job.data && ["success", "failed"].includes(job.data.status)) {
      setTaskId(null);
      qc.invalidateQueries({ queryKey: ["news-items"] });
      qc.invalidateQueries({ queryKey: ["news-status"] });
    }
  }, [job.data, qc]);

  const refreshing = refresh.isPending || taskId !== null || job.data?.status === "running";
  const lastFailures = status.data?.last_refresh?.failures ?? [];
  const lastRefreshAt = status.data?.last_refresh?.refreshed_at;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">技术资讯</h1>
        <Button size="sm" onClick={() => refresh.mutate(undefined, { onSuccess: (d) => setTaskId(d.task_id) })} disabled={refreshing}>
          <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} /> {refreshing ? "刷新中…" : "刷新"}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Select value={topic} onChange={(e) => setTopic(e.target.value)} className="w-32" aria-label="主题筛选">
          <option value="">全部主题</option>
          {Object.entries(TOPIC_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </Select>
        <Select value={source} onChange={(e) => setSource(e.target.value)} className="w-40" aria-label="来源筛选">
          <option value="">全部来源</option>
          {(sources.data ?? []).filter((s) => s.enabled).map((s) => (
            <option key={s.id} value={s.name}>{s.name}</option>
          ))}
        </Select>
        <Select value={range} onChange={(e) => setRange(e.target.value)} className="w-32" aria-label="时间范围">
          {TIME_RANGES.map(({ value, label }) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </Select>
        <div className="flex rounded-md border border-neutral-300">
          {(["top", "latest"] as const).map((value) => (
            <button
              key={value}
              onClick={() => setSort(value)}
              className={`px-3 py-1.5 text-xs ${sort === value ? "bg-neutral-900 text-neutral-50" : "bg-white text-neutral-600"}`}
            >
              {value === "top" ? "综合热度" : "最新"}
            </button>
          ))}
        </div>
        <span className="text-xs text-neutral-400">
          {lastRefreshAt ? `上次更新 ${relativeTime(lastRefreshAt)}` : "尚未成功刷新"}
        </span>
      </div>

      {job.data?.status === "failed" && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          刷新失败：{job.data.error ?? "未知错误"}
        </div>
      )}
      {lastFailures.length > 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700">
          部分来源刷新失败：{lastFailures.map((f) => `${f.source}（${f.error}）`).join("；")}
        </div>
      )}

      {items.isLoading ? (
        <div className="py-10 text-center text-sm text-neutral-400">加载中…</div>
      ) : items.isError ? (
        <div className="py-10 text-center text-sm text-red-600">后端未连接，请确认服务已启动</div>
      ) : items.data && items.data.items.length > 0 ? (
        <ul className="space-y-2">
          {items.data.items.map((item) => (
            <NewsRow key={item.id} item={item} />
          ))}
        </ul>
      ) : (
        <div className="py-10 text-center text-sm text-neutral-400">
          暂无资讯{refreshing ? "，正在抓取…" : "，可点击右上角刷新"}
        </div>
      )}
    </div>
  );
}

function NewsRow({ item }: { item: NewsItem }) {
  const update = useUpdateNewsItem();

  const openLink = () => {
    window.open(item.url, "_blank", "noopener");
    if (!item.is_read) update.mutate({ id: item.id, is_read: true });
  };

  return (
    <li className={`rounded-lg border border-neutral-200 bg-white p-3 ${item.is_read ? "opacity-70" : ""}`}>
      <div className="flex items-start gap-2">
        <button
          onClick={() => update.mutate({ id: item.id, is_favorite: !item.is_favorite })}
          aria-label={item.is_favorite ? "取消收藏" : "收藏"}
          className="mt-0.5 p-1 text-neutral-300 hover:text-amber-500"
        >
          <Star className={`h-4 w-4 ${item.is_favorite ? "fill-amber-400 text-amber-400" : ""}`} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <button onClick={openLink} className="truncate text-left text-sm font-medium text-neutral-900 hover:underline">
              {item.title}
            </button>
            <ExternalLink className="h-3 w-3 shrink-0 text-neutral-300" />
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-neutral-400">
            <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-neutral-500">{item.source}</span>
            <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-neutral-500">{TOPIC_LABELS[item.topic] ?? item.topic}</span>
            <span>{relativeTime(item.published_at)}</span>
            <span>热度 {item.score.toFixed(2)}</span>
            {!item.is_read ? (
              <button onClick={() => update.mutate({ id: item.id, is_read: true })} className="text-neutral-400 hover:text-neutral-700">
                标记已读
              </button>
            ) : (
              <button onClick={() => update.mutate({ id: item.id, is_read: false })} className="text-neutral-400 hover:text-neutral-700">
                标记未读
              </button>
            )}
          </div>
          {item.raw_summary && (
            <p className="mt-1 line-clamp-2 text-xs text-neutral-500">{item.raw_summary}</p>
          )}
        </div>
      </div>
    </li>
  );
}
