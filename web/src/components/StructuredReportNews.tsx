import { NewsReference } from "../api/morning";
import { MorningNewsCard } from "./MorningNewsCard";

type Category = "domestic" | "international" | "ai";
interface NewsEntry {
  id: number; category: Category; title: string; url: string; summary: string; section_label: string;
}
interface NewsContent {
  version: 1; categories: Record<Category, NewsEntry[]>;
  overview: (NewsEntry & { display_type: string })[]; errors: Partial<Record<Category, string>>;
}
const categories: Category[] = ["domestic", "international", "ai"];
function isEntry(item: unknown): item is NewsEntry {
  if (!item || typeof item !== "object") return false;
  const value = item as Record<string, unknown>;
  return Number.isInteger(value.id) && categories.includes(value.category as Category) &&
    ["title", "url", "summary", "section_label"].every((key) => typeof value[key] === "string");
}
export function isStructuredNews(value: unknown): value is NewsContent {
  if (!value || typeof value !== "object") return false;
  const content = value as NewsContent;
  return content.version === 1 && !!content.categories && categories.every((key) =>
    Array.isArray(content.categories[key]) && content.categories[key].every((item) => isEntry(item) && item.category === key)) &&
    Array.isArray(content.overview) && content.overview.every((item) => isEntry(item) && typeof item.display_type === "string") &&
    !!content.errors && typeof content.errors === "object" && Object.values(content.errors).every((error) => typeof error === "string");
}

export function StructuredReportNews({ content, newsItems, pendingNewsId, onImportanceChange }: {
  content: NewsContent; newsItems?: NewsReference[]; pendingNewsId?: number;
  onImportanceChange?: (id: number, important: boolean) => void;
}) {
  const card = (item: NewsEntry, topic: string, expanded = false) => <MorningNewsCard key={`${topic}-${item.id}`}
    title={item.title} url={item.url} summary={item.summary} topic={topic} expanded={expanded}
    news={newsItems?.find((row) => row.id === item.id)} pendingNewsId={pendingNewsId} onImportanceChange={onImportanceChange} />;
  return <>
    <h2 className="mb-3 mt-6 text-[24px] font-bold leading-9">一、开篇速览</h2>
    {content.overview.length ? content.overview.map((item) => card(item, item.display_type)) : <p>本期暂无可用速览资讯。</p>}
    <h2 className="mb-3 mt-6 text-[24px] font-bold leading-9">二、重要资讯</h2>
    {categories.map((category) => <section key={category} aria-label={`${category}资讯`}>
      <h3 className="mb-2 mt-4 text-xl font-semibold">{{ domestic: "国内", international: "国际", ai: "AI" }[category]}</h3>
      {content.errors[category] && <p className="my-2 text-[16px] text-amber-700 dark:text-amber-400">资讯暂缺：{content.errors[category]}</p>}
      {content.categories[category].map((item) => card(item, category === "ai" ? item.section_label : ""))}
      {!content.categories[category].length && !content.errors[category] && <p>本期暂无可用资讯。</p>}
    </section>)}
  </>;
}
