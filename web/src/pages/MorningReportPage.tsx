import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Moon, RefreshCw, Send, Star, Sun, Trash2 } from "lucide-react";

import {
  HistoryItem, MemoryItem, Report, assistantChat, useCreateMemory, useDeleteMemory,
  useMorningHistory, useMorningMemories, useMorningReport, useMorningStatus,
  usePatchMemory, useRegenerate,
} from "../api/morning";
import { SafeMarkdown } from "../components/SafeMarkdown";
import { Button } from "../components/ui/button";
import { cn } from "../lib/utils";

type Tab = "report" | "evaluation" | "history";

const DARK_KEY = "hub.theme.dark";

function useDarkMode() {
  const [dark, setDark] = useState(() => localStorage.getItem(DARK_KEY) === "1");
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem(DARK_KEY, dark ? "1" : "0");
  }, [dark]);
  return { dark, toggle: () => setDark((v) => !v) };
}

export function MorningReportPage() {
  const { dark, toggle } = useDarkMode();
  const status = useMorningStatus();
  const [tab, setTab] = useState<Tab>("report");
  const [selected, setSelected] = useState<{ date: string; versionNo: number } | null>(null);
  const report = useMorningReport(selected?.date, selected?.versionNo);

  const data: Report | undefined = report.data;
  const runId = status.data?.today_run?.id ?? null;

  return (
    <div className="flex h-full min-h-0">
      {/* 主阅读区 */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-neutral-200 px-6 py-3 dark:border-neutral-800">
          <div>
            <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50">今日晨报</h1>
            <p className="text-xs text-neutral-500 dark:text-neutral-400">
              {data
                ? `${data.report_date} · 版本 v${data.version_no}${data.is_primary ? "（主报告）" : ""}`
                : "今天还没有主报告"}
              {status.data?.today_run?.status === "running" ? " · 生成中…" : ""}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={toggle} aria-label="切换深色模式">
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <RegenerateMenu />
          </div>
        </header>

        <nav className="flex gap-1 border-b border-neutral-200 px-6 pt-2 dark:border-neutral-800">
          {([["report", "晨报正文"], ["evaluation", "质量评价"], ["history", "历史晨报"]] as [Tab, string][]).map(
            ([key, label]) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={cn(
                  "rounded-t-md px-4 py-2 text-sm",
                  tab === key
                    ? "bg-neutral-900 text-neutral-50 dark:bg-neutral-100 dark:text-neutral-900"
                    : "text-neutral-600 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-800",
                )}
              >
                {label}
              </button>
            ),
          )}
        </nav>

        <main className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {tab === "report" && <ReportTab data={data} loading={report.isLoading} error={report.error} />}
          {tab === "evaluation" && <EvaluationTab data={data} />}
          {tab === "history" && (
            <HistoryTab
              current={selected}
              onSelect={(item: HistoryItem) =>
                setSelected({ date: item.report_date, versionNo: item.version_no })
              }
            />
          )}
        </main>
      </div>

      {/* 右栏：晨报助手 + 实时日志 */}
      <aside className="hidden w-80 shrink-0 flex-col border-l border-neutral-200 dark:border-neutral-800 lg:flex">
        <AssistantPanel />
        <LogPanel runId={runId} />
      </aside>
    </div>
  );
}

function RegenerateMenu() {
  const regenerate = useRegenerate();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const run = async (mode: "reuse" | "full") => {
    setBusy(true);
    try {
      await regenerate.mutateAsync({ mode });
      setTimeout(() => qc.invalidateQueries({ queryKey: ["morning"] }), 8000);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex gap-2">
      <Button size="sm" disabled={busy} onClick={() => run("reuse")}>
        <RefreshCw className={cn("mr-1 h-4 w-4", busy && "animate-spin")} /> 重新生成
      </Button>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => run("full")}>
        完整重算
      </Button>
    </div>
  );
}

function ReportTab({ data, loading, error }: { data?: Report; loading: boolean; error?: unknown }) {
  if (loading) return <p className="text-sm text-neutral-500">加载中…</p>;
  if (error || !data) {
    return (
      <div className="text-sm text-neutral-500">
        <p>今天的主报告尚未生成。</p>
        <p className="mt-1 text-xs">可点击右上角「重新生成」立即生成；每天 08:00 会自动生成。</p>
      </div>
    );
  }
  return (
    <article className="mx-auto max-w-3xl text-[15px] leading-7 text-neutral-800 dark:text-neutral-200">
      <SafeMarkdown text={data.content_md} />
      <footer className="mt-6 border-t border-neutral-200 pt-3 text-xs text-neutral-400 dark:border-neutral-800">
        窗口 {data.window_start.slice(0, 16)} ~ {data.window_end.slice(0, 16)} · 快照 {data.snapshot_id} ·{" "}
        {data.generation_mode === "auto" ? "自动生成" : "手动生成"} · {data.created_at.slice(0, 16)}
      </footer>
    </article>
  );
}

function EvaluationTab({ data }: { data?: Report }) {
  if (!data) return <p className="text-sm text-neutral-500">暂无报告。</p>;
  const ev = data.evaluation;
  if (!ev || ev.status === "failed") {
    return <p className="text-sm text-neutral-500">该版本未评价或评价失败（不影响正文发布）。</p>;
  }
  const dims = Object.entries(ev.scores ?? {});
  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-4 flex items-baseline gap-3">
        <span className="text-4xl font-bold text-neutral-900 dark:text-neutral-50">{ev.composite}</span>
        <span className="text-xs text-neutral-400">综合分（{ev.rule_version}，五维等权，程序计算）</span>
      </div>
      <div className="space-y-3">
        {dims.map(([name, score]) => (
          <div key={name}>
            <div className="mb-1 flex justify-between text-sm">
              <span className="text-neutral-700 dark:text-neutral-300">{name}</span>
              <span className="font-medium">{score}</span>
            </div>
            <div className="h-2 rounded bg-neutral-200 dark:bg-neutral-700">
              <div className="h-2 rounded bg-neutral-900 dark:bg-neutral-100" style={{ width: `${score}%` }} />
            </div>
          </div>
        ))}
      </div>
      <p className="mt-5 whitespace-pre-wrap text-sm leading-6 text-neutral-600 dark:text-neutral-300">
        {ev.comment}
      </p>
    </div>
  );
}

function HistoryTab({ current, onSelect }: {
  current: { date: string; versionNo: number } | null;
  onSelect: (item: HistoryItem) => void;
}) {
  const history = useMorningHistory();
  const items = history.data?.items ?? [];
  if (!items.length) return <p className="text-sm text-neutral-500">暂无历史晨报。</p>;
  return (
    <ul className="max-w-2xl space-y-2">
      {items.map((item) => (
        <li key={item.id}>
          <button
            onClick={() => onSelect(item)}
            className={cn(
              "flex w-full items-center gap-3 rounded-md border px-4 py-3 text-left text-sm",
              current?.date === item.report_date && current?.versionNo === item.version_no
                ? "border-neutral-900 dark:border-neutral-100"
                : "border-neutral-200 hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-800",
            )}
          >
            <span className="font-medium">{item.report_date}</span>
            <span className="text-neutral-500">v{item.version_no}</span>
            {item.is_primary && <Star className="h-3.5 w-3.5 fill-current" />}
            <span className="ml-auto text-xs text-neutral-400">{item.created_at.slice(0, 16)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

interface ChatMsg { role: "user" | "assistant"; content: string }
interface Proposal { kind: string; content: string }

function AssistantPanel() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const memories = useMorningMemories();
  const createMemory = useCreateMemory();
  const patchMemory = usePatchMemory();
  const deleteMemory = useDeleteMemory();
  const bottomRef = useRef<HTMLDivElement>(null);
  const [showMemory, setShowMemory] = useState(false);

  useEffect(() => bottomRef.current?.scrollIntoView?.({ behavior: "smooth" }), [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", content: text }]);
    let acc = "";
    try {
      const final = await assistantChat(text, messages, (delta) => {
        acc += delta;
        setMessages((m) => [...m, { role: "assistant" as const, content: acc }].slice(-12));
      });
      setMessages((m) => [...m.filter((x) => x.content !== acc || x.role !== "assistant"), { role: "assistant", content: final.content || acc }]);
      if (final.proposals.length) setProposals(final.proposals);
    } catch {
      setMessages((m) => [...m, { role: "assistant", content: "（助手调用失败，请稍后重试）" }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col border-b border-neutral-200 dark:border-neutral-800">
      <header className="flex items-center justify-between px-4 py-2">
        <h2 className="text-sm font-medium">晨报助手</h2>
        <button className="text-xs text-neutral-500 underline" onClick={() => setShowMemory((v) => !v)}>
          Memory 管理
        </button>
      </header>

      {showMemory && (
        <div className="max-h-48 overflow-y-auto border-t border-neutral-100 px-4 py-2 text-sm dark:border-neutral-800">
          {(memories.data ?? []).map((m: MemoryItem) => (
            <div key={m.id} className="flex items-start gap-2 py-1">
              <span className="rounded bg-neutral-100 px-1 text-xs dark:bg-neutral-700">{m.kind}</span>
              <span className={cn("flex-1", !m.enabled && "text-neutral-400 line-through")}>{m.content}</span>
              <button
                className="text-xs text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200"
                onClick={() => patchMemory.mutate({ id: m.id, enabled: !m.enabled })}
              >
                {m.enabled ? "禁用" : "启用"}
              </button>
              <button
                className="text-neutral-400 hover:text-red-500"
                onClick={() => deleteMemory.mutate(m.id)}
                aria-label="删除"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          {!(memories.data ?? []).length && <p className="text-xs text-neutral-400">暂无 Memory。</p>}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2">
        {messages.map((m, i) => (
          <div key={i} className={cn("mb-2 text-sm leading-6", m.role === "user" ? "text-right" : "")}>
            <span
              className={cn(
                "inline-block rounded-lg px-3 py-1.5",
                m.role === "user"
                  ? "bg-neutral-900 text-neutral-50 dark:bg-neutral-100 dark:text-neutral-900"
                  : "bg-neutral-100 text-neutral-800 dark:bg-neutral-800 dark:text-neutral-200",
              )}
            >
              {m.content}
            </span>
          </div>
        ))}
        {proposals.map((p, i) => (
          <div key={`p-${i}`} className="mb-2 rounded-lg border border-amber-300 bg-amber-50 p-2 text-xs dark:border-amber-700 dark:bg-amber-900/30">
            <p className="mb-1 font-medium">助手提议记录一条 Memory（需你确认）：</p>
            <p className="mb-2 text-neutral-600 dark:text-neutral-300">[{p.kind}] {p.content}</p>
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => {
                  createMemory.mutate({ kind: p.kind, content: p.content, source: "chat" });
                  setProposals((list) => list.filter((_, j) => j !== i));
                }}
              >
                确认写入
              </Button>
              <Button size="sm" variant="outline" onClick={() => setProposals((list) => list.filter((_, j) => j !== i))}>
                忽略
              </Button>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="flex items-center gap-2 border-t border-neutral-200 p-2 dark:border-neutral-800">
        <input
          className="min-w-0 flex-1 rounded-md border border-neutral-300 bg-transparent px-3 py-1.5 text-sm dark:border-neutral-600"
          placeholder="偏好 / Memory / 目标补充…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <Button size="sm" disabled={busy} onClick={send} aria-label="发送">
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </section>
  );
}

interface LogRow { id: number; at: string; stage: string; level: string; message: string }

function LogPanel({ runId }: { runId: number | null }) {
  const [rows, setRows] = useState<LogRow[]>([]);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    setRows([]);
    if (!runId) return;
    let cancelled = false;
    let after = 0;
    const connect = async () => {
      const resp = await fetch(`/api/morning/logs/stream?run_id=${runId}&after_id=${after}`);
      if (!resp.ok || !resp.body) return;
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done || cancelled) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";
        for (const evt of events) {
          const line = evt.trim();
          if (!line.startsWith("data:")) continue;
          try {
            const d = JSON.parse(line.slice(5));
            if (d.id) {
              after = d.id;
              if (!cancelled) setRows((r) => [...r.slice(-199), d]);
            }
          } catch { /* 忽略不完整帧 */ }
        }
      }
    };
    connect().catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [runId]);

  return (
    <section className="flex h-2/5 min-h-0 flex-col">
      <header className="px-4 py-2">
        <h2 className="text-sm font-medium">实时执行日志</h2>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-2 font-mono text-xs">
        {rows.length === 0 && <p className="text-neutral-400">暂无日志。</p>}
        {rows.map((r) => (
          <div key={r.id}>
            <button className="flex w-full gap-2 py-0.5 text-left" onClick={() => setOpen(open === r.id ? null : r.id)}>
              <span className="text-neutral-400">{r.at.slice(11, 19)}</span>
              <span
                className={cn(
                  "rounded px-1",
                  r.level === "error" ? "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-200"
                  : r.level === "warning" ? "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-200"
                  : "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
                )}
              >
                {r.stage}
              </span>
              <span className="flex-1 truncate text-neutral-700 dark:text-neutral-200">{r.message}</span>
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
