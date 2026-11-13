interface Item { id: string; title: string; summary: string; detail: string; kind: string }
interface Content { version: number; completed: Item[]; goal_progress: Item[]; attention: Item[]; questions: Item[]; additional: Item[]; notices: string[] }
export function isYesterdayContent(value: unknown): value is Content {
  if (!value || typeof value !== "object") return false;
  const data = value as Content;
  return data.version === 1 && [data.completed, data.goal_progress, data.attention, data.questions, data.additional].every(
    rows => Array.isArray(rows) && rows.every(item => item && [item.id, item.title, item.summary, item.detail, item.kind].every(value => typeof value === "string"))) &&
    Array.isArray(data.notices) && data.notices.every(value => typeof value === "string");
}
function Entry({ item, completed }: { item: Item; completed: boolean }) {
  const fact = completed && item.kind === "confirmed";
  const label = fact ? "事实完成" : "AI分析";
  const color = fact ? "bg-sky-100 text-sky-800" : "bg-violet-100 text-violet-800";
  return <li className="py-2">
    <div className="break-words text-[18px] leading-8"><h4 className="inline text-[18px] font-bold">{item.title}</h4>
      <span className={`mx-2 inline-block rounded px-2 align-middle text-xs leading-6 ${color}`}>{label}</span>
      {item.summary !== item.title && <span className="text-[#c7c7c7]">{item.summary}</span>}</div>
    {item.detail && item.detail !== item.summary && item.detail !== item.title && <details className="text-[18px] text-[#c7c7c7]"><summary className="cursor-pointer text-sm">查看完整记录</summary><p className="whitespace-pre-wrap">{item.detail}</p></details>}
  </li>;
}
export function YesterdaySummary({ content }: { content: Content }) {
  const groups = ["completed", "goal_progress", "attention", "questions", "additional"] as const;
  return <div data-testid="yesterday-summary">
    {content.notices.map((notice, index) => <p key={index} className="text-[18px] text-[#c7c7c7]">{notice}</p>)}
    <ul className="list-disc space-y-2 divide-y divide-neutral-200 pl-6 marker:text-neutral-400 dark:divide-neutral-800">
      {groups.flatMap(group => content[group].map(item => <Entry key={`${group}:${item.id}`} item={item} completed={group === "completed"} />))}
    </ul>
  </div>;
}
