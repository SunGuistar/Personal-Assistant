import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Github as GithubIcon, RefreshCw } from "lucide-react";

import { Button } from "../components/ui/button";
import { useJob } from "../api/wechat";
import {
  ContributionDay,
  DayDetail,
  getContributionDetail,
  getContributions,
  getGithubStatus,
  startGithubSync,
} from "../api/github";

/** GitHub 浅色主题五级配色（白底：无贡献浅灰，绿色由浅到深，与 Less–More 图例共用） */
const LEVEL_COLORS = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"];
const CELL = 11;
const GAP = 3;
const LABEL_FONT_PX = 10;
const LABEL_CHAR_WIDTH = 5.6; // 10px 字号下保守字符宽，用于月份标签防重叠估算
const LABEL_MIN_GAP = 8; // 相邻月份标签最小视觉间距（px）
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function formatTooltipText(day: ContributionDay): string {
  const [year, month, date] = day.date.split("-").map(Number);
  const countText = day.count > 0 ? `${day.count} contribution${day.count > 1 ? "s" : ""}` : "No contributions";
  return `${MONTHS[month - 1]} ${date}, ${year}: ${countText}`;
}

interface WeekColumn {
  /** 列内 7 格（周一→周日）；null = 年份外占位 */
  cells: (ContributionDay | null)[];
  /** 该列首个有效日期的月份（1-12），跨月列用于月份标签 */
  monthOfFirst: number | null;
}

/** 把全年日期排成"列=周、行=周一~周日"的矩阵（GitHub 布局） */
function buildColumns(days: ContributionDay[]): WeekColumn[] {
  if (days.length === 0) return [];
  const year = Number(days[0].date.slice(0, 4));
  const jan1 = new Date(year, 0, 1);
  const offset = (jan1.getDay() + 6) % 7; // 周一=0

  const makeColumn = (cells: (ContributionDay | null)[]): WeekColumn => {
    const valid = cells.filter((c): c is ContributionDay => c !== null);
    return { cells, monthOfFirst: valid.length > 0 ? Number(valid[0].date.slice(5, 7)) : null };
  };

  const columns: WeekColumn[] = [];
  let current: (ContributionDay | null)[] = new Array<ContributionDay | null>(offset).fill(null);
  for (const day of days) {
    if (current.length === 7) {
      columns.push(makeColumn(current));
      current = [];
    }
    current.push(day);
  }
  if (current.length > 0) {
    while (current.length < 7) current.push(null);
    columns.push(makeColumn(current));
  }
  return columns;
}

export function GithubPage() {
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);
  const [syncTaskId, setSyncTaskId] = useState<number | null>(null);

  const status = useQuery({ queryKey: ["github-status"], queryFn: getGithubStatus, retry: 1 });
  const syncJob = useJob(syncTaskId);
  const contributions = useQuery({
    queryKey: ["github-contributions", year],
    queryFn: () => getContributions(year),
    retry: 1,
  });

  useEffect(() => {
    if (syncJob.data?.status === "success" || syncJob.data?.status === "failed") {
      setSyncTaskId(null);
      status.refetch();
      contributions.refetch();
    }
  }, [syncJob.data?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const syncing = syncJob.data?.status === "pending" || syncJob.data?.status === "running";

  const sync = async () => {
    try {
      const result = await startGithubSync();
      setSyncTaskId(result.task_id);
    } catch {
      status.refetch();
    }
  };

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-3">
      <h1 className="text-xl font-semibold">GitHub 数据</h1>

      {/* 同步控制区 */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs">
        <GithubIcon className="h-4 w-4 text-neutral-600" />
        {!status.data?.configured ? (
          <span className="text-amber-600">未配置 GITHUB_TOKEN（在 ~/.personal-hub/.env 设置后同步）</span>
        ) : (
          <span className="text-neutral-600">
            {status.data.repos} 仓库 · {status.data.commits} commits · {status.data.pull_requests} PRs ·{" "}
            {status.data.issues} issues
            {status.data.last_sync && ` · 上次同步 ${status.data.last_sync.updated_at?.slice(0, 16) ?? ""}`}
          </span>
        )}
        <Button size="sm" variant="outline" onClick={sync} disabled={syncing || !status.data?.configured}>
          <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
          {syncing ? `同步中 ${syncJob.data?.progress ?? 0}%` : "同步 GitHub 数据"}
        </Button>
        {syncJob.data?.status === "failed" && (
          <span className="text-red-500">同步失败:{syncJob.data.error}</span>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <ContributionGraph
          year={year}
          currentYear={currentYear}
          onYearChange={setYear}
          data={contributions.data ?? null}
          loading={contributions.isLoading}
        />
      </div>
    </div>
  );
}

function ContributionGraph({
  year,
  currentYear,
  onYearChange,
  data,
  loading,
}: {
  year: number;
  currentYear: number;
  onYearChange: (year: number) => void;
  data: import("../api/github").Contributions | null;
  loading: boolean;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);
  const detail = useQuery({
    queryKey: ["github-day", selected],
    queryFn: () => getContributionDetail(selected!),
    enabled: selected !== null,
    retry: 1,
  });

  const columns = useMemo(() => buildColumns(data?.days ?? []), [data?.days]);

  const columnWidth = CELL + GAP;
  const graphWidth = columns.length * columnWidth;

  // 部分覆盖提示：synced 但首尾未铺满整年
  const coverage = data?.coverage;
  const partialCoverage =
    !!coverage &&
    coverage.synced &&
    ((coverage.from ?? "") > `${year}-01-01` || (coverage.to ?? "") < `${year}-12-31`);

  // 月份标签：月份首变的列放置标签；贪心防重叠——同月不重复、与前一个已放置
  // 标签估算宽度间距不足 8px 时跳过（对齐不变形、不缩小字号、不粘连）
  const monthLabels: { col: number; label: string }[] = [];
  let lastLabelEnd = -Infinity;
  let lastLabelMonth: number | null = null;
  columns.forEach((column, index) => {
    if (column.monthOfFirst === null || column.monthOfFirst === lastLabelMonth) return;
    const left = index * columnWidth;
    if (left <= lastLabelEnd + LABEL_MIN_GAP) return;
    const label = MONTHS[column.monthOfFirst - 1];
    monthLabels.push({ col: index, label });
    lastLabelEnd = left + label.length * LABEL_CHAR_WIDTH;
    lastLabelMonth = column.monthOfFirst;
  });

  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-4">
      {/* 标题 + 年份切换 */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">
          {data ? `${data.total.toLocaleString()} contributions in ${year}` : `Contribution graph · ${year}`}
        </h2>
        <div className="ml-auto flex items-center gap-1 text-xs">
          <button
            aria-label="上一年"
            className="rounded border border-neutral-300 px-2 py-0.5 hover:bg-neutral-100 disabled:opacity-40"
            onClick={() => {
              setSelected(null);
              onYearChange(year - 1);
            }}
          >
            ‹
          </button>
          <span className="px-1 font-medium">{year}</span>
          <button
            aria-label="下一年"
            className="rounded border border-neutral-300 px-2 py-0.5 hover:bg-neutral-100 disabled:opacity-40"
            disabled={year >= currentYear}
            onClick={() => {
              setSelected(null);
              onYearChange(year + 1);
            }}
          >
            ›
          </button>
        </div>
      </div>

      {/* 覆盖范围提示：区分"未同步"与"零贡献" */}
      {data && !data.coverage.synced && (
        <div className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          该年份 GitHub 数据尚未同步——下方零贡献不代表真实活动，请点击上方"同步 GitHub 数据"。
        </div>
      )}
      {partialCoverage && (
        <div className="mb-3 rounded-md border border-neutral-300 bg-neutral-50 px-3 py-2 text-xs text-neutral-600">
          数据覆盖 {coverage?.from} ~ {coverage?.to}，范围外的零贡献不代表真实活动。
        </div>
      )}

      {loading ? (
        <div className="py-10 text-center text-sm text-neutral-400">加载中…</div>
      ) : (
        <>
          <div className="overflow-x-auto pb-1">
            <div className="relative" style={{ width: graphWidth + 30 }}>
              {/* 月份标签行 */}
              <div className="relative mb-1 h-4" style={{ width: graphWidth }}>
                {monthLabels.map((label) => (
                  <span
                    key={`${label.col}-${label.label}`}
                    className="absolute top-0 text-neutral-400"
                    style={{ left: label.col * columnWidth, fontSize: LABEL_FONT_PX }}
                  >
                    {label.label}
                  </span>
                ))}
              </div>
              <div className="flex">
                {/* 星期标签（周一/周三/周五） */}
                <div className="mr-1 flex flex-col text-[10px] text-neutral-400" style={{ gap: GAP, width: 24 }}>
                  {["Mon", "", "Wed", "", "Fri", "", ""].map((label, row) => (
                    <span key={row} style={{ height: CELL, lineHeight: `${CELL}px` }}>
                      {label}
                    </span>
                  ))}
                </div>
                {/* 方格矩阵：列=周，行=周一~周日 */}
                <div
                  className="grid"
                  style={{
                    gridTemplateRows: `repeat(7, ${CELL}px)`,
                    gridAutoFlow: "column",
                    gap: GAP,
                    width: graphWidth,
                  }}
                >
                  {columns.flatMap((column, colIndex) =>
                    column.cells.map((day, rowIndex) =>
                      day === null ? (
                        <span key={`${colIndex}-${rowIndex}`} />
                      ) : (
                        <button
                          key={day.date}
                          aria-label={formatTooltipText(day)}
                          onMouseEnter={(e) => {
                            const rect = (e.target as HTMLElement).getBoundingClientRect();
                            setTooltip({ x: rect.left, y: rect.top - 8, text: formatTooltipText(day) });
                          }}
                          onMouseLeave={() => setTooltip(null)}
                          onClick={() => setSelected(day.date)}
                          className={`rounded-[2px] outline-none transition-opacity hover:opacity-80 focus:ring-2 focus:ring-neutral-400 ${selected === day.date ? "ring-2 ring-neutral-500" : ""}`}
                          style={{ backgroundColor: LEVEL_COLORS[day.level], width: CELL, height: CELL }}
                        />
                      )
                    )
                  )}
                </div>
              </div>
              {/* Less / More 图例 */}
              <div className="mt-2 flex items-center gap-1 text-[10px] text-neutral-500">
                Less
                {LEVEL_COLORS.map((color) => (
                  <span key={color} className="rounded-[2px]" style={{ backgroundColor: color, width: CELL, height: CELL }} />
                ))}
                More
              </div>
            </div>
          </div>

          {/* 日期详情 */}
          {selected && (
            <DayDetailPanel
              date={selected}
              detail={detail.data ?? null}
              loading={detail.isLoading}
              onClose={() => setSelected(null)}
            />
          )}
        </>
      )}

      {tooltip && (
        <div
          className="pointer-events-none fixed z-50 -translate-x-1/2 -translate-y-full rounded-md bg-neutral-900 px-2 py-1 text-xs text-white shadow"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          {tooltip.text}
        </div>
      )}
    </section>
  );
}

const TYPE_LABEL: Record<string, string> = {
  commit: "Commit",
  pull_request: "Pull Request",
  issue: "Issue",
};

function DayDetailPanel({
  date,
  detail,
  loading,
  onClose,
}: {
  date: string;
  detail: DayDetail | null;
  loading: boolean;
  onClose: () => void;
}) {
  return (
    <div className="mt-3 rounded-md border border-neutral-200 bg-neutral-50 p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold">{date} 的活动</h3>
        <button className="text-xs text-neutral-400 hover:text-neutral-700" onClick={onClose}>
          关闭
        </button>
      </div>
      {loading ? (
        <div className="py-4 text-center text-xs text-neutral-400">加载中…</div>
      ) : !detail || detail.items.length === 0 ? (
        <div className="py-4 text-center text-xs text-neutral-400">这一天没有 GitHub 活动记录</div>
      ) : (
        <ul className="space-y-1.5">
          {detail.items.map((item, index) => (
            <li key={index} className="flex items-center gap-2 text-xs">
              <span
                className={`shrink-0 rounded-full px-2 py-0.5 ${
                  item.type === "commit"
                    ? "bg-green-100 text-green-700"
                    : item.type === "pull_request"
                      ? "bg-blue-100 text-blue-700"
                      : "bg-amber-100 text-amber-700"
                }`}
              >
                {TYPE_LABEL[item.type]}
              </span>
              <span className="shrink-0 text-neutral-400">{item.repo}</span>
              {item.url ? (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="min-w-0 flex-1 truncate text-neutral-700 hover:text-blue-600 hover:underline"
                >
                  {item.title}
                </a>
              ) : (
                <span className="min-w-0 flex-1 truncate text-neutral-700">{item.title}</span>
              )}
              <span className="shrink-0 text-neutral-400">{(item.time || "").slice(5, 16).replace("T", " ")}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
