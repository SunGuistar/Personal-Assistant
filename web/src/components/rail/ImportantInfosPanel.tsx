import { useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Pencil, Plus, Trash2 } from "lucide-react";

import { Button } from "../ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import { Input, Label, Textarea } from "../ui/input";
import { SafeMarkdown } from "../SafeMarkdown";
import {
  ImportantInfo,
  useCreateInfo,
  useDeleteInfo,
  useInfos,
  useReorderInfos,
  useUpdateInfo,
} from "../../api/infos";

function InfoCard({
  info,
  canUp,
  canDown,
  onMove,
  onEdit,
}: {
  info: ImportantInfo;
  canUp: boolean;
  canDown: boolean;
  onMove: (direction: -1 | 1) => void;
  onEdit: () => void;
}) {
  const deleteInfo = useDeleteInfo();
  const [expanded, setExpanded] = useState(false);
  const lines = info.content.split("\n").filter((l) => l.trim() !== "");
  const foldable = lines.length > 3;

  return (
    <li className="rounded-md border border-neutral-200 bg-white p-2">
      <div className="flex items-center gap-1">
        <button onClick={() => onMove(-1)} disabled={!canUp} aria-label="上移信息" className="p-0.5 text-neutral-400 hover:text-neutral-700 disabled:opacity-30">
          <ArrowUp className="h-3.5 w-3.5" />
        </button>
        <button onClick={() => onMove(1)} disabled={!canDown} aria-label="下移信息" className="p-0.5 text-neutral-400 hover:text-neutral-700 disabled:opacity-30">
          <ArrowDown className="h-3.5 w-3.5" />
        </button>
        <span className="flex-1 truncate text-xs font-semibold">{info.title}</span>
        <button onClick={onEdit} aria-label="编辑信息" className="p-0.5 text-neutral-400 hover:text-neutral-700">
          <Pencil className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => confirm(`删除重要信息「${info.title}」？`) && deleteInfo.mutate(info.id)}
          aria-label="删除信息"
          className="p-0.5 text-neutral-400 hover:text-red-600"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
      {info.content.trim() && (
        <div className="mt-1">
          <SafeMarkdown
            text={expanded || !foldable ? info.content : lines.slice(0, 3).join("\n")}
            className="text-neutral-600"
          />
          {foldable && (
            <button
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
              className="mt-0.5 inline-flex items-center gap-0.5 text-[11px] text-neutral-400 hover:text-neutral-700"
            >
              {expanded ? (
                <>
                  收起 <ChevronDown className="h-3 w-3" />
                </>
              ) : (
                <>
                  展开 <ChevronRight className="h-3 w-3" />
                </>
              )}
            </button>
          )}
        </div>
      )}
    </li>
  );
}

function InfoDialog({
  open,
  onOpenChange,
  info,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  info: ImportantInfo | null;
}) {
  const createInfo = useCreateInfo();
  const updateInfo = useUpdateInfo();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  // 打开时重置（编辑回填）
  const [prevOpen, setPrevOpen] = useState(false);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setTitle(info?.title ?? "");
      setContent(info?.content ?? "");
    }
  }

  const submit = () => {
    const trimmed = title.trim();
    if (!trimmed) return;
    if (info) {
      updateInfo.mutate({ id: info.id, title: trimmed, content }, { onSuccess: () => onOpenChange(false) });
    } else {
      createInfo.mutate({ title: trimmed, content }, { onSuccess: () => onOpenChange(false) });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{info ? "编辑重要信息" : "新增重要信息"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>标题</Label>
            <Input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div>
            <Label>内容（支持基础 Markdown）</Label>
            <Textarea rows={5} value={content} onChange={(e) => setContent(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={submit} disabled={!title.trim()}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** 右侧栏上部：重要信息（约 40% 高度，独立滚动）。 */
export function ImportantInfosPanel() {
  const { data: infos = [] } = useInfos();
  const reorder = useReorderInfos();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ImportantInfo | null>(null);
  const ids = infos.map((i) => i.id);

  const swap = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= ids.length) return;
    const next = [...ids];
    [next[index], next[target]] = [next[target], next[index]];
    reorder.mutate(next);
  };

  return (
    <section className="flex min-h-0 flex-[2] flex-col border-b border-neutral-200">
      <div className="flex items-center justify-between px-3 py-2">
        <h2 className="text-xs font-semibold text-neutral-700">重要信息</h2>
        <Button
          size="sm"
          variant="outline"
          className="h-6 px-2 text-xs"
          onClick={() => {
            setEditing(null);
            setDialogOpen(true);
          }}
        >
          <Plus className="h-3.5 w-3.5" /> 新增
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {infos.length === 0 ? (
          <div className="py-4 text-center text-xs text-neutral-400">还没有重要信息</div>
        ) : (
          <ul className="space-y-2">
            {infos.map((info, index) => (
              <InfoCard
                key={info.id}
                info={info}
                canUp={index > 0}
                canDown={index < infos.length - 1}
                onMove={(direction) => swap(index, direction)}
                onEdit={() => {
                  setEditing(info);
                  setDialogOpen(true);
                }}
              />
            ))}
          </ul>
        )}
      </div>
      <InfoDialog open={dialogOpen} onOpenChange={setDialogOpen} info={editing} />
    </section>
  );
}
