import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { api } from "../lib/api";
import { Button } from "../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";

type StorageType = "sql" | "vector" | "file";
interface StorageItem {
  id: string; name: string; storage_type: StorageType; engine: string; path: string;
  retention: string; description: string; size_basis: string; size_bytes: number | null;
  file_count: number | null; note: string;
}
interface Overview { checked_at: string; total_bytes: number; items: StorageItem[] }
const TYPES: Record<StorageType, { label: string; color: string }> = {
  sql: { label: "SQL 数据库", color: "#6366f1" },
  vector: { label: "向量库", color: "#14b8a6" },
  file: { label: "文件", color: "#f59e0b" },
};
export function storageSize(bytes: number | null): string {
  if (bytes === null) return "未知";
  if (bytes === 0) return "0 B";
  const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), 4);
  return `${(bytes / 1024 ** unit).toFixed(unit ? 1 : 0)} ${["B", "KiB", "MiB", "GiB", "TiB"][unit]}`;
}

export function StoragePage() {
  const query = useQuery({ queryKey: ["storage-overview"], queryFn: () => api<Overview>("/storage/overview"),
    staleTime: 60_000, refetchOnWindowFocus: false, retry: false });
  const [filter, setFilter] = useState<StorageType | "all">("all");
  const [selected, setSelected] = useState<StorageItem | null>(null);
  const [view, setView] = useState<"overview" | "details">("overview");
  const data = query.data;
  const all = [...(data?.items ?? [])].sort((a, b) => (b.size_bytes ?? -1) - (a.size_bytes ?? -1));
  const items = all.filter(i => filter === "all" || i.storage_type === filter);
  const ranked = all.filter(i => i.size_bytes !== null && i.size_bytes > 0).slice(0, 10);
  const total = data?.total_bytes ?? 0;
  let angle = 0;
  const slices = (Object.keys(TYPES) as StorageType[]).map(type => {
    const size = all.filter(i => i.storage_type === type).reduce((sum, i) => sum + (i.size_bytes ?? 0), 0);
    const start = angle;
    angle += total ? size / total * 360 : 0;
    return { type, size, start, end: angle };
  });
  const gradient = total ? `conic-gradient(${slices.map(s => `${TYPES[s.type].color} ${s.start}deg ${s.end}deg`).join(",")})` : "#e5e7eb";
  return <div className="min-w-0 space-y-4">
    <nav aria-label="存储浏览子模块" className="flex flex-wrap gap-2">
      {([{ id: "overview", label: "存储概览" }, { id: "details", label: "存储明细" }] as const).map(item =>
        <button key={item.id} aria-pressed={view === item.id} onClick={() => setView(item.id)}
          className={`rounded-md px-4 py-2 text-sm ${view === item.id ? "bg-indigo-50 font-medium text-indigo-700" : "text-neutral-500 hover:bg-neutral-100"}`}>{item.label}</button>)}
    </nav>
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-white p-4 xl:p-5">
      <div><h2 className="text-sm text-neutral-500">已知总占用</h2><p className="mt-1 text-3xl font-semibold tabular-nums">{data ? storageSize(total) : "—"}</p>
        <p className="mt-2 text-xs text-neutral-500">{data ? `最近统计：${new Date(data.checked_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}` : "正在读取存储信息…"}</p></div>
      <Button variant="outline" disabled={query.isFetching} onClick={() => void query.refetch()}><RefreshCw className={`mr-2 h-4 w-4 ${query.isFetching ? "animate-spin" : ""}`} />{query.isFetching ? "统计中" : "刷新"}</Button>
    </div>
    {query.isError && <p role="alert" className="text-sm text-red-600">统计未完成：{query.error instanceof Error ? query.error.message : "请重试"}。{data && "下方保留上次结果。"}</p>}
    {data && <>
      {view === "overview" ? <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,24rem),1fr))] gap-4">
        <section className="min-w-0 rounded-xl border bg-white p-4 xl:p-5"><h3 className="mb-5 text-sm font-semibold">按类型占用</h3>
          <div className="flex flex-wrap items-center justify-around gap-5">
            <div role="img" aria-label={`类型占比，已知总占用 ${storageSize(total)}`} className="flex aspect-square w-[clamp(8rem,18vw,12rem)] shrink-0 items-center justify-center rounded-full" style={{ background: gradient }}>
              <div className="flex h-3/4 w-3/4 flex-col items-center justify-center rounded-full bg-white"><span className="text-xs text-neutral-500">已知总占用</span><span className="mt-1 font-semibold">{storageSize(total)}</span></div>
            </div>
            <div className="space-y-4 text-sm">{slices.map(s => <div key={s.type} title={`${TYPES[s.type].label}：${storageSize(s.size)}，${total ? (s.size / total * 100).toFixed(1) : 0}%`}>
              <div className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: TYPES[s.type].color }} />{TYPES[s.type].label}</div>
              <p className="mt-1 pl-4 text-xs text-neutral-500">{storageSize(s.size)} · {total ? (s.size / total * 100).toFixed(1) : 0}%</p>
            </div>)}</div>
          </div>
        </section>
        <section className="min-w-0 rounded-xl border bg-white p-4 xl:p-5"><h3 className="mb-4 text-sm font-semibold">存储大小排行 <span className="font-normal text-neutral-400">前 10 项</span></h3>
          <div className="space-y-2">{ranked.map(i => <button key={i.id} className="block w-full rounded px-1 py-0.5 text-left hover:bg-neutral-50" onClick={() => setSelected(i)} title={`${i.name}：${storageSize(i.size_bytes)}`}>
            <div className="mb-1 flex justify-between gap-2 text-xs"><span className="min-w-0 truncate">{i.name}</span><span className="shrink-0 tabular-nums text-neutral-500">{storageSize(i.size_bytes)}</span></div>
            <div className="h-2 rounded bg-neutral-100"><div className="h-2 rounded" style={{ width: `${i.size_bytes! / ranked[0].size_bytes! * 100}%`, background: TYPES[i.storage_type].color }} /></div>
          </button>)}{!ranked.length && <p className="text-sm text-neutral-500">暂无可展示的占用数据</p>}</div>
        </section>
      </div> :
      <section className="min-w-0 rounded-xl border bg-white">
        <div className="flex items-center justify-between border-b px-5 py-3"><h3 className="text-sm font-semibold">存储明细</h3>
          <select aria-label="筛选存储类型" className="rounded border px-2 py-1 text-sm" value={filter} onChange={e => setFilter(e.target.value as StorageType | "all")}>
            <option value="all">全部类型</option>{Object.entries(TYPES).map(([key, type]) => <option key={key} value={key}>{type.label}</option>)}
          </select>
        </div>
        <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] table-fixed text-left text-sm">
          <colgroup><col /><col /><col /><col className="w-28" /><col className="w-20" /></colgroup>
          <thead className="bg-neutral-50 text-xs text-neutral-500"><tr>{["存储名称", "存储类型", "设计保留时长", "当前大小 ↓", "操作"].map(h => <th key={h} className="px-3 py-3 font-medium xl:px-5">{h}</th>)}</tr></thead>
          <tbody>{items.map(i => <tr key={i.id} className="border-t"><td className="break-words px-3 py-3 xl:px-5">{i.name}</td><td className="break-words px-3 py-3 text-neutral-500 xl:px-5">{TYPES[i.storage_type].label} · {i.engine}</td>
            <td className="break-words px-3 py-3 xl:px-5" title={i.description}>{i.retention}</td><td className="whitespace-nowrap px-3 py-3 tabular-nums xl:px-5" title={i.note || i.size_basis}>{storageSize(i.size_bytes)}</td>
            <td className="px-3 py-3 xl:px-5"><button className="whitespace-nowrap text-indigo-600 hover:underline" aria-label={`查看${i.name}详情`} onClick={() => setSelected(i)}>详情</button></td></tr>)}</tbody>
        </table></div>
        <p className="border-t px-5 py-3 text-xs leading-5 text-neutral-500">统计文件逻辑大小，非磁盘实际分配空间。未知大小不计入图表及总占用；各存储去重统计。图表展示全部类型，筛选仅作用于明细。只读查看，刷新不会清理数据。</p>
      </section>}
    </>}
    <Dialog open={selected !== null} onOpenChange={open => { if (!open) setSelected(null); }}><DialogContent className="max-h-[calc(100dvh-3rem)] w-[min(48rem,calc(100vw-3rem))] max-w-none overflow-y-auto" aria-describedby={undefined}>
      <DialogHeader><DialogTitle>{selected?.name}</DialogTitle></DialogHeader>
      {selected && <dl className="space-y-4 text-sm">{[
        ["存储类型", `${TYPES[selected.storage_type].label} · ${selected.engine}`], ["当前大小", storageSize(selected.size_bytes)],
        ["路径 / 地址", selected.path], ["设计保留时长", selected.retention], ["用途及保留规则", selected.description],
        ["统计口径", selected.size_basis], ["文件数量", selected.file_count === null ? "未知" : String(selected.file_count)],
        ["说明", selected.note || "保留时长不代表自动删除；本页面不写入业务数据。"],
      ].map(([label, value]) => <div key={label}><dt className="mb-1 text-neutral-500">{label}</dt><dd className="whitespace-pre-wrap break-all">{value}</dd></div>)}</dl>}
    </DialogContent></Dialog>
  </div>;
}
