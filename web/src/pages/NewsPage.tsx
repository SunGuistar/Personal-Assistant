import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Globe, RefreshCw } from "lucide-react";

import { Button } from "../components/ui/button";
import { TopNewsList, relativeTime } from "../components/news/TopNewsList";
import { NEWS_NAV_SITES } from "../lib/newsNav";
import { useNewsJob, useNewsStatus, useNewsTop, useRefreshNews } from "../api/news";

function SiteIcon({ url, name }: { url: string; name: string }) {
  const [failed, setFailed] = useState(false);
  const domain = new URL(url).hostname;
  if (failed) {
    return (
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-neutral-900 text-sm font-semibold text-neutral-50">
        {name.slice(0, 1).toUpperCase()}
      </div>
    );
  }
  return (
    <img
      src={`https://${domain}/favicon.ico`}
      alt=""
      aria-hidden
      onError={() => setFailed(true)}
      className="h-10 w-10 shrink-0 rounded-md border border-neutral-200 bg-white object-contain p-1"
    />
  );
}

export function NewsPage() {
  const top = useNewsTop();
  const status = useNewsStatus();
  const refresh = useRefreshNews();
  const [taskId, setTaskId] = useState<number | null>(null);
  const job = useNewsJob(taskId);
  const qc = useQueryClient();

  // 进入页面时：缓存不新鲜则自动触发一次刷新（后台任务，不阻塞榜单展示）
  useEffect(() => {
    if (status.data?.stale && taskId === null && !refresh.isPending) {
      refresh.mutate(undefined, { onSuccess: (data) => setTaskId(data.task_id) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status.data?.stale]);

  useEffect(() => {
    if (job.data && ["success", "failed"].includes(job.data.status)) {
      setTaskId(null);
      qc.invalidateQueries({ queryKey: ["news-top"] });
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
        <Button
          size="sm"
          onClick={() => refresh.mutate(undefined, { onSuccess: (d) => setTaskId(d.task_id) })}
          disabled={refreshing}
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} /> {refreshing ? "刷新中…" : "刷新"}
        </Button>
      </div>

      <section className="rounded-lg border border-neutral-200 bg-white p-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">近期热门资讯 TOP 10</h2>
          <span className="text-xs text-neutral-400">
            {lastRefreshAt ? `上次成功更新 ${relativeTime(lastRefreshAt)}` : "尚未成功刷新"}
          </span>
        </div>
        {job.data?.status === "failed" && (
          <div className="mb-2 rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700">
            刷新失败：{job.data.error ?? "未知错误"}（展示已有缓存）
          </div>
        )}
        {lastFailures.length > 0 && (
          <div className="mb-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
            部分来源刷新失败：{lastFailures.map((f) => f.source).join("、")}
          </div>
        )}
        <TopNewsList items={top.data?.items} loading={top.isLoading} error={top.isError} refreshing={refreshing} />
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold">外部资讯导航</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {NEWS_NAV_SITES.map((site) => (
            <div key={site.name} className="flex flex-col rounded-lg border border-neutral-200 bg-white p-4">
              <div className="flex items-start gap-3">
                <SiteIcon url={site.url} name={site.name} />
                <div className="min-w-0">
                  <div className="text-sm font-medium">{site.name}</div>
                  <div className="mt-0.5 text-xs text-neutral-500">{site.description}</div>
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between">
                <span className="truncate text-xs text-neutral-400">{new URL(site.url).hostname}</span>
                <Button asChild size="sm" variant="outline">
                  <a href={site.url} target="_blank" rel="noopener noreferrer">
                    <ExternalLink className="h-3.5 w-3.5" /> 打开网站
                  </a>
                </Button>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-2 flex items-center gap-2 text-xs text-neutral-400">
          <Globe className="h-3.5 w-3.5" />
          外部网站在新标签页打开；若某个网站无法访问，请检查网络或稍后再试。
        </div>
      </section>
    </div>
  );
}
