import { useEffect } from "react";
import { StageInfo, TokenUsageItem, useMorningUsage } from "../api/morning";

function sumTokens(rows: TokenUsageItem[], field: "input_tokens" | "output_tokens" | "cache_hit_tokens" | "cache_miss_tokens"): number | null {
  const values = rows.map((row) => row[field]).filter((value): value is number => typeof value === "number");
  return values.length ? values.reduce((sum, value) => sum + value, 0) : null;
}
const fmt = (value: number | null) => value === null ? "—" : value.toLocaleString("en-US");

export function MorningTokenUsage({ runId, active, stages }: {
  runId: number; active: boolean; stages: Pick<StageInfo, "stage" | "title">[];
}) {
  const usage = useMorningUsage(runId, active);
  const { refetch } = usage;
  // 完成、失败或停止时再取一次，显示最后落库的调用用量。
  useEffect(() => { if (!active) void refetch(); }, [active, refetch]);
  const items = usage.data?.items ?? [];
  const names = new Map(stages.map((stage) => [stage.stage, stage.title]));
  for (const item of items) if (!names.has(item.node)) names.set(item.node, item.node);
  const input = sumTokens(items, "input_tokens");
  const output = sumTokens(items, "output_tokens");
  const total = items.length === 0 ? 0 : input === null && output === null ? null : (input ?? 0) + (output ?? 0);
  const cacheHits = items.length === 0 ? 0 : sumTokens(items, "cache_hit_tokens");
  const cacheMisses = items.length === 0 ? 0 : sumTokens(items, "cache_miss_tokens");
  const hitPartial = cacheHits !== null && items.some((item) => item.cache_hit_tokens == null);
  const missPartial = cacheMisses !== null && items.some((item) => item.cache_miss_tokens == null);
  const partial = items.some((item) => item.input_tokens === null || item.output_tokens === null);
  return (
    <section aria-label="本轮 Token 用量" className="mt-3 border-t border-neutral-200 pt-3 text-xs dark:border-neutral-800">
      <h3 className="mb-2 font-medium">本轮 Token 用量</h3>
      {usage.isError ?
        <p className="text-amber-700">用量获取失败</p> : <>
          <table className="w-full table-fixed text-right tabular-nums">
            <thead className="text-neutral-400"><tr><th className="w-[40%] text-left font-normal">步骤</th>
              <th className="font-normal">输入</th><th className="font-normal">输出</th><th className="font-normal">合计</th></tr></thead>
            <tbody>{Array.from(names, ([node, title]) => {
              const rows = items.filter((item) => item.node === node);
              const inTokens = rows.length === 0 && active ? 0 : sumTokens(rows, "input_tokens");
              const outTokens = rows.length === 0 && active ? 0 : sumTokens(rows, "output_tokens");
              const all = inTokens === null && outTokens === null ? null : (inTokens ?? 0) + (outTokens ?? 0);
              return <tr key={node}><th scope="row" className="truncate py-1 text-left font-normal" title={title}>{title}</th>
                <td>{fmt(inTokens)}</td><td>{fmt(outTokens)}</td><td>{fmt(all)}</td></tr>;
            })}</tbody>
          </table>
          <p className="mt-2 flex flex-wrap justify-between gap-x-2 gap-y-1 font-medium"><span>本轮总 Token</span><span>{fmt(total)}{partial ? "（已记录）" : ""}</span>
            <span className="basis-full text-[11px] font-normal text-neutral-500">
              缓存命中 {fmt(cacheHits)}{hitPartial ? "（已记录）" : ""} · 缓存未命中 {fmt(cacheMisses)}{missPartial ? "（已记录）" : ""}
            </span>
          </p>
          <p className="mt-1 text-[11px] leading-4 text-neutral-400">按本轮已记录的输入与输出累计；无记录显示 —，缓存命中不重复累加。{partial ? "部分调用用量缺失。" : ""}</p>
        </>}
    </section>
  );
}
