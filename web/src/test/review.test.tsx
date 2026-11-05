import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ReviewPage } from "../pages/ReviewPage";

const REVIEW = {
  id: 1,
  week_start: "2026-06-01",
  week_end: "2026-06-07",
  status: "draft",
  stats: {
    week_start: "2026-06-01",
    week_end: "2026-06-07",
    tasks: {
      belonging: { total: 3, done: 2 },
      done_in_week: { total: 2, carried_in_done: { total: 0 } },
      created_in_week: 1,
      overdue_at_week_end: { total: 1 },
    },
    plans: { active: { total: 1 }, completed_in_week: [] },
    memos: { total: 2, stale: 1 },
    reading: { reading: [{ id: 1 }], notes_added_in_week: 0 },
  },
  analysis_md: "",
  user_notes: "",
  has_report: false,
  confirmed_at: null,
};

function makeSuggestions() {
  return [
    {
      id: 11,
      review_id: 1,
      seq: 0,
      content: "清理积压任务",
      basis: [
        { source_type: "daily_task", source_id: 1, reason: "已逾期", fact: "任务「x」（2026-05-20，未完成）" },
      ],
      is_general: false,
      status: "pending",
      final_content: null,
      reject_reason: "",
      resolved_at: null,
    },
    {
      id: 12,
      review_id: 1,
      seq: 1,
      content: "保持阅读习惯",
      basis: [],
      is_general: true,
      status: "pending",
      final_content: null,
      reject_reason: "",
      resolved_at: null,
    },
  ];
}

function sseResponse(events: object[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const event of events) controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } }
  );
}

interface StubState {
  generated: boolean;
  confirmed: boolean;
  suggestions: ReturnType<typeof makeSuggestions>;
}

function stubFetch(state: StubState) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/reviews" && init?.method === "POST") {
        return new Response(JSON.stringify(REVIEW), { status: 200 });
      }
      if (url === "/api/reviews") {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url === "/api/reviews/1/messages") {
        return new Response(JSON.stringify({ messages: [] }), { status: 200 });
      }
      if (url === "/api/reviews/1/suggestions/generate" && init?.method === "POST") {
        state.generated = true;
        return sseResponse([
          { type: "step", step: "collecting", text: "汇总对话与统计数据…" },
          { type: "done", suggestions: state.suggestions },
        ]);
      }
      if (url.includes("/api/reviews/suggestions/") && init?.method === "PUT") {
        const id = Number(url.split("/").pop());
        const body = JSON.parse(String(init.body));
        const target = state.suggestions.find((s) => s.id === id)!;
        const statusMap: Record<string, string> = {
          accept: "accepted",
          modify: "modified",
          reject: "rejected",
        };
        target.status = statusMap[body.action] ?? body.action;
        target.final_content = body.action === "modify" ? body.final_content : target.content;
        return new Response(JSON.stringify(target), { status: 200 });
      }
      if (url.endsWith("/api/reviews/1/confirm") && init?.method === "POST") {
        state.confirmed = true;
        return new Response(
          JSON.stringify({ ...REVIEW, status: "confirmed", confirmed_at: "now" }),
          { status: 200 }
        );
      }
      if (url.endsWith("/api/reviews/1/report")) {
        return new Response(
          JSON.stringify({
            status: "confirmed",
            report_md: "# 每周回顾（2026-06-01 ~ 2026-06-07）\n\n## 分析\n最终分析",
          }),
          { status: 200 }
        );
      }
      if (url.endsWith("/api/reviews/1")) {
        return new Response(
          JSON.stringify({
            ...REVIEW,
            status: state.confirmed ? "confirmed" : "draft",
            confirmed_at: state.confirmed ? "now" : null,
            suggestions: state.generated ? state.suggestions : [],
          }),
          { status: 200 }
        );
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
        <ReviewPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const GENERATE_BUTTON = /^(生成建议|重新生成)$/;

describe("每周回顾页面", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("加载草稿并渲染事实统计", async () => {
    stubFetch({ generated: false, confirmed: false, suggestions: makeSuggestions() });
    renderPage();
    await waitFor(() => expect(screen.getByText("本周任务")).toBeInTheDocument());
    expect(screen.getByText("2/3 完成")).toBeInTheDocument();
    expect(screen.getByText("回顾周期：2026-06-01 ~ 2026-06-07")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: GENERATE_BUTTON })).toBeInTheDocument();
  });

  it("生成建议后渲染依据与一般性建议标记，确认前阻止保存", async () => {
    stubFetch({ generated: false, confirmed: false, suggestions: makeSuggestions() });
    renderPage();
    await waitFor(() => expect(screen.getByRole("button", { name: GENERATE_BUTTON })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: GENERATE_BUTTON }));

    await waitFor(() => expect(screen.getByText("清理积压任务")).toBeInTheDocument());
    expect(screen.getByText(/任务「x」/)).toBeInTheDocument(); // 依据事实
    expect(screen.getByText("一般性建议")).toBeInTheDocument();
    // 有待处置建议 → 确认按钮禁用
    expect(screen.getByRole("button", { name: /确认保存周报/ })).toBeDisabled();
  });

  it("处置全部建议后可确认并展示正式周报", async () => {
    const state: StubState = { generated: false, confirmed: false, suggestions: makeSuggestions() };
    stubFetch(state);
    renderPage();
    await waitFor(() => expect(screen.getByRole("button", { name: GENERATE_BUTTON })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: GENERATE_BUTTON }));
    await waitFor(() => expect(screen.getByText("清理积压任务")).toBeInTheDocument());

    // 逐条接受两条建议（已处置卡片仍保留操作按钮，以状态徽标计数）
    const acceptButtons = screen.getAllByRole("button", { name: "接受" });
    fireEvent.click(acceptButtons[0]);
    await waitFor(() => expect(screen.getAllByText("已接受")).toHaveLength(1));
    fireEvent.click(screen.getAllByRole("button", { name: "接受" })[1]);
    await waitFor(() => expect(screen.getAllByText("已接受")).toHaveLength(2));

    const confirmButton = screen.getByRole("button", { name: /确认保存周报/ });
    await waitFor(() => expect(confirmButton).toBeEnabled());
    fireEvent.click(confirmButton);

    await waitFor(() => expect(screen.getByText("正式周报")).toBeInTheDocument());
    expect(screen.getByText(/每周回顾（2026-06-01/)).toBeInTheDocument();
    expect(screen.getByText("已确认正式周报（只读）")).toBeInTheDocument();
  });
});
