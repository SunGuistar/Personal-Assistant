import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { GithubPage } from "../pages/GithubPage";

function makeDays(year: number, counts: Record<string, number>) {
  const days = [];
  const start = new Date(year, 0, 1);
  while (start.getFullYear() === year) {
    const iso = `${year}-${String(start.getMonth() + 1).padStart(2, "0")}-${String(start.getDate()).padStart(2, "0")}`;
    const count = counts[iso] ?? 0;
    const level = count >= 9 ? 4 : count >= 6 ? 3 : count >= 3 ? 2 : count >= 1 ? 1 : 0;
    days.push({ date: iso, count, level });
    start.setDate(start.getDate() + 1);
  }
  return days;
}

const STATUS = {
  configured: true,
  repos: 2,
  commits: 10,
  pull_requests: 3,
  issues: 1,
  last_sync: { status: "success", error: null, updated_at: "2026-11-06T10:00:00" },
};

const DETAIL = {
  date: "2024-02-29",
  items: [
    {
      type: "commit",
      repo: "me/demo",
      title: "fix graph",
      time: "2024-02-29T09:30:00+08:00",
      url: "https://github.com/me/demo/commit/x",
    },
  ],
};

function stubFetch(countsByYear: Record<number, Record<string, number>>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/github/status")) {
        return new Response(JSON.stringify(STATUS), { status: 200 });
      }
      const match = url.match(/contributions\?year=(\d+)/);
      if (match) {
        const year = Number(match[1]);
        const counts = countsByYear[year] ?? {};
        const days = makeDays(year, counts);
        const synced = year in countsByYear;
        const dates = Object.keys(counts).sort();
        return new Response(
          JSON.stringify({
            year,
            total: Object.values(counts).reduce((a, b) => a + b, 0),
            days,
            coverage: {
              synced,
              from: synced ? dates[0] : null,
              to: synced ? dates[dates.length - 1] : null,
            },
            counting_note: "test note",
          }),
          { status: 200 }
        );
      }
      const detail = url.match(/contributions\/(\d{4}-\d{2}-\d{2})/);
      if (detail) {
        const payload = detail[1] === "2024-02-29" ? DETAIL : { date: detail[1], items: [] };
        return new Response(JSON.stringify(payload), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    })
  );
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <GithubPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}


/** 点击"上一年"直到目标年份（模拟真实年份切换）。 */
async function gotoYear(target: number) {
  for (let guard = 0; guard < 10; guard++) {
    const yearText = screen.getByText(/^\d{4}$/);
    const current = Number(yearText.textContent);
    if (current === target) return;
    fireEvent.click(screen.getByRole("button", { name: "上一年" }));
    await waitFor(() => expect(screen.getByText(String(current - 1))).toBeInTheDocument());
  }
  throw new Error(`无法切换到年份 ${target}`);
}

describe("GitHub 贡献热力图", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("闰年 366 格、月份标签与标题正确", async () => {
    stubFetch({ 2024: { "2024-02-29": 5 } });
    renderPage();
    await gotoYear(2024);
    await waitFor(() => expect(screen.getByText("5 contributions in 2024")).toBeInTheDocument());
    const cells = screen.getAllByRole("button", { name: /contributions?|No contributions/ });
    expect(cells).toHaveLength(366);
    expect(screen.getByText("January")).toBeInTheDocument();
    expect(screen.getByText("December")).toBeInTheDocument();
    expect(screen.getByText("February")).toBeInTheDocument();
  });

  it("悬停显示 tooltip，点击方格加载当日详情", async () => {
    stubFetch({ 2024: { "2024-02-29": 1 } });
    renderPage();
    await gotoYear(2024);
    const cell = await screen.findByRole("button", { name: "February 29, 2024: 1 contribution" });
    fireEvent.mouseEnter(cell);
    expect(screen.getByText("February 29, 2024: 1 contribution")).toBeInTheDocument();
    fireEvent.mouseLeave(cell);

    fireEvent.click(cell);
    await waitFor(() => expect(screen.getByText("fix graph")).toBeInTheDocument());
    expect(screen.getByText("me/demo")).toBeInTheDocument();
    expect(screen.getByText("Commit")).toBeInTheDocument();
  });

  it("未同步年份显示提示而非零贡献，未来年份禁止切换", async () => {
    stubFetch({});
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/该年份 GitHub 数据尚未同步/)).toBeInTheDocument()
    );
    // 当前年份禁止前往未来；切到上一年后允许前进，且空数据年份同样提示未同步
    expect(screen.getByRole("button", { name: "下一年" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "上一年" }));
    await waitFor(() => expect(screen.getByText(/该年份 GitHub 数据尚未同步/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "下一年" })).toBeEnabled();
  });

  it("无活动日期点击显示空状态", async () => {
    stubFetch({ 2024: { "2024-02-29": 1 } });
    renderPage();
    await gotoYear(2024);
    const empty = await screen.findByRole("button", { name: "March 1, 2024: No contributions" });
    fireEvent.click(empty);
    await screen.findByText("这一天没有 GitHub 活动记录");
  });
});
