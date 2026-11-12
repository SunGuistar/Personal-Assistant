import { Star } from "lucide-react";
import { NewsReference } from "../api/morning";
import { PersonalReportSection } from "./PersonalReportSection";
import { SafeMarkdown } from "./SafeMarkdown";

interface ImportanceProps {
  newsItems?: NewsReference[];
  pendingNewsId?: number;
  onImportanceChange?: (id: number, isImportant: boolean) => void;
}

const markdownClass = "[&_p]:text-[18px] [&_li]:text-[18px] [&_p]:leading-8 [&_li]:leading-8 [&_ul]:my-3 [&_ol]:my-3 [&_li]:my-1 [&>div]:text-xl [&>div]:mt-6 [&>div]:mb-3 [&_a]:underline [&_a]:underline-offset-4";

function savedField(selection: unknown, category: string, title: string, url?: string, field = "summary"): string {
  if (!selection || typeof selection !== "object") return "";
  const rows = (selection as Record<string, unknown>)[category];
  if (!Array.isArray(rows)) return "";
  const item = rows.find((row) => row && typeof row === "object" &&
    (url ? row.url === url || row.source_url === url : row.title === title));
  return typeof item?.[field] === "string" ? item[field].trim() : "";
}

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

// 仅调整晨报展示，标题链接与摘要展开分别操作，兼容历史 Markdown 和 AI 结构化摘要。
function NewsMarkdown({ text, newsSelection, newsItems, pendingNewsId, onImportanceChange }: { text: string; newsSelection?: unknown } & ImportanceProps) {
  const blocks: React.ReactNode[] = [];
  const lines = text.split("\n");
  let category = "";
  let categoryDepth = 0;
  let buffer: string[] = [];
  const flush = () => {
    if (buffer.length) blocks.push(<SafeMarkdown key={blocks.length} text={buffer.join("\n")} className={markdownClass} />);
    buffer = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      const label = heading[2].replace(/\*\*/g, "").trim();
      const match = /^(国内|国际|国外|AI)(新闻|资讯|社会)?$/i.exec(label);
      if (/^(?:一[、.．]\s*)?开篇速览$/.test(label)) {
        category = "overview";
        categoryDepth = heading[1].length;
      } else if (match) {
        category = match[1] === "国内" ? "domestic" : match[1].toUpperCase() === "AI" ? "ai" : "international";
        categoryDepth = heading[1].length;
      } else if (heading[1].length <= categoryDepth) category = "";
      const mainHeading = /^(?:[一二三四][、.．]\s*)?(开篇速览|重要资讯|我的昨日|今日建议)$/.exec(label);
      if (mainHeading) {
        flush();
        blocks.push(<h2 key={blocks.length} className="mb-3 mt-6 text-[24px] font-bold leading-9">{label}</h2>);
        if (mainHeading[1] === "我的昨日" || mainHeading[1] === "今日建议") {
          let end = i + 1;
          while (end < lines.length) {
            const next = /^(#{1,6})\s+/.exec(lines[end]);
            if (next && next[1].length <= heading[1].length) break;
            end++;
          }
          blocks.push(<PersonalReportSection key={blocks.length} kind={mainHeading[1] === "我的昨日" ? "yesterday" : "advice"}
            text={lines.slice(i + 1, end).join("\n")} />);
          i = end - 1;
          category = "";
        }
        continue;
      }
      buffer.push(line);
      continue;
    }
    const bullet = /^\s*(?:[-*]|\d+\.)\s+(.+)$/.exec(line);
    if (!category || !bullet) { buffer.push(line); continue; }
    flush();
    const link = /\[([^\]]+)\]\(((?:[^()\s]|\([^()]*\))+)\)/.exec(bullet[1]);
    const overviewType = category === "overview" ? /【(国内新闻|国外新闻|AI新闻|技巧与观点)】\s*$/.exec(bullet[1]) : null;
    const title = link ? `[${link[1]}](${link[2]})` : bullet[1].replace(overviewType?.[0] ?? /$^/, "");
    const body: string[] = [];
    const tail = link ? bullet[1].slice(link.index + link[0].length).replace(/^\*\*/, "").replace(overviewType?.[0] ?? /$^/, "").trim() : "";
    if (tail) body.push(tail);
    while (i + 1 < lines.length && !/^#{1,6}\s+/.test(lines[i + 1]) &&
           !/^\s*(?:[-*]|\d+\.)\s+/.test(lines[i + 1])) body.push(lines[++i]);
    const summary = body.join("\n").trim() || savedField(newsSelection, category, link?.[1] ?? title, link?.[2]) || "暂无摘要";
    const topic = overviewType?.[1] || (category === "ai" ? savedField(newsSelection, category, link?.[1] ?? title, link?.[2], "section_label") : "");
    const sourceCategory = category === "overview" ? overviewType?.[1] === "国内新闻" ? "domestic"
      : overviewType?.[1] === "国外新闻" ? "international" : "ai" : category;
    const news = newsItems?.find((item) => item.category === sourceCategory &&
      (link ? item.source_url === link[2] : item.title === title));
    blocks.push(
      <div key={blocks.length} className="my-3">
        <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-3">
          <button type="button" className={`mt-1 rounded p-1 ${news?.is_important ? "text-amber-500" : "text-neutral-400 hover:text-amber-500"} disabled:cursor-not-allowed disabled:opacity-50`}
            aria-label={`${news?.is_important ? "取消重要新闻" : "标记重要新闻"}：${link?.[1] ?? title}`}
            aria-pressed={news?.is_important ?? false}
            title={!news ? "此条目尚未关联新闻记录" : news.is_important ? "取消重要标记" : "标记为重要新闻"}
            disabled={!news || !onImportanceChange || pendingNewsId === news.id}
            onClick={() => news && onImportanceChange?.(news.id, !news.is_important)}>
            <Star className="h-5 w-5" fill={news?.is_important ? "currentColor" : "none"} />
          </button>
          <SafeMarkdown text={title} className={`${markdownClass} min-w-0 break-words`} />
          {topic && <span className={`mt-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${topicColors[topic] ?? "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-200"}`}>
            {topic}
          </span>}
        </div>
        {category === "overview" ? <SafeMarkdown text={summary} className={`${markdownClass} mt-2`} /> : <details className="mt-1 border-l-2 border-neutral-200 pl-3 dark:border-neutral-700">
          <summary className="cursor-pointer text-base text-neutral-500">摘要</summary>
          <SafeMarkdown text={summary} className={`${markdownClass} mt-2`} />
        </details>}
      </div>
    );
  }
  flush();
  return <>{blocks}</>;
}

export function MorningReportBody({ text, newsSelection, ...importance }: { text: string; newsSelection?: unknown } & ImportanceProps) {
  const lines = text.replace(/\r\n/g, "\n").replace(/^\*\*([一二三四五][、.．][^\n]+)\*\*\s*$/gm, "## $1").split("\n");
  const start = lines.findIndex((line) => /^#{1,3}\s+(?:[五5][、.．]\s*)?信息说明\s*$/.test(line));
  const heading = start < 0 ? null : /^(#{1,3})\s+(.+)$/.exec(lines[start]);
  let end = start + 1;
  if (heading) {
    while (end < lines.length) {
      const next = /^(#{1,6})\s+/.exec(lines[end]);
      if (next && next[1].length <= heading[1].length) break;
      end++;
    }
  }
  return (
    <div className="text-[18px] leading-8" data-testid="morning-report-body">
      <NewsMarkdown text={(heading ? lines.slice(0, start) : lines).join("\n")} newsSelection={newsSelection} {...importance} />
      {heading && (
        <>
          <details className="mt-6 rounded-lg border border-neutral-200 px-4 py-3 dark:border-neutral-700">
            <summary className="cursor-pointer text-lg font-semibold">{heading[2]}</summary>
            <SafeMarkdown text={lines.slice(start + 1, end).join("\n")} className={`${markdownClass} mt-3`} />
          </details>
          <NewsMarkdown text={lines.slice(end).join("\n")} newsSelection={newsSelection} {...importance} />
        </>
      )}
    </div>
  );
}
