import { useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";

import { NewsTopItem } from "../../api/news";

export function relativeTime(iso: string): string {
  const then = new Date(iso);
  const diffMinutes = Math.max(Math.floor((Date.now() - then.getTime()) / 60000), 0);
  if (diffMinutes < 60) return `${diffMinutes} 分钟前`;
  if (diffMinutes < 60 * 24) return `${Math.floor(diffMinutes / 60)} 小时前`;
  return `${Math.floor(diffMinutes / (60 * 24))} 天前`;
}

/** 展示标题/摘要：优先中文翻译，缺失或失败回退原文。 */
function displayTitle(item: NewsTopItem): string {
  return item.title_zh.trim() || item.title;
}

function displaySummary(item: NewsTopItem): string {
  return item.summary_zh.trim() || item.raw_summary.trim();
}

function NewsRow({ item }: { item: NewsTopItem }) {
  const [expanded, setExpanded] = useState(false);
  const summary = displaySummary(item);
  const hasSummary = summary.length > 0;

  return (
    <li className="border-b border-neutral-100 py-2 last:border-b-0">
      <div className="flex items-center gap-2">
        <span className="w-6 shrink-0 text-center text-xs font-semibold text-neutral-400">
          {item.rank}
        </span>
        <button
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="min-w-0 flex-1 truncate text-left text-sm font-medium text-neutral-900 hover:underline"
        >
          {displayTitle(item)}
        </button>
        {(hasSummary || expanded) &&
          (expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-neutral-400" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-neutral-400" />
          ))}
      </div>
      {/* 中文摘要默认直接展示（限 2 行），点击标题展开完整内容 */}
      {hasSummary && (
        <button
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className={`mt-0.5 block w-full pl-8 text-left text-xs leading-relaxed text-neutral-600 ${
            expanded ? "" : "line-clamp-2"
          }`}
        >
          {summary}
          {!expanded && summary.length > 80 && (
            <span className="ml-1 text-neutral-400">展开</span>
          )}
        </button>
      )}
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 pl-8 text-xs text-neutral-400">
        <span>{item.source}</span>
        <span>·</span>
        <span>{relativeTime(item.published_at)}</span>
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="inline-flex items-center gap-0.5 text-neutral-400 hover:text-neutral-700"
        >
          查看原文 <ExternalLink className="h-3 w-3" />
        </a>
      </div>
      {expanded && !hasSummary && (
        <p className="mt-1 pl-8 text-xs leading-relaxed text-neutral-400">来源未提供摘要</p>
      )}
    </li>
  );
}

/** 资讯页热门 TOP 10 榜单组件（API 数据与翻译结果同源复用）。 */
export function TopNewsList({
  items,
  loading,
  error,
  refreshing = false,
}: {
  items?: NewsTopItem[];
  loading: boolean;
  error: boolean;
  refreshing?: boolean;
}) {
  if (loading) {
    return <div className="py-6 text-center text-sm text-neutral-400">加载中…</div>;
  }
  if (error) {
    return <div className="py-6 text-center text-sm text-neutral-500">资讯暂不可用（后端未连接）</div>;
  }
  if (!items || items.length === 0) {
    return (
      <div className="py-6 text-center text-sm text-neutral-400">
        还没有资讯{refreshing ? "，正在抓取…" : "，到资讯页点「刷新」获取"}
      </div>
    );
  }
  return (
    <ul>
      {items.map((item) => (
        <NewsRow key={item.id} item={item} />
      ))}
    </ul>
  );
}
