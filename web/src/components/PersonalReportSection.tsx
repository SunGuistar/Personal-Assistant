import { SafeMarkdown } from "./SafeMarkdown";

interface Entry { title: string; body: string[] }

export function PersonalReportSection({ text, kind }: { text: string; kind: "yesterday" | "advice" }) {
  const entries: Entry[] = [];
  let current: Entry | null = null;
  const intro: string[] = [];
  for (const line of text.split("\n")) {
    const item = /^(?:[-*]|\d+[.、)])\s+(.+)$/.exec(line);
    const heading = /^#{3,6}\s+(.+)$/.exec(line);
    if (item || heading) {
      let content = (item?.[1] ?? heading![1]).trim();
      // 兼容历史正文中重复写入的数字前缀，编号统一由一个列表产生。
      content = content.replace(/^(?:\d+[.、)]\s+)+/, "");
      const plain = content.replace(/\*\*/g, "");
      const sentence = plain.indexOf("。");
      const bold = /^\*\*([^*]+)\*\*\s*(.*)$/.exec(content);
      let title = plain;
      let remainder = "";
      if (kind === "yesterday" && sentence >= 0) {
        title = plain.slice(0, sentence);
        remainder = plain.slice(sentence + 1).trim();
      } else if (bold) {
        title = bold[1]; remainder = bold[2];
      } else if (sentence >= 0) {
        title = plain.slice(0, sentence); remainder = plain.slice(sentence + 1).trim();
      }
      current = { title: title || plain, body: remainder ? [remainder] : [] };
      entries.push(current);
    } else if (current) current.body.push(line.replace(/^ {2,4}/, ""));
    else intro.push(line);
  }
  const bodyClass = "text-[#c7c7c7] [&_p]:text-[18px] [&_li]:text-[18px] [&_p]:leading-8 [&_li]:leading-8 [&_a]:text-[#c7c7c7]";
  const items = entries.map((entry, index) => <li key={index} className="my-4 pl-1 marker:text-[20px] marker:font-bold">
    <h3 className={`${kind === "yesterday" ? "text-[18px]" : "text-[20px]"} font-bold leading-8`}>{entry.title}</h3>
    {entry.body.some((line) => line.trim()) && <SafeMarkdown text={entry.body.join("\n")} className={`${bodyClass} mt-1`} />}
  </li>);
  return <div data-personal-section={kind}>
    {intro.some((line) => line.trim()) && <SafeMarkdown text={intro.join("\n")} className={bodyClass} />}
    {kind === "advice" ? <ol className="list-decimal pl-6" data-advice-list>{items}</ol>
      : <ul className="list-disc pl-5">{items}</ul>}
  </div>;
}
