import { useState } from "react";
import { FavoriteNews, useFavoriteNews, useUpdateFavoriteNews } from "../api/morning";
import { StarButton, importantRowClass } from "./StarButton";
import { Button } from "./ui/button";
import { Textarea } from "./ui/input";

const CATEGORY_LABELS: Record<string, string> = { domestic: "国内新闻", international: "国际新闻", ai: "AI 新闻" };
const CATEGORY_CLASSES: Record<string, string> = {
  domestic: "bg-blue-50 text-blue-700", international: "bg-purple-50 text-purple-700", ai: "bg-emerald-50 text-emerald-700",
};

export function FavoriteMorningNews() {
  const query = useFavoriteNews();
  if (query.isPending) return <p className="text-sm text-neutral-500">加载中…</p>;
  if (query.isError) return <div role="alert" className="text-sm text-red-600">收藏新闻加载失败。<Button variant="outline" size="sm" onClick={() => void query.refetch()}>重试</Button></div>;
  const items = query.data.items;
  if (!items.length) return <p className="text-sm text-neutral-500">暂无收藏新闻，可在晨报正文或历史晨报中点击新闻五角星收藏。</p>;
  return <div className="space-y-3">
    <p className="text-sm text-neutral-500">共 {items.length} 条收藏新闻 · 红色五角星标记重点并置顶，仅笔记可编辑。</p>
    <ul className="space-y-1">{items.map(item => <FavoriteRow key={item.content_hash || item.id} item={item} />)}</ul>
  </div>;
}

function FavoriteRow({ item }: { item: FavoriteNews }) {
  const update = useUpdateFavoriteNews();
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");
  return <li className={`rounded-md border border-neutral-200 px-3 py-3 ${importantRowClass(item.is_highlighted)}`}>
    <div className="flex items-start gap-3">
      <span className={update.isPending ? "pointer-events-none opacity-50" : ""}>
        <StarButton important={item.is_highlighted} onToggle={() => {
          if (!update.isPending) update.mutate({ id: item.id, is_highlighted: !item.is_highlighted });
        }} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="min-w-0 break-words text-xl font-semibold leading-7 text-neutral-900">{item.title}</span>
          <span className={`shrink-0 rounded px-2 py-0.5 text-xs ${CATEGORY_CLASSES[item.category] ?? "bg-neutral-100 text-neutral-600"}`}>
            {CATEGORY_LABELS[item.category] ?? item.category}
          </span>
        </div>
        {editing ? <div className="mt-2 space-y-2">
          <Textarea className="text-lg leading-7" aria-label={`笔记：${item.title}`} value={note} maxLength={10000} disabled={update.isPending}
            onChange={event => setNote(event.target.value)} />
          <div className="flex gap-2">
            <Button size="sm" disabled={update.isPending} onClick={() => update.mutate({ id: item.id, note }, { onSuccess: () => setEditing(false) })}>保存笔记</Button>
            <Button size="sm" variant="outline" disabled={update.isPending} onClick={() => { setEditing(false); update.reset(); }}>取消</Button>
          </div>
        </div> : item.note.trim() ? <p className="mt-2 whitespace-pre-wrap break-words text-lg leading-7 text-blue-700">笔记：{item.note}</p> : null}
        {item.summary?.trim() && <details className="mt-2 text-sm text-neutral-600">
          <summary className="cursor-pointer select-none text-neutral-500">摘要</summary>
          <p className="mt-2 whitespace-pre-wrap break-words">{item.summary}</p>
        </details>}
        {update.isError && <p role="alert" className="mt-2 text-sm text-red-600">保存失败，请重试。未保存的笔记已保留。</p>}
      </div>
      {!editing && <Button size="sm" variant="outline" disabled={update.isPending} onClick={() => { setNote(item.note); setEditing(true); update.reset(); }}>编辑笔记</Button>}
    </div>
  </li>;
}
