import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { CleanupBanner } from "../pages/CleanupPage";

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
