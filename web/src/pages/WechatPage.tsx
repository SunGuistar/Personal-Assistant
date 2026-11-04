import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileText, RefreshCw, Send } from "lucide-react";

import { Button } from "../components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import {
  ChatEvent,
  DataRange,
  getHistory,
  postChat,
  readChatEvents,
  Report,
  startSync,
  useDataRange,
  useJob,
  useReports,
  useSourceStatus,
} from "../api/wechat";

const SESSION_KEY = "hub_wechat_session_id";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  jobId?: number;
}

export function WechatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<number | null>(
    () => Number(localStorage.getItem(SESSION_KEY)) || null
  );
  const [sending, setSending] = useState(false);
  const [reportsOpen, setReportsOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const source = useSourceStatus();
  const dataRange = useDataRange();
  const reports = useReports(reportsOpen);
  const qc = useQueryClient();

  const currentChat: DataRange | undefined = dataRange.data?.[0];
  const chips = currentChat
    ? [
        `总结今天的${currentChat.display_name}的聊天记录`,
        `今天的${currentChat.display_name}是否有人表达过对主播的担忧？`,
        "列出今天说话最多的十个人",
      ]
    : [];

  // 会话恢复
  useEffect(() => {
    if (!sessionId) return;
    getHistory(sessionId)
      .then((data) =>
        setMessages(data.messages.map((m) => ({ role: m.role as "user" | "assistant", text: m.content })))
      )
      .catch(() => localStorage.removeItem(SESSION_KEY));
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages]);

  const handleEvent = (event: ChatEvent, draft: { text: string; jobId?: number }) => {
    if (event.type === "token" && event.text) {
      draft.text += event.text;
    } else if (event.type === "summary_job" && event.task_id) {
      draft.jobId = event.task_id;
    }
  };

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || sending) return;
    setSending(true);
    setMessages((old) => [...old, { role: "user", text: message }]);
    setInput("");
    const draft: { text: string; jobId?: number } = { text: "" };
    try {
      const response = await postChat(message, sessionId);
      for await (const event of readChatEvents(response)) {
        handleEvent(event, draft);
        if (event.type === "token") {
          setMessages((old) => {
            const next = [...old];
            const last = next[next.length - 1];
            if (last?.role === "assistant" && last.text === draft.text.slice(0, last.text.length)) {
              next[next.length - 1] = { ...last, text: draft.text };
            } else {
              next.push({ role: "assistant", text: draft.text });
            }
            return next;
          });
        } else if (event.type === "summary_job") {
          setMessages((old) => {
            const next = [...old];
            next[next.length - 1] = { ...next[next.length - 1], jobId: draft.jobId };
            return next;
          });
        } else if (event.type === "done" && event.session_id) {
          setSessionId(event.session_id);
          localStorage.setItem(SESSION_KEY, String(event.session_id));
        } else if (event.type === "error") {
          setMessages((old) => [...old, { role: "assistant", text: `⚠️ ${event.message}` }]);
        }
      }
      if (!draft.text && !draft.jobId) {
        setMessages((old) => [...old, { role: "assistant", text: "（无回复）" }]);
      }
    } catch (error) {
      setMessages((old) => [
        ...old,
        { role: "assistant", text: `⚠️ ${error instanceof Error ? error.message : "请求失败"}` },
      ]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-3">
      <h1 className="text-xl font-semibold">微信聊天助手</h1>

      {/* 辅助区：数据源状态 / 同步 / 数据范围 / 历史报告 */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs">
        <StatusDot running={source.data?.running ?? false} />
        <span className="text-neutral-600">
          {source.isLoading
            ? "检查数据源…"
            : source.data?.running
              ? "WeChatDataAnalysis 运行中"
              : "WeChatDataAnalysis 未运行"}
        </span>
        <SyncButton
          onSync={() => {
            qc.invalidateQueries({ queryKey: ["wechat-data-range"] });
            qc.invalidateQueries({ queryKey: ["wechat-source-status"] });
          }}
        />
        <span className="ml-auto text-neutral-400">
          {currentChat
            ? `${currentChat.display_name}：${currentChat.message_count} 条 · ${currentChat.min_date ?? "—"} ~ ${currentChat.max_date ?? "—"}`
            : "本地暂无聊天数据，请先同步"}
        </span>
        <Button size="sm" variant="outline" onClick={() => setReportsOpen(true)}>
          <FileText className="h-3.5 w-3.5" /> 历史报告
        </Button>
      </div>

      {/* 对话窗 */}
      <div className="flex-1 space-y-3 overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4">
        {messages.length === 0 && (
          <div className="py-8 text-center text-sm text-neutral-400">
            输入问题开始对话；总结类请求会生成报告并在下方显示进度
          </div>
        )}
        {messages.map((message, index) => (
          <MessageBubble key={index} message={message} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* 快捷输入 */}
      {chips.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {chips.map((chip) => (
            <button
              key={chip}
              onClick={() => send(chip)}
              disabled={sending}
              className="rounded-full border border-neutral-300 bg-white px-3 py-1.5 text-xs text-neutral-600 hover:border-neutral-500 disabled:opacity-50"
            >
              {chip}
            </button>
          ))}
        </div>
      )}

      {/* 输入框 */}
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="输入你的问题，回车发送…"
          className="flex h-10 flex-1 rounded-md border border-neutral-300 bg-white px-3 text-sm outline-none focus:border-neutral-500"
        />
        <Button type="submit" disabled={sending || !input.trim()}>
          <Send className="h-4 w-4" /> 发送
        </Button>
      </form>

      <ReportsDialog open={reportsOpen} onClose={() => setReportsOpen(false)} reports={reports.data ?? []} />
    </div>
  );
}

function StatusDot({ running }: { running: boolean }) {
  return (
    <span
      className={`h-2.5 w-2.5 rounded-full ${running ? "bg-green-500" : "bg-neutral-300"}`}
      title={running ? "数据源在线" : "数据源离线"}
    />
  );
}

function SyncButton({ onSync }: { onSync: () => void }) {
  const [taskId, setTaskId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const job = useJob(taskId);

  const sync = async () => {
    setError(null);
    try {
      const result = await startSync({});
      setTaskId(result.task_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "同步提交失败");
    }
  };

  useEffect(() => {
    if (job.data?.status === "success") {
      setTaskId(null);
      onSync();
    }
  }, [job.data?.status, onSync]);

  const running = job.data?.status === "running" || job.data?.status === "pending";
  return (
    <span className="flex items-center gap-1">
      <Button size="sm" variant="outline" onClick={sync} disabled={running}>
        <RefreshCw className={`h-3.5 w-3.5 ${running ? "animate-spin" : ""}`} />
        {running ? `同步中 ${job.data?.progress ?? 0}%` : "同步聊天"}
      </Button>
      {job.data?.status === "failed" && (
        <span className="text-red-500">同步失败：{job.data.error}</span>
      )}
      {error && <span className="text-red-500">{error}</span>}
    </span>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
          isUser ? "bg-neutral-900 text-neutral-50" : "bg-neutral-100 text-neutral-800"
        }`}
      >
        {message.text}
        {message.jobId !== undefined && <SummaryJobCard taskId={message.jobId} />}
      </div>
    </div>
  );
}

function SummaryJobCard({ taskId }: { taskId: number }) {
  const job = useJob(taskId);
  const status = job.data?.status;
  const [reportSeq, setReportSeq] = useState<number | null>(null);
  const reports = useReports(status === "success");

  useEffect(() => {
    if (status !== "success") return;
    const html = (job.data?.result as { html?: string } | null)?.html ?? "";
    const found = reports.data?.find((report) => html.endsWith(report.filename));
    if (found) setReportSeq(found.seq);
  }, [status, job.data?.result, reports.data]);

  return (
    <div className="mt-2 rounded-md border border-neutral-300 bg-white p-2 text-xs text-neutral-600">
      {status === "pending" || status === "running" ? (
        <span>报告生成中… {job.data?.progress ?? 0}%</span>
      ) : status === "success" ? (
        reportSeq !== null ? (
          <a
            href={`/api/wechat/reports/${reportSeq}/file`}
            target="_blank"
            rel="noreferrer"
            className="text-blue-600 hover:underline"
          >
            查看总结报告 ↗
          </a>
        ) : (
          <span>报告已生成，可在"历史报告"中查看</span>
        )
      ) : status === "failed" ? (
        <span className="text-red-500">报告生成失败：{job.data?.error}</span>
      ) : (
        <span>报告任务排队中…</span>
      )}
    </div>
  );
}

function ReportsDialog({
  open,
  onClose,
  reports,
}: {
  open: boolean;
  onClose: () => void;
  reports: Report[];
}) {
  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>历史总结报告</DialogTitle>
        </DialogHeader>
        {reports.length === 0 ? (
          <div className="py-6 text-center text-sm text-neutral-400">还没有生成过报告</div>
        ) : (
          <ul className="max-h-[60vh] space-y-1 overflow-y-auto">
            {reports.map((report) => (
              <li key={report.seq} className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-neutral-50">
                <FileText className="h-4 w-4 shrink-0 text-neutral-400" />
                <span className="flex-1 truncate text-sm">{report.chat_name}</span>
                <span className="text-xs text-neutral-400">{report.date}</span>
                <a
                  href={`/api/wechat/reports/${report.seq}/file`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-blue-600 hover:underline"
                >
                  打开
                </a>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}
