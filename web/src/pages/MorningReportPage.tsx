import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, CheckCircle2, Circle, Clock, Loader2, MinusCircle, RefreshCw,
  Send, Star, Trash2, XCircle,
} from "lucide-react";

import {
  fetchActiveProgress, fetchProgress, HistoryItem, MemoryItem, ProgressSnapshot,
  stopRun,
  Report, StageInfo, assistantChat, useCreateMemory, useDeleteMemory,
  useMorningHistory, useMorningMemories, useMorningReport, usePatchMemory, useRegenerate,
} from "../api/morning";
import { SafeMarkdown } from "../components/SafeMarkdown";
import { Button } from "../components/ui/button";
import { cn } from "../lib/utils";

type Tab = "report" | "evaluation" | "history";

export function MorningReportPage() {
  const [tab, setTab] = useState<Tab>("report");
  const [historyView, setHistoryView] = useState<{ date: string; versionNo: number } | null>(null);
  const report = useMorningReport();

  const data: Report | undefined = report.data;
  // 活动任务：初始化与兜底轮询 /progress/active（5s）；重新生成提交后立即切换
  const [active, setActive] = useState<ProgressSnapshot | null>(null);
  const acceptSnapshot = useCallback((s: ProgressSnapshot) => {
    setActive((prev) => {
      if (prev?.run && !s.run) return prev;
      if (prev?.run && s.run && (s.run.id < prev.run.id ||
          (s.run.id === prev.run.id && (!prev.active && s.active || s.seq < prev.seq)))) return prev;
      return s;
    });
  }, []);
  const taskActive = active?.active ?? false;
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchActiveProgress().then((s) => !cancelled && acceptSnapshot(s)).catch(() => undefined);
    load();
    const timer = window.setInterval(load, taskActive ? 5000 : 30000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [taskActive, acceptSnapshot]);
  const runId = active?.run?.id ?? null;

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
              {taskActive ? " · 生成中…" : ""}
            </p>
          </div>
          <RegenerateMenu
            running={taskActive}
            runId={runId}
            onSubmitted={(id) => {
              setActive({ run: { id, run_date: "", kind: "generate", status: "pending",
                error: null, started_at: null, finished_at: null }, active: true,
                stages: [], recent: [], done_count: 0, total_count: 11,
                seq: 0, server_now: new Date().toISOString(), stall_seconds: 150 });
              // 立即切换到新任务并置活动态（不等 5s 轮询，按钮即刻互斥）
              fetchProgress(id)
                .then((s) => { if (s.run) acceptSnapshot(s); })
                .catch(() => undefined);
            }}
          />
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
        <ProgressPanel snap={active} onSnapshot={acceptSnapshot} />
      </aside>
    </div>
  );
}

function RegenerateMenu({ running, runId, onSubmitted }: {
  running: boolean; // 后端活动任务存在即禁用生成按钮（多标签页经 5s 轮询同步）
  runId: number | null;
  onSubmitted: (runId: number) => void;
}) {
  const regenerate = useRegenerate();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  useEffect(() => {
    if (!running) setStopping(false); // 任务离开活动态后复位停止按钮
  }, [running]);
  const run = async (mode: "reuse" | "full") => {
    setBusy(true);
    setErrorMessage(null);
    try {
      const res = await regenerate.mutateAsync({ mode });
      onSubmitted(res.run_id); // 立即切换，不等 /status 轮询
      setTimeout(() => qc.invalidateQueries({ queryKey: ["morning"] }), 8000);
    } catch (e) {
      const err = e as { message?: string };
      setErrorMessage(`提交失败：${err.message ?? "未知错误"}`);
    } finally {
      setBusy(false);
    }
  };
  const disabled = busy || running;
  const stop = async () => {
    if (runId == null) return;
    if (!window.confirm("确定停止本次晨报生成吗？已完成的阶段结果和历史记录会保留，尚未完成的晨报不会发布。")) {
      return; // 用户取消：不改变任何任务状态
    }
    setStopping(true);
    setErrorMessage(null);
    try {
      await stopRun(runId);
    } catch (e) {
      const err = e as { message?: string };
      setErrorMessage(`停止请求失败：${err.message ?? "未知错误"}`);
      setStopping(false);
    }
  };
  return (
    <div className="flex items-center gap-2">
      <Button size="sm" disabled={disabled} onClick={() => run("reuse")}>
        <RefreshCw className={cn("mr-1 h-4 w-4", busy && "animate-spin")} /> 重新生成
      </Button>
      <Button size="sm" variant="outline" disabled={disabled} onClick={() => run("full")}>
        完整重算
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={!running || stopping}
        onClick={stop}
      >
        {stopping ? "正在停止…" : "停止生成"}
      </Button>
      {errorMessage && (
        <span className="text-xs text-red-600" role="alert">{errorMessage}</span>
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

// 阶段展示辅助
const STAGE_PURPOSE: Record<string, string> = {
  collect: "新浪国内/国际热榜为主，中新网精选补充，结合 AIHOT 和热摸爽获取候选",
  index: "AI 资讯写入 Qdrant 向量索引并做必要索引一致性检查（不通过则阻塞）",
  snapshot: "冻结本期新闻与个人上下文快照，保证生成基于确定的数据版本",
  info_analysis: "从候选中选出值得进入晨报的国内/国际/AI 条目（公共价值优先）",
  personal_analysis: "只依据有时间证据的个人记录总结昨日进展",
  tech_research: "分析本期 AI 资讯的技术价值、局限与历史脉络（Subagent）",
  goal_analysis: "对照昨日活动、长期计划与 Memory 识别目标进展（Subagent）",
  advice: "综合前两阶段结论与历史建议，形成 0–3 条行动建议（后置）",
  editor: "把材料整合为五部分中文晨报正文",
  quality_eval: "独立模型对最终正文做五维评分（失败不阻塞发布）",
  publish: "保存报告版本、质量评价并更新历史晨报索引",
};

const STATUS_META: Record<string, { label: string; className: string }> = {
  success: { label: "已完成", className: "bg-emerald-100 text-emerald-700" },
  running: { label: "进行中", className: "bg-sky-100 text-sky-700" },
  pending: { label: "等待执行", className: "bg-neutral-100 text-neutral-500" },
  warning: { label: "警告", className: "bg-amber-100 text-amber-700" },
  failed: { label: "失败", className: "bg-red-100 text-red-700" },
  skipped: { label: "降级/跳过", className: "bg-amber-100 text-amber-700" },
  interrupted: { label: "中断·待确认", className: "bg-neutral-200 text-neutral-600" },
  stopping: { label: "正在停止", className: "bg-sky-100 text-sky-700" },
  cancelled: { label: "已停止", className: "bg-neutral-200 text-neutral-600" },
};

function fmtClock(iso: string | null | undefined): string {
  return iso ? iso.slice(11, 19) : "--:--:--";
}

function fmtDuration(ms: number | null | undefined): string {
  if (!ms && ms !== 0) return "-";
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${s % 60}s`;
}

function StageIcon({ status }: { status: string }) {
  const cls = "h-3.5 w-3.5 shrink-0";
  switch (status) {
    case "success": case "skipped": return <CheckCircle2 className={cn(cls, "text-emerald-600")} />;
    case "running": return <Loader2 className={cn(cls, "animate-spin text-sky-600")} />;
    case "warning": return <AlertTriangle className={cn(cls, "text-amber-600")} />;
    case "failed": return <XCircle className={cn(cls, "text-red-600")} />;
    case "interrupted": return <MinusCircle className={cn(cls, "text-neutral-500")} />;
    default: return <Circle className={cn(cls, "text-neutral-300")} />;
  }
}

/** 晨报生成进度面板：完整阶段列表 + 整体进度 + 关键动态；点击阶段开悬浮详情。 */
function ProgressPanel({ snap, onSnapshot }: {
  snap: ProgressSnapshot | null;
  onSnapshot: (snapshot: ProgressSnapshot) => void;
}) {
  const runId = snap?.run?.id ?? null;
  const active = snap?.active ?? false;
  const [live, setLive] = useState(false);
  const [openStage, setOpenStage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [, setTick] = useState(0);

  useEffect(() => {
    const t = window.setInterval(() => setTick((n) => n + 1), 1000); // 秒级刷新耗时
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => {
    setOpenStage(null);
    setLive(false);
    if (!runId || !active) return;
    let cancelled = false;
    let lastSeq = snap?.seq ?? 0;
    let done = false;
    let es: EventSource | null = null;
    let retryTimer: number | undefined;

    const connect = (afterSeq: number) => {
      if (cancelled || done || typeof EventSource === "undefined") return; // jsdom 无 EventSource
      es = new EventSource(`/api/morning/progress/stream?run_id=${runId}&after_seq=${afterSeq}`);
      es.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data);
          if (d.stages && d.seq >= lastSeq) {
            lastSeq = d.seq;
            if (!cancelled) {
              onSnapshot(d);
            }
          }
          if (d.done) {
            done = true;
            setLive(false);
            es?.close();
          }
        } catch { /* 忽略坏帧 */ }
      };
      es.onopen = () => setLive(true);
      es.onerror = () => {
        es?.close();
        setLive(false);
        if (!cancelled && !done) retryTimer = window.setTimeout(() => connect(lastSeq), 3000);
      };
    };

    connect(lastSeq);
    return () => {
      cancelled = true;
      window.clearTimeout(retryTimer);
      es?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, active, onSnapshot]);

  // 服务器时钟偏移（用于卡住判断与耗时，避免客户端时钟不准）
  const serverOffset = snap
    ? new Date(snap.server_now).getTime() - Date.now()
    : 0;
  const nowServer = () => Date.now() + serverOffset;

  const run = snap?.run ?? null;
  const currentStage = snap?.stages.find((s) => s.status === "running") ?? null;
  const elapsedRun = run?.started_at
    ? Math.max(0, nowServer() - new Date(run.started_at).getTime())
    : null;

  const stalledStage = currentStage && currentStage.last_event_at
    ? nowServer() - new Date(currentStage.last_event_at).getTime() > snap!.stall_seconds * 1000
    : false;

  return (
    <section className="relative flex h-2/5 min-h-0 flex-col">
      <header className="flex items-center justify-between px-4 py-2">
        <h2 className="text-sm font-medium">生成进度</h2>
        {live && <span className="text-xs text-emerald-600">● 已连接</span>}
      </header>

      {run && snap && (
        <div className="space-y-1 px-4 pb-1 text-xs text-neutral-600">
          <div className="flex items-center gap-2">
            <span className={cn("rounded px-1.5 py-0.5", STATUS_META[run.status]?.className ?? "bg-neutral-100")}>
              {STATUS_META[run.status]?.label ?? run.status}
            </span>
            <span>开始 {fmtClock(run.started_at)}</span>
            <span className="inline-flex items-center gap-0.5">
              <Clock className="h-3 w-3" />
              {run.status === "success" || run.status === "failed" || run.status === "degraded"
                ? fmtDuration(run.finished_at && run.started_at
                    ? new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()
                    : null)
                : fmtDuration(elapsedRun)}
            </span>
            <span className="ml-auto">
              阶段 {snap.done_count}/{snap.total_count}
            </span>
          </div>
          {currentStage && (
            <p className="truncate">
              当前：<span className="font-medium text-sky-700">{currentStage.title}</span>
              {stalledStage && (
                <span className="ml-2 rounded bg-amber-100 px-1 text-amber-700">
                  较长时间未更新（{fmtDuration(nowServer() - new Date(currentStage.last_event_at!).getTime())}）
                </span>
              )}
            </p>
          )}
          {!currentStage && run.error && (
            <p className="truncate text-red-600">{run.error}</p>
          )}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-1">
        {snap?.stages.map((s) => {
          const showGroupHead = s.group && s.stage === "tech_research";
          return (
            <div key={s.stage}>
              {showGroupHead && (
                <p className="mt-1 text-[10px] uppercase tracking-wide text-neutral-400">并行执行</p>
              )}
              <button
                className={cn(
                  "flex w-full items-center gap-1.5 rounded px-1 py-1 text-left text-xs hover:bg-neutral-100",
                  s.status === "running" && "bg-sky-50",
                )}
                onClick={() => setOpenStage(openStage === s.stage ? null : s.stage)}
              >
                <StageIcon status={s.status} />
                <span
                  className={cn(
                    "shrink-0",
                    s.status === "pending" ? "text-neutral-400" : "text-neutral-700",
                    s.status === "running" && "font-medium text-sky-700",
                  )}
                >
                  {s.title}
                </span>
                <span className="truncate text-neutral-400">
                  {s.summary || s.reason || ""}
                </span>
              </button>
            </div>
          );
        })}
        {!snap && <p className="py-2 text-xs text-neutral-400">今天还没有生成任务。</p>}
      </div>

      {snap && snap.recent.length > 0 && (
        <div className="border-t border-neutral-100 px-4 py-1">
          <p className="py-0.5 text-[10px] uppercase tracking-wide text-neutral-400">最近动态</p>
          {snap.recent.slice(-3).map((r) => (
            <p key={r.id} className="truncate text-[11px] text-neutral-500">
              <span className="text-neutral-400">{r.at.slice(11, 19)}</span>{" "}
              {r.level === "error" ? "✗ " : r.level === "warning" ? "⚠ " : ""}{r.message}
            </p>
          ))}
        </div>
      )}

      {openStage && snap && (
        <StagePopover
          stage={snap.stages.find((s) => s.stage === openStage)!}
          onClose={() => setOpenStage(null)}
          onCopied={() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          }}
          copied={copied}
        />
      )}
    </section>
  );
}

/** 阶段悬浮详情窗（面板内部浮层，不改变页面布局）。 */
function StagePopover({ stage, onClose, onCopied, copied }: {
  stage: StageInfo;
  onClose: () => void;
  onCopied: () => void;
  copied: boolean;
}) {
  const tech = stage.data ?? {};
  const categoryCounts = tech.by_category as Record<string, number> | undefined;
  const selectedCounts = tech.selected_by_category as Record<string, number> | undefined;
  const rawCounts = tech.raw_by_category as Record<string, number> | undefined;
  const windowCounts = tech.windowed_by_category as Record<string, number> | undefined;
  const coverageNotes = tech.coverage_notes as string[] | undefined;
  const copy = () => {
    navigator.clipboard?.writeText(JSON.stringify(
      { stage: stage.stage, status: stage.status, summary: stage.summary, reason: stage.reason, data: stage.data },
      null, 2,
    )).then(onCopied).catch(() => undefined);
  };
  return (
    <div className="absolute inset-x-2 bottom-2 top-10 z-10 flex flex-col rounded-md border border-neutral-200 bg-white shadow-lg">
      <header className="flex items-center justify-between border-b border-neutral-100 px-3 py-2">
        <div>
          <h3 className="text-sm font-medium">{stage.title}</h3>
          <p className={cn("mt-0.5 inline-block rounded px-1 text-[11px]",
            STATUS_META[stage.status]?.className)}>
            {STATUS_META[stage.status]?.label}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <Button size="sm" variant="outline" onClick={copy}>
            {copied ? "已复制" : "复制"}
          </Button>
          <Button size="sm" variant="outline" onClick={onClose} aria-label="关闭详情">✕</Button>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2 text-xs leading-5">
        <p className="text-neutral-500">{STAGE_PURPOSE[stage.stage] ?? ""}</p>
        {stage.stage === "collect" && categoryCounts && (
          <div className="mt-2 rounded border border-neutral-100 p-2">
            <p className="mb-1 text-neutral-500">已保存候选资讯（含线索）</p>
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              <span>国内 {categoryCounts.domestic ?? 0} 条</span>
              <span>国际 {categoryCounts.international ?? 0} 条</span>
              <span>AI {categoryCounts.ai ?? 0} 条</span>
            </div>
          </div>
        )}
        {stage.stage === "collect" && rawCounts && windowCounts && categoryCounts && (
          <div className="mt-2 space-y-1 text-neutral-500">
            <p>获取候选 → 时间过滤 → 事件去重后保存</p>
            {([["domestic", "国内"], ["international", "国际"], ["ai", "AI"]] as const).map(([key, label]) => (
              <p key={key}>{label}：{rawCounts[key] ?? 0} → {windowCounts[key] ?? 0} → {categoryCounts[key] ?? 0}</p>
            ))}
            <p>时间过滤只计窗口内新闻；保存数量还包含时间未知的线索。</p>
          </div>
        )}
        {stage.stage === "collect" && selectedCounts && (
          <p className="mt-2 text-neutral-500">最终选用：国内 {selectedCounts.domestic ?? 0} 条、国际 {selectedCounts.international ?? 0} 条、AI {selectedCounts.ai ?? 0} 条</p>
        )}
        {stage.stage === "collect" && coverageNotes && coverageNotes.length > 0 && (
          <ul className="mt-2 list-disc space-y-1 pl-4 text-amber-700">
            {coverageNotes.map((note, i) => <li key={i}>{note}</li>)}
          </ul>
        )}
        <dl className="mt-2 space-y-1">
          <div className="flex gap-2"><dt className="w-16 shrink-0 text-neutral-400">开始</dt><dd>{fmtClock(stage.started_at)}</dd></div>
          <div className="flex gap-2"><dt className="w-16 shrink-0 text-neutral-400">结束</dt><dd>{fmtClock(stage.finished_at)}</dd></div>
          <div className="flex gap-2"><dt className="w-16 shrink-0 text-neutral-400">耗时</dt><dd>{fmtDuration(stage.elapsed_ms)}</dd></div>
          <div className="flex gap-2"><dt className="w-16 shrink-0 text-neutral-400">尝试次数</dt><dd>{stage.attempts || "-"}</dd></div>
          {stage.summary && (
            <div className="flex gap-2"><dt className="w-16 shrink-0 text-neutral-400">结果</dt><dd>{stage.summary}</dd></div>
          )}
          {stage.reason && (
            <div className="flex gap-2"><dt className="w-16 shrink-0 text-neutral-400">说明</dt><dd className="text-amber-700">{stage.reason}</dd></div>
          )}
        </dl>
        {Object.keys(tech).length > 0 && (
          <details className="mt-2 rounded border border-neutral-100 p-2">
            <summary className="cursor-pointer text-neutral-500">技术详情（已脱敏）</summary>
            <pre className="mt-1 whitespace-pre-wrap break-all text-[11px] text-neutral-500">
              {JSON.stringify(tech, null, 2)}
            </pre>
          </details>
        )}
      </div>
    </div>
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
