import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Send, Star, Trash2 } from "lucide-react";

import {
  HistoryItem, MemoryItem, Report, assistantChat, useCreateMemory, useDeleteMemory,
  useMorningHistory, useMorningMemories, useMorningReport, useMorningStatus,
  usePatchMemory, useRegenerate,
} from "../api/morning";
import { SafeMarkdown } from "../components/SafeMarkdown";
import { Button } from "../components/ui/button";
import { cn } from "../lib/utils";

type Tab = "report" | "evaluation" | "history";

export function MorningReportPage() {
  const status = useMorningStatus();
  const [tab, setTab] = useState<Tab>("report");
  const [historyView, setHistoryView] = useState<{ date: string; versionNo: number } | null>(null);
  const report = useMorningReport();

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
          <RegenerateMenu />
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
              current={historyView ?? undefined}
              onSelect={(item: HistoryItem) =>
                setHistoryView({ date: item.report_date, versionNo: item.version_no })
              }
            />
          )}
        </main>

        {historyView && (
          <HistoryModal
            date={historyView.date}
            versionNo={historyView.versionNo}
            onClose={() => setHistoryView(null)}
          />
        )}
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
  const [message, setMessage] = useState<string | null>(null);
  const run = async (mode: "reuse" | "full") => {
    setBusy(true);
    setMessage(null);
    try {
      await regenerate.mutateAsync({ mode });
      setMessage(mode === "full" ? "已提交完整重算，生成中…" : "已提交重新生成，生成中…");
      setTimeout(() => qc.invalidateQueries({ queryKey: ["morning"] }), 8000);
    } catch (e) {
      const err = e as { message?: string };
      setMessage(`提交失败：${err.message ?? "未知错误"}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex items-center gap-2">
      <Button size="sm" disabled={busy} onClick={() => run("reuse")}>
        <RefreshCw className={cn("mr-1 h-4 w-4", busy && "animate-spin")} /> 重新生成
      </Button>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => run("full")}>
        完整重算
      </Button>
      {message && (
        <span className="text-xs text-neutral-500" role="status">{message}</span>
      )}
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
  current?: { date: string; versionNo: number };
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
  const [live, setLive] = useState(false);

  useEffect(() => {
    setRows([]);
    if (!runId) return;
    let cancelled = false;
    let after = 0;
    let es: EventSource | null = null;
    let retryTimer: number | undefined;

    const connect = () => {
      if (cancelled || typeof EventSource === "undefined") return; // 测试环境（jsdom）无 EventSource
      es = new EventSource(`/api/morning/logs/stream?run_id=${runId}&after_id=${after}`);
      es.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data);
          if (d.id) {
            after = d.id;
            setRows((r) => [...r.slice(-199), d]);
          }
          if (d.done) {
            setLive(false);
            es?.close();
          }
        } catch { /* 忽略坏帧 */ }
      };
      es.onopen = () => setLive(true);
      es.onerror = () => {
        es?.close();
        if (!cancelled) retryTimer = window.setTimeout(connect, 3000); // 断线自动重连（带 after_id 续传）
      };
    };
    connect();
    return () => {
      cancelled = true;
      window.clearTimeout(retryTimer);
      es?.close();
    };
  }, [runId]);

  return (
    <section className="flex h-2/5 min-h-0 flex-col">
      <header className="flex items-center justify-between px-4 py-2">
        <h2 className="text-sm font-medium">实时执行日志</h2>
        {live && <span className="text-xs text-emerald-600">● 连接中</span>}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-2 font-mono text-xs">
        {rows.length === 0 && <p className="text-neutral-400">暂无日志。</p>}
        {rows.map((r) => (
          <div key={r.id} className="flex gap-2 py-0.5 text-left">
            <span className="text-neutral-400">{r.at.slice(11, 19)}</span>
            <span
              className={cn(
                "rounded px-1",
                r.level === "error" ? "bg-red-100 text-red-700"
                : r.level === "warning" ? "bg-amber-100 text-amber-700"
                : "bg-neutral-100 text-neutral-600",
              )}
            >
              {r.stage}
            </span>
            <span className="flex-1 truncate text-neutral-700">{r.message}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

/** 历史晨报弹窗：独立展示所选版本，可关闭（×/Esc/点遮罩）、可下载 Markdown。 */
function HistoryModal({ date, versionNo, onClose }: {
  date: string;
  versionNo: number;
  onClose: () => void;
}) {
  const q = useMorningReport(date, versionNo);
  const data = q.data;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const download = () => {
    if (!data) return;
    const blob = new Blob([data.content_md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `晨报-${data.report_date}-v${data.version_no}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="flex h-[80vh] w-full max-w-3xl flex-col rounded-lg border border-neutral-200 bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-neutral-200 px-5 py-3">
          <div>
            <h2 className="text-base font-semibold text-neutral-900">
              {data ? data.title : `历史晨报 ${date}`}
            </h2>
            <p className="text-xs text-neutral-500">
              {date} · 版本 v{versionNo}
              {data?.is_primary ? "（主报告）" : ""}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={download} disabled={!data}>
              下载 Markdown
            </Button>
            <Button size="sm" variant="outline" onClick={onClose} aria-label="关闭">
              ✕
            </Button>
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {q.isLoading && <p className="text-sm text-neutral-500">加载中…</p>}
          {q.error && <p className="text-sm text-neutral-500">报告不存在或加载失败。</p>}
          {data && (
            <article className="mx-auto max-w-2xl text-[15px] leading-7 text-neutral-800">
              <SafeMarkdown text={data.content_md} />
              <footer className="mt-6 border-t border-neutral-200 pt-3 text-xs text-neutral-400">
                窗口 {data.window_start.slice(0, 16)} ~ {data.window_end.slice(0, 16)} ·{" "}
                {data.generation_mode === "auto" ? "自动生成" : "手动生成"} · {data.created_at.slice(0, 16)}
              </footer>
            </article>
          )}
        </div>
      </div>
    </div>
  );
}
