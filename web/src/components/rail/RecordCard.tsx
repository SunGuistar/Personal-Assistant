import { ReactNode } from "react";
import { ArrowDown, ArrowUp, Pencil, Trash2 } from "lucide-react";

import { SafeMarkdown } from "../SafeMarkdown";

/**
 * 右栏通用记录卡片（重要信息/随手备忘共用）：标题与内容完整显示、自动换行、
 * 无展开/收起、无省略截断；长英文单词/URL/代码通过 break-words 防溢出。
 */
export function RecordCard({
  title,
  content,
  badge,
  canUp,
  canDown,
  onMove,
  onEdit,
  onDelete,
  deleteConfirm,
  extraAction,
  titleClassName = "text-xs font-semibold leading-relaxed",
}: {
  title: string;
  content: string;
  /** 标题旁的可选徽标（如随手备忘的任务类型标签） */
  badge?: ReactNode;
  canUp: boolean;
  canDown: boolean;
  onMove: (direction: -1 | 1) => void;
  onEdit: () => void;
  onDelete: () => void;
  deleteConfirm: string;
  extraAction?: ReactNode;
  /** 标题样式覆盖（默认小号深色；重要信息可传入放大标红） */
  titleClassName?: string;
}) {
  return (
    <li className="min-w-0 rounded-md border border-neutral-200 bg-white p-2">
      <div className="flex items-start gap-1">
        <div className="flex shrink-0 flex-col">
          <button onClick={() => onMove(-1)} disabled={!canUp} aria-label="上移记录" className="p-0.5 text-neutral-400 hover:text-neutral-700 disabled:opacity-30">
            <ArrowUp className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => onMove(1)} disabled={!canDown} aria-label="下移记录" className="p-0.5 text-neutral-400 hover:text-neutral-700 disabled:opacity-30">
            <ArrowDown className="h-3.5 w-3.5" />
          </button>
        </div>
        <span className={`min-w-0 flex-1 break-words ${titleClassName}`}>
          {title}
          {badge}
        </span>
        <div className="flex shrink-0 items-center gap-0.5">
          {extraAction}
          <button onClick={onEdit} aria-label="编辑记录" className="p-0.5 text-neutral-400 hover:text-neutral-700">
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => confirm(deleteConfirm) && onDelete()}
            aria-label="删除记录"
            className="p-0.5 text-neutral-400 hover:text-red-600"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      {content.trim() && (
        <SafeMarkdown
          text={content}
          className="mt-1 break-words pl-6 text-neutral-600"
        />
      )}
    </li>
  );
}
