import { isYesterdayContent, YesterdaySummary } from "./YesterdaySummary";
import { MorningNewsCard } from "./MorningNewsCard";
import { StructuredReportNews, isStructuredNews } from "./StructuredReportNews";
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

// 仅调整晨报展示，标题链接与摘要展开分别操作，兼容历史 Markdown 和 AI 结构化摘要。
function NewsMarkdown({ text, newsSelection, yesterdayContent, newsItems, pendingNewsId, onImportanceChange }: { text: string; newsSelection?: unknown; yesterdayContent?: unknown } & ImportanceProps) {
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
      const match = /^(国内|国际|国外|AI)\s*(新闻|资讯|社会|前沿)?$/i.exec(label);
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
          blocks.push(mainHeading[1] === "我的昨日" && isYesterdayContent(yesterdayContent) ? <YesterdaySummary key={blocks.length} content={yesterdayContent} /> : <PersonalReportSection key={blocks.length} kind={mainHeading[1] === "我的昨日" ? "yesterday" : "advice"}
            text={lines.slice(i + 1, end).join("\n")} />);
          i = end - 1;
          category = "";
        }
        continue;
      }
      buffer.push(line);
      continue;
    }
    if (line.startsWith("资讯暂缺：")) {
      flush();
      blocks.push(<p key={blocks.length} className="my-2 text-[16px] text-amber-700 dark:text-amber-400">{line}</p>);
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
    blocks.push(<MorningNewsCard key={blocks.length} title={link?.[1] ?? title.replace(/\*\*/g, "")}
      url={link?.[2]} summary={summary} topic={topic} expanded={false}
      news={news} pendingNewsId={pendingNewsId} onImportanceChange={onImportanceChange} />);
  }
  flush();
  return <>{blocks}</>;
}

export function MorningReportBody({ text, newsSelection, newsContent, yesterdayContent, ...importance }: { text: string; newsSelection?: unknown; newsContent?: unknown; yesterdayContent?: unknown } & ImportanceProps) {
  const lines = text.replace(/\r\n/g, "\n").replace(/^\*\*([一二三四五][、.．][^\n]+)\*\*\s*$/gm, "## $1").split("\n");
  if (isStructuredNews(newsContent)) {
    const tail = lines.findIndex((line) => /^#{1,2}\s*(?:[三四五][、.．]\s*)?(我的昨日|今日建议|信息说明)/.test(line));
    const title = lines.find((line) => /^#\s+/.test(line));
    return <div data-testid="morning-structured-report" className="text-[18px] leading-8">
      {title && <SafeMarkdown text={title} className={markdownClass} />}
      <StructuredReportNews content={newsContent} {...importance} />
      {tail >= 0 && <MorningReportBody text={lines.slice(tail).join("\n")} newsSelection={newsSelection} yesterdayContent={yesterdayContent} {...importance} />}
    </div>;
  }
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
      <NewsMarkdown text={(heading ? lines.slice(0, start) : lines).join("\n")} newsSelection={newsSelection} yesterdayContent={yesterdayContent} {...importance} />
      {heading && (
        <>
          <details className="mt-6 rounded-lg border border-neutral-200 px-4 py-3 dark:border-neutral-700">
            <summary className="cursor-pointer text-lg font-semibold">{heading[2]}</summary>
            <SafeMarkdown text={lines.slice(start + 1, end).join("\n")} className={`${markdownClass} mt-3`} />
          </details>
          <NewsMarkdown text={lines.slice(end).join("\n")} newsSelection={newsSelection} yesterdayContent={yesterdayContent} {...importance} />
        </>
      )}
    </div>
  );
}
