import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { MorningReportPage } from "../pages/MorningReportPage";

const REPORT = {
  id: 1,
  report_date: "2026-11-10",
  version_no: 1,
  is_primary: true,
  status: "published",
  title: "今日晨报",
  sections: {},
  content_md: "# 今日晨报\n\n## 一、开篇速览\n\n今天值得关注的事。",
  window_start: "2026-11-09T08:00:00+08:00",
  window_end: "2026-11-10T08:00:00+08:00",
  snapshot_id: "snap-x",
  fact_check: { ok: true, issues: [] },
  generation_mode: "auto",
  created_at: "2026-11-10T08:05:00+08:00",
  evaluation: {
    status: "ok",
    scores: { 资讯呈现: 88, "内容逻辑与一致性": 86, "AI 技术分析": 90, "个人总结与建议": 84, 阅读体验: 87 },
    composite: 87,
    comment: "整体质量良好。",
    rule_version: "quality_score_v1",
  },
};

function makeFetchMock() {
  return vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/morning/report")) {
      return new Response(JSON.stringify(REPORT), { status: 200 });
    }
    if (url.includes("/api/morning/status")) {
      return new Response(
        JSON.stringify({
          db_ok: true, mr_schema_version: 1, schedule_enabled: true, today: "2026-11-10",
          today_run: { id: 5, status: "success", error: null, started_at: null, finished_at: null },
          news_counts: { domestic: 100, international: 44, ai: 20 },
        }),
        { status: 200 },
      );
    }
    if (url.includes("/api/morning/history")) {
      return new Response(JSON.stringify({ items: [
        { id: 1, report_date: "2026-11-10", version_no: 1, is_primary: true, status: "published",
          created_at: "2026-11-10T08:05:00+08:00", has_evaluation: true },
      ] }), { status: 200 });
    }
    if (url.includes("/api/morning/memory")) {
      return new Response(JSON.stringify([
        { id: 1, kind: "interest", content: "关注 AI Agent", enabled: true, confirmed: true,
          source: "manual", created_at: "", updated_at: "" },
      ]), { status: 200 });
    }
    return new Response(JSON.stringify({ detail: { code: "not_found", message: "not found" } }), { status: 404 });
  });
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <MorningReportPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MorningReportPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", makeFetchMock());
    localStorage.clear();
  });

  it("渲染晨报正文（五部分正文可见，标注主报告）", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("今天值得关注的事。")).toBeInTheDocument());
    expect(screen.getByText(/版本 v1（主报告）/)).toBeInTheDocument();
    expect(screen.getAllByText("今日晨报").length).toBeGreaterThan(0);
  });

  it("质量评价页显示程序计算的综合分与五维条", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("质量评价"));
    await waitFor(() => expect(screen.getAllByText("87").length).toBeGreaterThanOrEqual(2)); // 综合分+阅读体验分
    expect(screen.getByText(/quality_score_v1/)).toBeInTheDocument();
    expect(screen.getByText("AI 技术分析")).toBeInTheDocument();
  });

  it("历史晨报在弹窗中独立展示，可关闭、可下载", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("历史晨报"));
    fireEvent.click(await screen.findByText("2026-11-10"));
    // 弹窗打开：包含下载按钮与正文内容，正文页签不被替换
    await waitFor(() => expect(screen.getByText("下载 Markdown")).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getAllByText("今天值得关注的事。").length).toBeGreaterThanOrEqual(1),
    ); // 弹窗内正文渲染完成
    // 关闭弹窗
    fireEvent.click(screen.getByLabelText("关闭"));
    await waitFor(() => expect(screen.queryByText("下载 Markdown")).not.toBeInTheDocument());
  });

  it("重新生成触发后端调用", async () => {
    const fetchMock = makeFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    fireEvent.click(await screen.findByText("重新生成"));
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]));
      expect(calls.some((u) => u.includes("/api/morning/regenerate"))).toBe(true);
    });
  });

  it("Memory 管理面板可禁用记忆", async () => {
    const fetchMock = makeFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    fireEvent.click(await screen.findByText("Memory 管理"));
    const disableBtn = await screen.findByText("禁用");
    fireEvent.click(disableBtn);
    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes("/api/morning/memory/1") &&
          (c as unknown as [unknown, RequestInit?])[1]?.method === "PATCH",
      );
      expect(patchCall).toBeTruthy();
    });
  });
});
