import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw, ShieldAlert, Trash2 } from "lucide-react";

import { Button } from "../components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import {
  Candidate,
  Review,
  useCleanupJob,
  useCleanupReview,
  useCleanupStatus,
  useConfirmReview,
  useDismissReview,
  useExecuteCleanup,
  useRetryCandidates,
  useSkipReview,
} from "../api/cleanup";

const KEEP_REASON_LABELS: Record<string, string> = {
  protected: "含永久保护日期的消息",
  mixed: "跨日期混合 chunk（保守保留）",
  unresolved: "消息归属无法确认（保守保留）",
};

const STATE_LABELS: Record<string, string> = {
  pending: "待处理",
  validated: "已校验",
  deleted: "已删除",
  failed: "失败",
  failed_protected: "已阻止（保护日期）",
};

export function CleanupPage() {
  const status = useCleanupStatus();
  const reviews = status.data?.reviews ?? [];
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const activeId = selectedId ?? reviews[0]?.id ?? null;
  const review = useCleanupReview(activeId);

  // 二次确认（生成删除计划）→ 执行 job 轮询
  const confirmMutation = useConfirmReview();
  const execute = useExecuteCleanup();
  const [taskId, setTaskId] = useState<number | null>(null);
  const job = useCleanupJob(taskId);

  useEffect(() => {
    if (job.data && ["success", "failed"].includes(job.data.status)) {
      setTaskId(null);
    }
  }, [job.data]);

  const current: Review | undefined = review.data;
  const selected: Candidate[] = current?.candidates ?? [];
  const pending = selected.filter((c) => c.state === "pending");
  const failed = selected.filter((c) => c.state === "failed");
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [confirmOpen, setConfirmOpen] = useState(false);
  const retry = useRetryCandidates();

  const toggle = (id: number) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const checkedCandidates = pending.filter((c) => checked.has(c.id));
  const totals = {
    groups: checkedCandidates.length,
    snapshot: checkedCandidates.reduce((s, c) => s + c.snapshot_count, 0),
    normalized: checkedCandidates.reduce((s, c) => s + c.normalized_count, 0),
    chunks: checkedCandidates.reduce((s, c) => s + c.chunk_delete_count, 0),
    kept: checkedCandidates.reduce((s, c) => s + c.chunk_keep_count, 0),
  };

  const running = taskId !== null || execute.isPending || confirmMutation.isPending;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">数据清理审核</h1>
        <span className="text-xs text-neutral-400">
          微信聊天缓存 · 每周日提醒 · 所有删除均需人工勾选并二次确认
        </span>
      </div>

      {reviews.length === 0 ? (
        <div className="rounded-lg border border-dashed border-neutral-300 bg-white p-6 text-sm text-neutral-500">
          还没有清理审核记录（每周日生成，错过周日会在下次启动补发）。
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {reviews.map((r) => (
            <button
              key={r.id}
              onClick={() => {
                setSelectedId(r.id);
                setChecked(new Set());
              }}
              className={`rounded-md border px-3 py-1.5 text-xs ${
                r.id === activeId
                  ? "border-neutral-900 bg-neutral-900 text-white"
                  : "border-neutral-200 bg-white text-neutral-600 hover:bg-neutral-50"
              }`}
            >
              周期 {r.week_id} · {r.status === "pending" ? "待审核" : r.status === "dismissed" ? "已稍后" : r.status === "done" ? "已完成" : "已跳过"}
            </button>
          ))}
        </div>
      )}

      {current && (
        <section className="rounded-lg border border-neutral-200 bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">周期 {current.week_id} · 候选分组（默认全不勾选）</h2>
            <ReviewActions review={current} disabled={running} />
          </div>

          {selected.length === 0 ? (
            <div className="py-6 text-center text-sm text-neutral-400">
              本周没有可清理数据（数据未超过 7 天，或全部受永久保护）
            </div>
          ) : (
            <>
              <ul className="space-y-2">
                {selected.map((candidate) => (
                  <CandidateRow key={candidate.id} candidate={candidate} checked={checked.has(candidate.id)} onToggle={() => toggle(candidate.id)} disabled={candidate.state !== "pending" || running} />
                ))}
              </ul>
              <div className="mt-3 flex items-center justify-between border-t border-neutral-100 pt-3">
                <div className="text-xs text-neutral-500">
                  已勾选 {totals.groups} 组：快照 {totals.snapshot} 条 · 归一化 {totals.normalized} 条 · 可删 chunk {totals.chunks} 个
                  {totals.kept > 0 && ` · 保守保留 chunk ${totals.kept} 个`}
                </div>
                <Button
                  size="sm"
                  disabled={checkedCandidates.length === 0 || running || !!current.confirmed_at}
                  onClick={() => setConfirmOpen(true)}
                >
                  <Trash2 className="h-4 w-4" /> 提交删除
                </Button>
              </div>
            </>
          )}

          {failed.length > 0 && !running && (
            <div className="mt-3 flex items-center justify-between rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
              <span>
                {failed.length} 组删除失败（可重试，重试会重新校验保护规则）
              </span>
              <Button
                size="sm"
                variant="outline"
                onClick={() => retry.mutate({ reviewId: current.id, candidateIds: failed.map((c) => c.id) })}
              >
                重置失败组
              </Button>
            </div>
          )}

          {job.data?.status === "failed" && (
            <div className="mt-2 rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700">
              执行失败：{job.data.error ?? "未知错误"}
            </div>
          )}
          {job.data?.status === "success" && job.data.result && (
            <div className="mt-2 rounded-md border border-green-200 bg-green-50 p-2 text-xs text-green-700">
              执行完成：成功 {job.data.result.deleted_groups ?? 0} 组，失败 {job.data.result.failed_groups ?? 0} 组
              {job.data.result.failed_groups ? "（失败组可重置后重试）" : ""}
            </div>
          )}
        </section>
      )}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
          </DialogHeader>
          <div className="space-y-2 text-sm text-neutral-600">
            <p className="font-medium text-red-700">此操作不可直接撤销，请确认以下删除范围：</p>
            <ul className="list-disc pl-5 text-xs">
              {checkedCandidates.map((c) => (
                <li key={c.id}>
                  {c.chat_name || c.chat_id} · {c.msg_date}（快照 {c.snapshot_count} · 归一化 {c.normalized_count} · chunk {c.chunk_delete_count}）
                  {c.chunk_keep_count > 0 && `；另保留 ${c.chunk_keep_count} 个 chunk（保护/混合/未知）`}
                </li>
              ))}
            </ul>
            <p className="text-xs text-neutral-500">
              合计：快照 {totals.snapshot} 条、归一化 {totals.normalized} 条、Chroma chunk {totals.chunks} 个。
              保留的混合 chunk 仍可能检索到已删除消息文本（保守策略，已明示）。2026-10-27 测试数据永久保护，不参与清理。
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              取消
            </Button>
            <Button
              disabled={confirmMutation.isPending || execute.isPending}
              onClick={() => {
                setConfirmOpen(false);
                // 先 confirm 生成删除计划（后端复检保护规则与一致性），再提交执行
                confirmMutation.mutate(
                  { reviewId: current!.id, candidateIds: checkedCandidates.map((c) => c.id) },
                  {
                    onSuccess: () =>
                      execute.mutate(current!.id, { onSuccess: (d) => setTaskId(d.task_id) }),
                  }
                );
              }}
            >
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ReviewActions({ review, disabled }: { review: Review; disabled: boolean }) {
  const dismiss = useDismissReview();
  const skip = useSkipReview();
  if (review.status === "done" || review.status === "skipped") return null;
  return (
    <div className="flex gap-2">
      {review.status === "pending" && (
        <Button size="sm" variant="outline" disabled={disabled} onClick={() => dismiss.mutate(review.id)}>
          稍后提醒
        </Button>
      )}
      <Button
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => confirm("跳过本次审核？数据将保留，不产生任何删除。") && skip.mutate(review.id)}
      >
        跳过本次
      </Button>
    </div>
  );
}

function CandidateRow({
  candidate,
  checked,
  onToggle,
  disabled,
}: {
  candidate: Candidate;
  checked: boolean;
  onToggle: () => void;
  disabled: boolean;
}) {
  return (
    <li
      className={`rounded-md border p-3 ${
        candidate.state === "deleted"
          ? "border-green-200 bg-green-50/50"
          : candidate.state === "failed" || candidate.state === "failed_protected"
            ? "border-red-200 bg-red-50/50"
            : "border-neutral-200"
      }`}
    >
      <div className="flex items-center gap-3">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          disabled={disabled}
          aria-label={`选择 ${candidate.chat_name || candidate.chat_id} ${candidate.msg_date}`}
          className="accent-neutral-900"
        />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">
            {candidate.chat_name || candidate.chat_id} · {candidate.msg_date}
            <span className="ml-2 text-xs font-normal text-neutral-400">({STATE_LABELS[candidate.state] ?? candidate.state})</span>
          </div>
          <div className="mt-0.5 text-xs text-neutral-500">
            快照 {candidate.snapshot_count} · 归一化 {candidate.normalized_count} · 可删 chunk {candidate.chunk_delete_count}
            {candidate.chunk_keep_count > 0 && (
              <span className="ml-1 inline-flex items-center gap-0.5 text-amber-600">
                <ShieldAlert className="h-3 w-3" /> 保留 {candidate.chunk_keep_count}
              </span>
            )}
            {candidate.size_estimate > 0 && ` · 约 ${(candidate.size_estimate / 1024).toFixed(0)}KB`}
          </div>
          {candidate.keep_reasons.length > 0 && (
            <div className="mt-1 text-[11px] text-neutral-400">
              保留原因：
              {Object.entries(
                candidate.keep_reasons.reduce<Record<string, number>>((acc, k) => {
                  acc[k.reason] = (acc[k.reason] ?? 0) + 1;
                  return acc;
                }, {})
              )
                .map(([reason, count]) => `${KEEP_REASON_LABELS[reason] ?? reason}×${count}`)
                .join("；")}
            </div>
          )}
          {candidate.error && <div className="mt-1 text-[11px] text-red-600">{candidate.error}</div>}
        </div>
      </div>
    </li>
  );
}

/** 首页提醒横幅（待审核且未稍后的周期）。 */
export function CleanupBanner() {
  const status = useCleanupStatus();
  const dismiss = useDismissReview();
  const banner = status.data?.banner;
  if (!banner || banner.status !== "pending") return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm">
      <span className="flex items-center gap-2 text-amber-800">
        <RefreshCw className="h-4 w-4" />
        本周待清理数据审核：{banner.candidate_groups} 组超过 7 天的微信聊天缓存
      </span>
      <span className="flex gap-2">
        <Button asChild size="sm">
          <Link to="/cleanup">立即审核</Link>
        </Button>
        <Button size="sm" variant="outline" onClick={() => dismiss.mutate(banner.review_id)}>
          稍后
        </Button>
      </span>
    </div>
  );
}
