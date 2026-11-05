import { Fragment, ReactNode } from "react";

/**
 * 轻量安全 Markdown 渲染：标题 / 无序/有序列表 / 代码块 / 行内代码 /
 * 粗体 / 斜体 / 链接（仅 http/https）。
 *
 * 安全模型：所有文本节点都经 React 文本渲染（等价 HTML 转义），
 * 不生成任意 HTML，天然防 XSS；链接协议白名单拦截 javascript: 等。
 */

const INLINE_RE = /(\[([^\]]+)\]\(((?:[^()\s]|\([^()]*\))+)\))|(`([^`]+)`)|(\*\*([^*]+)\*\*)|(\*([^*]+)\*)/;

function safeHref(url: string): string | null {
  const trimmed = url.trim();
  return /^https?:\/\//i.test(trimmed) ? trimmed : null;
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let rest = text;
  let index = 0;
  while (rest.length > 0) {
    const match = INLINE_RE.exec(rest);
    if (!match) {
      nodes.push(rest);
      break;
    }
    if (match.index > 0) nodes.push(rest.slice(0, match.index));
    if (match[1] !== undefined) {
      const href = safeHref(match[3]);
      nodes.push(
        href ? (
          <a
            key={`${keyPrefix}-${index++}`}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline"
          >
            {match[2]}
          </a>
        ) : (
          match[2]
        )
      );
    } else if (match[4] !== undefined) {
      nodes.push(
        <code key={`${keyPrefix}-${index++}`} className="rounded bg-neutral-100 px-1 py-0.5 text-[0.85em] text-red-600">
          {match[5]}
        </code>
      );
    } else if (match[6] !== undefined) {
      nodes.push(<strong key={`${keyPrefix}-${index++}`}>{match[7]}</strong>);
    } else if (match[8] !== undefined) {
      nodes.push(<em key={`${keyPrefix}-${index++}`}>{match[9]}</em>);
    }
    rest = rest.slice(match.index + match[0].length);
  }
  return nodes;
}

export function SafeMarkdown({ text, className = "" }: { text: string; className?: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // 代码块
    if (line.trim().startsWith("```")) {
      const buffer: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        buffer.push(lines[i]);
        i++;
      }
      i++; // 跳过收尾 ```
      blocks.push(
        <pre key={key++} className="my-1 whitespace-pre-wrap break-words rounded bg-neutral-900 p-2 text-xs text-neutral-100">
          <code>{buffer.join("\n")}</code>
        </pre>
      );
      continue;
    }

    // 标题
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const content = renderInline(heading[2], `h${key}`);
      const cls = level === 1 ? "text-sm font-semibold" : level === 2 ? "text-[13px] font-semibold" : "text-xs font-semibold";
      blocks.push(
        <div key={key++} className={`${cls} mt-1 mb-0.5`}>
          {content}
        </div>
      );
      i++;
      continue;
    }

    // 无序列表
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={key++} className="my-0.5 list-disc pl-4">
          {items.map((item, idx) => (
            <li key={idx} className="text-xs leading-relaxed">
              {renderInline(item, `ul${key}-${idx}`)}
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // 有序列表
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i++;
      }
      blocks.push(
        <ol key={key++} className="my-0.5 list-decimal pl-4">
          {items.map((item, idx) => (
            <li key={idx} className="text-xs leading-relaxed">
              {renderInline(item, `ol${key}-${idx}`)}
            </li>
          ))}
        </ol>
      );
      continue;
    }

    // 空行
    if (line.trim() === "") {
      i++;
      continue;
    }

    // 段落
    const paragraph: string[] = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^(#{1,3})\s+/.test(lines[i]) &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !lines[i].trim().startsWith("```")
    ) {
      paragraph.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={key++} className="text-xs leading-relaxed">
        {paragraph.map((l, idx) => (
          <Fragment key={idx}>
            {idx > 0 && <br />}
            {renderInline(l, `p${key}-${idx}`)}
          </Fragment>
        ))}
      </p>
    );
  }

  return <div className={className}>{blocks}</div>;
}
