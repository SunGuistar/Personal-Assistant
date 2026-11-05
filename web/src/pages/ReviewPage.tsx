import { useCallback, useEffect, useRef, useState } from "react";
import { Check, FileText, Pencil, RefreshCw, Send, Sparkles, X } from "lucide-react";

import { Button } from "../components/ui/button";
import { SafeMarkdown } from "../components/SafeMarkdown";
import {
  confirmReview,
  createOrGetReview,
  getReview,
  getReviewMessages,
  getReviewReport,
  postReviewChat,
  postSuggestGenerate,
  readSseEvents,
  resolveSuggestion,
  ReviewDetail,
  ReviewMessage,
  Suggestion,
  updateDraft,
  useReviews,
} from "../api/reviews";

/** 上一个完整自然周的周一（与后端 default_review_week 口径一致：本周周日结束后才算完整）。 */
function defaultWeekMonday(): string {
  const now = new Date();
  const day = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const monday = new Date(day);
  monday.setDate(day.getDate() - ((day.getDay() + 6) % 7));
  if (day.getTime() >= monday.getTime() + 7 * 86400_000) {
    return formatLocalDate(monday);
  }
  monday.setDate(monday.getDate() - 7);
  return formatLocalDate(monday);
}

/** 本地时区 YYYY-MM-DD（toISOString 会换算 UTC，东八区会把日期回拨一天）。 */
function formatLocalDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const dayOfMonth = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${dayOfMonth}`;
}

const STATUS_LABEL: Record<string, string> = {
  accepted: "已接受",
  modified: "已修改",
  rejected: "已拒绝",
};

export function ReviewPage() {
  const [weekInput, setWeekInput] = useState(defaultWeekMonday);
  const [review, setReview] = useState<ReviewDetail | null>(null);
  const [messages, setMessages] = useState<ReviewMessage[]>([]);
  const [report, setReport] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [banner, setBanner] = useState<{ kind: "info" | "error"; text: string } | null>(null);
  const [analysisDraft, setAnalysisDraft] = useState("");
  const [notesDraft, setNotesDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const history = useReviews();

  const suggestions = review?.suggestions ?? [];

  const loadReview = useCallback(async (id: number) => {
    const detail = await getReview(id);
    setReview(detail);
    setAnalysisDraft(detail.analysis_md);
    setNotesDraft(detail.user_notes);
    const [{ messages: msgs }, rep] = await Promise.all([
      getReviewMessages(id),
      detail.status === "confirmed" ? getReviewReport(id) : Promise.resolve({ report_md: null }),
    ]);
    setMessages(msgs);
    setReport(rep.report_md);
  }, []);

  const startReview = async (weekStart: string) => {
    setBanner(null);
    try {
      const detail = await createOrGetReview(weekStart);
      await loadReview(detail.id);
    } catch (error) {
      setBanner({ kind: "error", text: error instanceof Error ? error.message : "加载失败" });
    }
  };

  // 进入页面自动加载默认周期（创建草稿是确定性本地操作，无 LLM 调用）
  useEffect(() => {
    startReview(weekInput);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages]);

  const refreshDetail = async () => {
    if (!review) return;
    const detail = await getReview(review.id);
    setReview(detail);
    setAnalysisDraft(detail.analysis_md);
    setNotesDraft(detail.user_notes);
  };

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || sending || !review || review.status === "confirmed") return;
    setSending(true);
    setBanner(null);
    setMessages((old) => [...old, { id: -1, role: "user", content: message, created_at: "" }]);
    setInput("");
    const draft = { text: "" };
    try {
      const response = await postReviewChat(review.id, message);
      for await (const event of readSseEvents(response)) {
        if (event.type === "token" && typeof event.text === "string") {
          draft.text += event.text;
          setMessages((old) => {
            const next = [...old];
            const last = next[next.length - 1];
            if (last?.role === "assistant") next[next.length - 1] = { ...last, content: draft.text };
            else next.push({ id: -2, role: "assistant", content: draft.text, created_at: "" });
            return next;
          });
        } else if (event.type === "error") {
          setBanner({ kind: "error", text: String(event.message ?? "对话失败") });
        }
      }
      const { messages: persisted } = await getReviewMessages(review.id);
      setMessages(persisted);
    } catch (error) {
      setBanner({ kind: "error", text: error instanceof Error ? error.message : "请求失败" });
    } finally {
      setSending(false);
    }
  };

  const generate = async () => {
    if (!review || generating || review.status === "confirmed") return;
    setGenerating(true);
    setBanner({ kind: "info", text: "建议生成中…" });
    try {
      const response = await postSuggestGenerate(review.id);
      for await (const event of readSseEvents(response)) {
        if (event.type === "step" && typeof event.text === "string") {
          setBanner({ kind: "info", text: String(event.text) });
        } else if (event.type === "done") {
          setBanner(null);
          await refreshDetail();
          return;
        } else if (event.type === "error") {
          setBanner({ kind: "error", text: String(event.message ?? "生成失败") });
          return;
        }
      }
    } catch (error) {
      setBanner({ kind: "error", text: error instanceof Error ? error.message : "请求失败" });
    } finally {
      setGenerating(false);
    }
  };

  const actOnSuggestion = async (
    suggestion: Suggestion,
    action: string,
    extra: { final_content?: string; reject_reason?: string } = {}
  ) => {
    if (!review) return;
    try {
      await resolveSuggestion(suggestion.id, { action, ...extra });
      await refreshDetail();
    } catch (error) {
      setBanner({ kind: "error", text: error instanceof Error ? error.message : "操作失败" });
    }
  };

  const saveDraft = async () => {
    if (!review || review.status === "confirmed") return;
    await updateDraft(review.id, { analysis_md: analysisDraft, user_notes: notesDraft });
  };

  const confirm = async () => {
    if (!review || review.status === "confirmed") return;
    try {
      const result = await confirmReview(review.id, {
        analysis_md: analysisDraft,
        user_notes: notesDraft,
      });
      setReview({ ...result, suggestions });
      const rep = await getReviewReport(review.id);
      setReport(rep.report_md);
      setBanner({ kind: "info", text: "正式周报已保存" });
    } catch (error) {
      setBanner({ kind: "error", text: error instanceof Error ? error.message : "确认失败" });
    }
  };

  const pendingCount = suggestions.filter((s) => s.status === "pending").length;
  const confirmed = review?.status === "confirmed";
  const canConfirm = !!review && !confirmed && pendingCount === 0 && !generating && !sending;

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">每周回顾</h1>
        <input
          type="date"
          value={weekInput}
          onChange={(e) => setWeekInput(e.target.value)}
          className="h-8 rounded-md border border-neutral-300 bg-white px-2 text-sm"
        />
        <Button size="sm" variant="outline" onClick={() => startReview(weekInput)}>
          <RefreshCw className="h-3.5 w-3.5" /> {review ? "切换周期" : "开始回顾"}
        </Button>
        <select
          value={review?.id ?? ""}
          onChange={(e) => {
            const id = Number(e.target.value);
            const target = history.data?.find((r) => r.id === id);
            if (target) {
              setWeekInput(target.week_start);
              loadReview(id).catch(() => setBanner({ kind: "error", text: "加载失败" }));
            }
          }}
          className="ml-auto h-8 rounded-md border border-neutral-300 bg-white px-2 text-xs text-neutral-600"
        >
          <option value="">历史周报…</option>
          {(history.data ?? []).map((r) => (
            <option key={r.id} value={r.id}>
              {r.week_start} ~ {r.week_end}（{r.status === "confirmed" ? "已确认" : "草稿"}）
            </option>
          ))}
        </select>
      </div>

      {review && (
        <div className="text-xs text-neutral-500">
          回顾周期：{review.week_start} ~ {review.week_end}
          {confirmed && <span className="ml-2 text-green-600">已确认正式周报（只读）</span>}
          {!confirmed && pendingCount > 0 && (
            <span className="ml-2 text-amber-600">{pendingCount} 条建议待处置</span>
          )}
        </div>
      )}

      {banner && (
        <div
          className={`rounded-md border px-3 py-2 text-sm ${
            banner.kind === "error"
              ? "border-red-300 bg-red-50 text-red-600"
              : "border-neutral-300 bg-white text-neutral-600"
          }`}
        >
          {banner.text}
        </div>
      )}

      {!review ? (
        <div className="rounded-lg border border-dashed border-neutral-300 bg-white p-6 text-sm text-neutral-500">
          选择周期后点击"开始回顾"：Agent 将读取本周个人数据（任务/计划/备忘/重要信息/阅读）进行分析。
        </div>
      ) : (
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto">
          <StatsCards review={review} />

          {/* 已确认：正式周报 */}
          {confirmed && report && (
            <section className="rounded-lg border border-neutral-200 bg-white p-4">
              <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
                <FileText className="h-4 w-4" /> 正式周报
              </h2>
              <SafeMarkdown text={report} className="text-sm text-neutral-800" />
            </section>
          )}

          {/* Agent 对话 */}
          {!confirmed && (
            <section className="rounded-lg border border-neutral-200 bg-white p-4">
              <h2 className="mb-2 text-sm font-semibold">Agent 分析对话</h2>
              <div className="max-h-72 space-y-2 overflow-y-auto">
                {messages.length === 0 && (
                  <div className="py-4 text-center text-xs text-neutral-400">
                    向 Agent 描述本周情况、追问分析依据，或补充它不知道的信息
                  </div>
                )}
                {messages.map((message, index) => (
                  <div
                    key={index}
                    className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div
                      className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                        message.role === "user"
                          ? "bg-neutral-900 text-neutral-50"
                          : "bg-neutral-100 text-neutral-800"
                      }`}
                    >
                      {message.content}
                    </div>
                  </div>
                ))}
                <div ref={bottomRef} />
              </div>
              <form
                className="mt-2 flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  send(input);
                }}
              >
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={sending ? "Agent 分析中…" : "输入消息，回车发送…"}
                  disabled={sending}
                  className="flex h-9 flex-1 rounded-md border border-neutral-300 bg-white px-3 text-sm outline-none focus:border-neutral-500"
                />
                <Button type="submit" size="sm" disabled={sending || !input.trim()}>
                  <Send className="h-4 w-4" /> 发送
                </Button>
              </form>
            </section>
          )}

          {/* 周报草稿（确认前可编辑） */}
          {!confirmed && (
            <section className="space-y-2 rounded-lg border border-neutral-200 bg-white p-4">
              <h2 className="text-sm font-semibold">周报草稿（确认前可编辑）</h2>
              <textarea
                value={analysisDraft}
                onChange={(e) => setAnalysisDraft(e.target.value)}
                placeholder="分析正文（生成建议后自动填入，可修改）"
                rows={5}
                className="w-full rounded-md border border-neutral-300 bg-white p-2 text-sm outline-none focus:border-neutral-500"
              />
              <textarea
                value={notesDraft}
                onChange={(e) => setNotesDraft(e.target.value)}
                placeholder="用户补充信息（可选）"
                rows={2}
                className="w-full rounded-md border border-neutral-300 bg-white p-2 text-sm outline-none focus:border-neutral-500"
              />
              <div>
                <Button size="sm" variant="outline" onClick={() => saveDraft().catch(() => undefined)}>
                  保存草稿
                </Button>
              </div>
            </section>
          )}

          {/* 下周建议 */}
          {!confirmed && (
            <section className="rounded-lg border border-neutral-200 bg-white p-4">
              <div className="mb-2 flex items-center gap-2">
                <h2 className="text-sm font-semibold">下周建议</h2>
                <Button size="sm" variant="outline" onClick={generate} disabled={generating}>
                  <Sparkles className={`h-3.5 w-3.5 ${generating ? "animate-pulse" : ""}`} />
                  {generating ? "生成中…" : suggestions.length ? "重新生成" : "生成建议"}
                </Button>
              </div>
              {suggestions.length === 0 && (
                <div className="py-2 text-xs text-neutral-400">
                  点击"生成建议"：Agent 将基于对话、统计与业务事实提出下周行动建议
                </div>
              )}
              <div className="space-y-2">
                {suggestions.map((suggestion) => (
                  <SuggestionCard
                    key={suggestion.id}
                    suggestion={suggestion}
                    disabled={generating}
                    onAct={(action, extra) => actOnSuggestion(suggestion, action, extra)}
                  />
                ))}
              </div>
            </section>
          )}

          {/* 确认保存 */}
          {!confirmed && (
            <section className="flex items-center gap-2">
              <Button onClick={confirm} disabled={!canConfirm}>
                <Check className="h-4 w-4" /> 确认保存周报
              </Button>
              {pendingCount > 0 && (
                <span className="text-xs text-amber-600">
                  还有 {pendingCount} 条建议未处置（接受/修改/拒绝）
                </span>
              )}
              <span className="text-xs text-neutral-400">确认后不可修改；不会自动创建任务</span>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function StatsCards({ review }: { review: ReviewDetail }) {
  const stats = review.stats;
  if (!stats?.tasks) return null;
  const cards: Array<[string, string]> = [
    ["本周任务", `${stats.tasks.belonging.done}/${stats.tasks.belonging.total} 完成`],
    ["本周标记完成", `${stats.tasks.done_in_week.total} 项`],
    ["周末逾期/积压", `${stats.tasks.overdue_at_week_end.total} 项`],
    ["新建任务", `${stats.tasks.created_in_week} 项`],
    ["长期计划", `活动 ${stats.plans.active.total} · 本周完成 ${stats.plans.completed_in_week.length}`],
    ["随手备忘", `${stats.memos.total} 条（搁置 ${stats.memos.stale}）`],
    ["阅读", `在读 ${stats.reading.reading.length} 本 · 本周笔记 ${stats.reading.notes_added_in_week}`],
  ];
  return (
    <section className="grid grid-cols-2 gap-2 md:grid-cols-4">
      {cards.map(([label, value]) => (
        <div key={label} className="rounded-lg border border-neutral-200 bg-white px-3 py-2">
          <div className="text-xs text-neutral-400">{label}</div>
          <div className="text-sm font-medium text-neutral-800">{value}</div>
        </div>
      ))}
    </section>
  );
}

function SuggestionCard({
  suggestion,
  disabled,
  onAct,
}: {
  suggestion: Suggestion;
  disabled: boolean;
  onAct: (action: string, extra?: { final_content?: string; reject_reason?: string }) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(suggestion.content);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const resolved = suggestion.status !== "pending";

  return (
    <div
      className={`rounded-md border p-3 text-sm ${
        resolved ? "border-neutral-200 bg-neutral-50" : "border-neutral-300 bg-white"
      }`}
    >
      <div className="flex items-start gap-2">
        <span className="flex-1 whitespace-pre-wrap text-neutral-800">
          {resolved && suggestion.final_content ? suggestion.final_content : suggestion.content}
        </span>
        {resolved && (
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${
              suggestion.status === "rejected"
                ? "bg-neutral-200 text-neutral-500"
                : "bg-green-100 text-green-700"
            }`}
          >
            {STATUS_LABEL[suggestion.status]}
          </span>
        )}
        {suggestion.is_general && (
          <span className="shrink-0 rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
            一般性建议
          </span>
        )}
      </div>

      {suggestion.basis.length > 0 && (
        <ul className="mt-2 space-y-1 border-t border-dashed border-neutral-200 pt-2 text-xs text-neutral-500">
          {suggestion.basis.map((basis, index) => (
            <li key={index}>
              <span className="text-neutral-700">依据：</span>
              {basis.fact}——{basis.reason}
            </li>
          ))}
        </ul>
      )}
      {suggestion.status === "rejected" && suggestion.reject_reason && (
        <div className="mt-1 text-xs text-neutral-400">拒绝理由：{suggestion.reject_reason}</div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" disabled={disabled} onClick={() => onAct("accept")}>
          <Check className="h-3.5 w-3.5" /> 接受
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={disabled}
          onClick={() => {
            setText(resolved && suggestion.final_content ? suggestion.final_content : suggestion.content);
            setEditing((v) => !v);
          }}
        >
          <Pencil className="h-3.5 w-3.5" /> 修改
        </Button>
        <Button size="sm" variant="outline" disabled={disabled} onClick={() => setRejecting((v) => !v)}>
          <X className="h-3.5 w-3.5" /> 拒绝
        </Button>
        {editing && (
          <span className="flex flex-1 items-center gap-1">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              className="h-8 flex-1 rounded-md border border-neutral-300 px-2 text-xs"
            />
            <Button
              size="sm"
              disabled={!text.trim()}
              onClick={() => {
                onAct("modify", { final_content: text });
                setEditing(false);
              }}
            >
              保存
            </Button>
          </span>
        )}
        {rejecting && (
          <span className="flex flex-1 items-center gap-1">
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="拒绝理由（可选）"
              className="h-8 flex-1 rounded-md border border-neutral-300 px-2 text-xs"
            />
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                onAct("reject", { reject_reason: reason });
                setRejecting(false);
              }}
            >
              确认拒绝
            </Button>
          </span>
        )}
      </div>
    </div>
  );
}
