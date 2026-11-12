interface Item { id: string; title: string; summary: string; detail: string; kind: string }
interface Content { version: number; completed: Item[]; goal_progress: Item[]; attention: Item[]; questions: Item[]; additional: Item[]; notices: string[] }
export function isYesterdayContent(value: unknown): value is Content {
  if (!value || typeof value !== "object") return false;
  const data = value as Content;
  return data.version === 1 && [data.completed, data.goal_progress, data.attention, data.questions, data.additional].every(
    rows => Array.isArray(rows) && rows.every(item => item && [item.id, item.title, item.summary, item.detail, item.kind].every(value => typeof value === "string"))) &&
    Array.isArray(data.notices) && data.notices.every(value => typeof value === "string");
}
function Entry({ item }: { item: Item }) {
  const label = item.kind === "confirmed" ? "事实" : item.kind === "analysis" ? "分析" : "待确认";
  const color = item.kind === "confirmed" ? "bg-sky-100 text-sky-800" : item.kind === "analysis" ? "bg-violet-100 text-violet-800" : "bg-amber-100 text-amber-800";
  return <li className="py-2">
    <div className="flex items-start gap-2"><h4 className="min-w-0 text-[18px] font-bold">{item.title}</h4>
      <span className={`mt-1 shrink-0 rounded px-2 text-xs leading-6 ${color}`}>{label}</span></div>
    {item.summary !== item.title && <p className="text-[18px] leading-8 text-[#c7c7c7]">{item.summary}</p>}
    {item.detail && item.detail !== item.summary && item.detail !== item.title && <details className="text-[18px] text-[#c7c7c7]"><summary className="cursor-pointer text-sm">查看完整记录</summary><p className="whitespace-pre-wrap">{item.detail}</p></details>}
  </li>;
}
function Group({ title, items, limit }: { title: string; items: Item[]; limit: number }) {
  if (!items.length) return null;
  return <section className="mt-4"><h3 className="text-[22px] font-bold leading-9">{title}</h3>
    <ul className="list-disc space-y-2 pl-6 marker:text-neutral-400 divide-y divide-neutral-200 dark:divide-neutral-800">{items.slice(0, limit).map(item => <Entry key={item.id} item={item} />)}</ul>
    {items.length > limit && <details className="mt-2"><summary className="cursor-pointer text-sm text-neutral-500">{limit ? `查看其余 ${items.length - limit} 条` : `展开 ${items.length} 条`}</summary><ul className="list-disc space-y-2 pl-6 marker:text-neutral-400">{items.slice(limit).map(item => <Entry key={item.id} item={item} />)}</ul></details>}
  </section>;
}
export function YesterdaySummary({ content }: { content: Content }) {
  const goals = Math.min(3, content.goal_progress.length), risks = Math.min(2, content.attention.length);
  const attention = [...content.attention, ...content.questions, ...content.additional];
  const completed = Math.min(5, Math.max(3, 8 - goals - risks));
  return <div data-testid="yesterday-summary">
    {content.notices.map((notice, index) => <p key={index} className="text-[18px] text-[#c7c7c7]">{notice}</p>)}
    <Group title="昨日完成" items={content.completed} limit={completed} />
    <Group title="目标推进" items={content.goal_progress} limit={goals} />
    <Group title="需要关注" items={attention} limit={risks} />
  </div>;
}
