import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { PlansPage } from "../pages/PlansPage";
import { todayStr } from "../lib/api";

const TASK = {
  id: 1,
  plan_id: null,
  task_date: todayStr(),
  title: "写文档",
  done: false,
  sort_order: 1,
  moved_from_date: null,
};

function makeFetchMock(patchSpy: (body: unknown) => void) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/tasks/daily")) {
      return new Response(JSON.stringify([TASK]), { status: 200 });
    }
    if (url === "/api/plans") {
      return new Response(JSON.stringify([]), { status: 200 });
    }
    if (url === "/api/tasks/1" && init?.method === "PATCH") {
      patchSpy(JSON.parse(String(init.body)));
      return new Response(JSON.stringify({ ...TASK, done: true }), { status: 200 });
    }
    return new Response("not found", { status: 404 });
  });
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <PlansPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("计划管理页面", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("渲染每日任务并支持勾选完成", async () => {
    let patchBody: unknown = null;
    vi.stubGlobal("fetch", makeFetchMock((body) => (patchBody = body)));
    renderPage();

    expect(await screen.findByText("写文档")).toBeInTheDocument();
    expect(screen.getByText("长期计划")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "标记完成" }));
    await waitFor(() => expect(patchBody).toEqual({ done: true }));
  });

  it("新建任务提交 POST 并清空输入框", async () => {
    const posts: unknown[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/tasks/daily")) return new Response(JSON.stringify([]), { status: 200 });
      if (url === "/api/plans") return new Response(JSON.stringify([]), { status: 200 });
      if (url === "/api/tasks" && init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
        return new Response(JSON.stringify({ ...TASK, id: 9 }), { status: 201 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    const input = screen.getByPlaceholderText("添加任务，回车确认");
    fireEvent.change(input, { target: { value: "新任务" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(posts).toHaveLength(1));
    const body = posts[0] as { title: string; task_date: string };
    expect(body.title).toBe("新任务");
    expect(body.task_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("展示来自更早日期的未完成任务", async () => {
    const overdue = { ...TASK, id: 2, task_date: todayStr(-1), title: "逾期的任务" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/tasks/daily")) {
          return new Response(JSON.stringify([overdue, TASK]), { status: 200 });
        }
        if (url === "/api/plans") return new Response(JSON.stringify([]), { status: 200 });
        return new Response("not found", { status: 404 });
      })
    );
    renderPage();

    expect(await screen.findByText("未完成 · 来自更早日期")).toBeInTheDocument();
    expect(screen.getByText("逾期的任务")).toBeInTheDocument();
    expect(screen.getByText("写文档")).toBeInTheDocument();
    // 逾期任务不参与当日排序（只有今日任务的行才有排序按钮）
    expect(screen.getAllByRole("button", { name: "上移" })).toHaveLength(1);
  });
});
