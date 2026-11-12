import { Star } from "lucide-react";
import { NewsReference } from "../api/morning";
import { SafeMarkdown } from "./SafeMarkdown";

const topicColors: Record<string, string> = {
  "国内新闻": "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200",
  "国外新闻": "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200",
  "AI新闻": "bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-200",
  "技巧与观点": "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-200",
  "模型发布/更新": "bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-200",
  "产品发布/更新": "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200",
  "行业动态": "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200",
  "技术研究": "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
  "讨论与观点": "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-200",
  "快讯": "bg-cyan-100 text-cyan-800 dark:bg-cyan-950 dark:text-cyan-200",
  "精选": "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-200",
};

export function MorningNewsCard({ title, url, summary, topic, expanded = false, news, pendingNewsId, onImportanceChange }: {
  title: string; url?: string; summary: string; topic?: string; expanded?: boolean;
  news?: NewsReference; pendingNewsId?: number;
  onImportanceChange?: (id: number, important: boolean) => void;
}) {
  let href: string | undefined;
  try {
    if (url && ["http:", "https:"].includes(new URL(url).protocol)) href = url;
  } catch { /* 不渲染非法或非 HTTP 链接 */ }
  const summaryClass = "[&_p]:text-[18px] [&_li]:text-[18px] [&_p]:leading-8 [&_li]:leading-8 [&_a]:underline";
  const body = <SafeMarkdown text={summary || "暂无摘要"} className={`${summaryClass} mt-2`} />;
  return <div className="my-3" data-news-id={news?.id}>
    <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-3">
      <button type="button" className={`mt-1 rounded p-1 ${news?.is_important ? "text-amber-500" : "text-neutral-400 hover:text-amber-500"} disabled:cursor-not-allowed disabled:opacity-50`}
        aria-label={`${news?.is_important ? "取消重要新闻" : "标记重要新闻"}：${title}`}
        aria-pressed={news?.is_important ?? false}
        title={!news ? "此条目尚未关联新闻记录" : news.is_important ? "取消重要标记" : "标记为重要新闻"}
        disabled={!news || !onImportanceChange || pendingNewsId === news.id}
        onClick={() => news && onImportanceChange?.(news.id, !news.is_important)}>
        <Star className="h-5 w-5" fill={news?.is_important ? "currentColor" : "none"} />
      </button>
      <p className="min-w-0 break-words text-[18px] leading-8">
        {href ? <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-600 underline underline-offset-4">{title}</a> : title}
      </p>
      {topic && <span className={`mt-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${topicColors[topic] ?? "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-200"}`}>{topic}</span>}
    </div>
    {expanded ? body : <details className="mt-1 border-l-2 border-neutral-200 pl-3 dark:border-neutral-700">
      <summary className="cursor-pointer text-base text-neutral-500">摘要</summary>{body}
    </details>}
  </div>;
}
