import { useEffect, useRef, useState } from "react";
import { Eye, Pencil } from "lucide-react";

import { Button } from "../ui/button";
import { SafeMarkdown } from "../SafeMarkdown";
import { ApiError } from "../../lib/api";
import { useMemo, useSaveMemo } from "../../api/infos";

const AUTOSAVE_DELAY_MS = 800;

type SaveState = "idle" | "saving" | "saved" | "error";

function stateLabel(state: SaveState): string {
  switch (state) {
    case "saving":
      return "保存中…";
    case "saved":
      return "已保存";
    case "error":
      return "保存失败";
    default:
      return "";
  }
}

/** 右侧栏下部：随手备忘（约 60% 高度，独立滚动，防抖自动保存）。 */
export function MemoPanel() {
  const memo = useMemo();
  const saveMemo = useSaveMemo();

  const [draft, setDraft] = useState<string | null>(null); // null = 尚未加载/以服务端为准
  const [savedContent, setSavedContent] = useState(""); // 最后一次成功保存（作 expected）
  const [state, setState] = useState<SaveState>("idle");
  const [preview, setPreview] = useState(false);
  const [conflict, setConflict] = useState(false);

  // 加载完成后初始化本地草稿（此后编辑不丢失：切换页面/折叠不卸载本组件）
  useEffect(() => {
    if (draft === null && memo.data) {
      setDraft(memo.data.content);
      setSavedContent(memo.data.content);
    }
  }, [draft, memo.data]);

  const timerRef = useRef<number | undefined>(undefined);
  const seqRef = useRef(0);

  const persist = (content: string, expected: string) => {
    const seq = ++seqRef.current;
    setState("saving");
    setConflict(false);
    saveMemo.mutate(
      { content, expected },
      {
        onSuccess: () => {
          if (seq !== seqRef.current) return; // 已有更新的保存在进行/完成，忽略旧结果
          setSavedContent(content);
          setState("saved");
        },
        onError: (error) => {
          if (seq !== seqRef.current) return;
          if (error instanceof ApiError && error.code === "memo_conflict") {
            setConflict(true); // 内容被其他修改覆盖：提示刷新，不用旧内容覆盖
          }
          setState("error");
        },
      }
    );
  };

  const handleChange = (value: string) => {
    setDraft(value);
    setState("saving");
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => persist(value, savedContent), AUTOSAVE_DELAY_MS);
  };

  // 卸载时如有未保存改动立即落盘（尽力而为）
  useEffect(
    () => () => {
      window.clearTimeout(timerRef.current);
    },
    []
  );

  const content = draft ?? memo.data?.content ?? "";

  return (
    <section className="flex min-h-0 flex-[3] flex-col">
      <div className="flex items-center justify-between px-3 py-2">
        <h2 className="text-xs font-semibold text-neutral-700">随手备忘</h2>
        <div className="flex items-center gap-2">
          <span
            aria-live="polite"
            className={`text-[11px] ${
              state === "error" ? "text-red-600" : state === "saved" ? "text-green-600" : "text-neutral-400"
            }`}
          >
            {stateLabel(state)}
          </span>
          <Button
            size="sm"
            variant="outline"
            className="h-6 px-2 text-xs"
            onClick={() => setPreview((v) => !v)}
            aria-label={preview ? "编辑备忘" : "预览备忘"}
          >
            {preview ? <Pencil className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            {preview ? " 编辑" : " 预览"}
          </Button>
        </div>
      </div>
      {conflict && (
        <div className="mx-3 mb-1 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] text-amber-700">
          备忘内容在其他地方被修改，请刷新页面后重试，避免相互覆盖。
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {preview ? (
          content.trim() ? (
            <SafeMarkdown text={content} className="rounded border border-neutral-100 bg-white p-2" />
          ) : (
            <div className="py-4 text-center text-xs text-neutral-400">（空备忘）</div>
          )
        ) : (
          <textarea
            value={content}
            onChange={(e) => handleChange(e.target.value)}
            placeholder={"随手记录想法、待研究问题、代码片段…\n支持 Markdown：# 标题、- 列表、``` 代码块"}
            aria-label="随手备忘"
            className="h-full min-h-40 w-full resize-none rounded border border-neutral-200 bg-white p-2 font-mono text-xs leading-relaxed focus:border-neutral-400 focus:outline-none"
          />
        )}
      </div>
    </section>
  );
}
