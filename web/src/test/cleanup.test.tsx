import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { CleanupBanner, CleanupPage } from "../pages/CleanupPage";

const RULES = {
  keep_days: 7,
  protected_dates: ["2026-10-27"],
  timezone: "Asia/Shanghai",
  schedule: "每周日生成审核周期",
  age_rule: "仅早于保留期的消息进入候选",
  protection_rule: "永久保护日期整组排除",
  chunk_policy: "chunk 保守处置",
  dedupe_rule: "跨周去重",
  execute_rule: "人工勾选并二次确认后执行",
  conflict_rule: "与微信同步互斥",
};

const REVIEW_WITH_SUMMARY = {
  id: 1,
  week_id: "2026-11-01",
  status: "pending",
  summary: "本周扫描微信聊天缓存，共 2 组消息超过 7 天保留期进入候选：快照 6 条。",
  confirmed_at: null,
  reviewed_at: null,
  candidates: [],
};

function renderCleanupPage() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/cleanup/rules")) {
        return new Response(JSON.stringify(RULES), { status: 200 });
      }
      if (url.includes("/api/cleanup/status")) {
        return new Response(
          JSON.stringify({ banner: null, reviews: [{ ...REVIEW_WITH_SUMMARY, candidates: undefined }] }),
          { status: 200 }
        );
      }
      if (url.includes("/api/cleanup/reviews/1")) {
        return new Response(JSON.stringify(REVIEW_WITH_SUMMARY), { status: 200 });
      }
      return new Response(JSON.stringify({ banner: null, reviews: [] }), { status: 200 });
    })
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CleanupPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function renderBanner(status: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(status), { status: 200 }))
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CleanupBanner />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("首页清理提醒横幅", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("有待处理候选时显示横幅（含立即审核/稍后按钮）", async () => {
    renderBanner({
      banner: { review_id: 1, week_id: "2026-11-01", status: "pending", candidate_groups: 3 },
      reviews: [],
    });
    expect(await screen.findByText(/本周待清理数据审核/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "立即审核" })).toHaveAttribute("href", "/cleanup");
    expect(screen.getByRole("button", { name: "稍后" })).toBeInTheDocument();
  });

  it("候选为 0 时不显示横幅", async () => {
    renderBanner({ banner: null, reviews: [{ id: 1, week_id: "2026-11-01", status: "pending", candidates: [] }] });
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(0));
    expect(screen.queryByText(/待清理数据审核/)).not.toBeInTheDocument();
  });

  it("稍后（dismissed）不显示横幅，审核页入口不受影响", async () => {
    renderBanner({
      banner: { review_id: 1, week_id: "2026-11-01", status: "dismissed", candidate_groups: 3 },
      reviews: [],
    });
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(0));
    expect(screen.queryByText(/待清理数据审核/)).not.toBeInTheDocument();
  });

  it("点击稍后调用 dismiss API", async () => {
    const calls: string[] = [];
    let dismissed = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/dismiss") && init?.method === "POST") {
          calls.push(url);
          dismissed = true;
        }
        return new Response(
          JSON.stringify({
            banner: dismissed
              ? null
              : { review_id: 1, week_id: "2026-11-01", status: "pending", candidate_groups: 3 },
            reviews: [],
          }),
          { status: 200 }
        );
      })
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <CleanupBanner />
        </MemoryRouter>
      </QueryClientProvider>
    );
    fireEvent.click(await screen.findByRole("button", { name: "稍后" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toContain("/api/cleanup/reviews/1/dismiss");
    // dismiss 后横幅隐藏
    await waitFor(() => expect(screen.queryByText(/待清理数据审核/)).not.toBeInTheDocument());
  });
});

describe("清理审核页：生效规则与审核说明", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("完整展示当前实际生效的审核规则（非摘要）", async () => {
    renderCleanupPage();
    expect(await screen.findByText("当前生效的清理规则")).toBeInTheDocument();
    expect(await screen.findByText("每周日生成审核周期")).toBeInTheDocument();
    expect(screen.getByText("永久保护日期整组排除")).toBeInTheDocument();
    expect(screen.getByText("chunk 保守处置")).toBeInTheDocument();
    expect(screen.getByText("人工勾选并二次确认后执行")).toBeInTheDocument();
    expect(screen.getByText(/2026-10-27/)).toBeInTheDocument();
  });

  it("展示与审核记录关联的审核说明", async () => {
    renderCleanupPage();
    expect(await screen.findByText("审核说明：")).toBeInTheDocument();
    expect(screen.getByText(/共 2 组消息超过 7 天保留期进入候选/)).toBeInTheDocument();
  });
});
