import { Star } from "lucide-react";

/** 通用重要星标按钮（计划/任务/书籍同一视觉规范：重要红色实心）。 */
export function StarButton({
  important,
  onToggle,
  className = "",
}: {
  important: boolean;
  onToggle: () => void;
  className?: string;
}) {
  return (
    <button
      onClick={onToggle}
      aria-label={important ? "取消重要" : "标记重要"}
      className={`p-1 ${important ? "text-red-500" : "text-neutral-300 hover:text-red-400"} ${className}`}
    >
      <Star className="h-4 w-4" fill={important ? "currentColor" : "none"} />
    </button>
  );
}

/** 重要行红色强调：浅红背景 + 左侧红色标识（与整体 UI 协调）。 */
export function importantRowClass(isImportant: boolean): string {
  return isImportant ? "border-l-2 border-red-400 bg-red-50/60" : "border-l-2 border-transparent";
}
