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
  is_important: false,
  completed_at: null,
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
    const body = posts[0] as { title: string; task_date: string; plan_id?: number | null };
    expect(body.title).toBe("新任务");
    expect(body.task_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    // 需求五：新建不再携带关联长期计划
    expect(body.plan_id === undefined || body.plan_id === null).toBe(true);
  });

  it("不再显示关联长期计划入口（需求五）", async () => {
    vi.stubGlobal("fetch", makeFetchMock(() => {}));
    renderPage();
    await screen.findByText("写文档");
    expect(screen.queryByLabelText("关联长期计划")).not.toBeInTheDocument();
  });

  it("今日与逾期任务统一列表展示、统一排序按钮（需求二）", async () => {
    const overdue = {
      ...TASK,
      id: 2,
      task_date: todayStr(-1),
      title: "逾期的任务",
      moved_from_date: null,
    };
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

    // 统一列表：逾期任务直接展示并带原始日期徽标（不再有独立分区标题）
    expect(await screen.findByText("逾期的任务")).toBeInTheDocument();
    expect(screen.getByText(todayStr(-1))).toBeInTheDocument();
    expect(screen.queryByText("未完成 · 来自更早日期")).not.toBeInTheDocument();
    // 两行都可上移/下移（共 2 套按钮），可自由穿插
    expect(screen.getAllByRole("button", { name: "上移" })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "下移" })).toHaveLength(2);
  });

  it("已完成的任务复选框禁用（历史只读，需求四）", async () => {
    const done = { ...TASK, done: true };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/tasks/daily")) {
          return new Response(JSON.stringify([done]), { status: 200 });
        }
        if (url === "/api/plans") return new Response(JSON.stringify([]), { status: 200 });
        return new Response("not found", { status: 404 });
      })
    );
    renderPage();

    expect(await screen.findByText("写文档")).toBeInTheDocument();
    const checkbox = screen.getByRole("button", { name: "已完成（历史只读）" });
    expect(checkbox).toBeDisabled();
  });

  it("重要任务红色强调并可切换（需求一）", async () => {
    const important = { ...TASK, is_important: true };
    let patchBody: unknown = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/tasks/daily")) {
          return new Response(JSON.stringify([important]), { status: 200 });
        }
        if (url === "/api/plans") return new Response(JSON.stringify([]), { status: 200 });
        if (url === "/api/tasks/1" && init?.method === "PATCH") {
          patchBody = JSON.parse(String(init.body));
          return new Response(JSON.stringify(TASK), { status: 200 });
        }
        return new Response("not found", { status: 404 });
      })
    );
    renderPage();

    await screen.findByText("写文档");
    // 红色强调样式（浅红背景 + 红色标题）
    expect(screen.getByText("写文档").className).toContain("text-red-700");
    expect(screen.getByText("写文档").closest("li")?.className).toContain("bg-red-50");

    // 点击星标 → PATCH is_important
    fireEvent.click(screen.getByRole("button", { name: "取消重要" }));
    await waitFor(() => expect(patchBody).toEqual({ is_important: false }));
  });

  it("长期计划标记完成需确认，取消不执行（需求二）", async () => {
    const plan = {
      id: 5,
      title: "学习计划",
      description: "",
      status: "in_progress",
      target_date: null,
      is_important: false,
      sort_order: 1,
      completed_at: null,
    };
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/tasks/daily")) return new Response(JSON.stringify([]), { status: 200 });
        if (url === "/api/plans") return new Response(JSON.stringify([plan]), { status: 200 });
        if (url === "/api/plans/5/complete" && init?.method === "POST") {
          calls.push("complete");
          return new Response(JSON.stringify({ ...plan, status: "completed" }), { status: 200 });
        }
        return new Response("not found", { status: 404 });
      })
    );
    renderPage();

    await screen.findByText("学习计划");
    fireEvent.click(screen.getByRole("button", { name: "标记完成" }));

    // 确认弹窗文案（需求二指定文案）
    expect(await screen.findByText("确认将该长期计划标记为已完成吗？完成后将移入历史计划。")).toBeInTheDocument();

    // 取消 → 不执行
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(calls).toHaveLength(0);

    // 再次打开并确认 → 执行
    fireEvent.click(screen.getByRole("button", { name: "标记完成" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认完成" }));
    await waitFor(() => expect(calls).toEqual(["complete"]));
  });

  it("长期计划与每日计划均有历史入口（需求二/六）", async () => {
    vi.stubGlobal("fetch", makeFetchMock(() => {}));
    renderPage();
    await screen.findByText("写文档");
    // 两个面板各一个"历史"按钮
    expect(screen.getAllByRole("button", { name: /历史/ })).toHaveLength(2);
  });
});
