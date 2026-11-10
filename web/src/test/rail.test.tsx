import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { SafeMarkdown } from "../components/SafeMarkdown";
import { MemosPanel } from "../components/rail/MemosPanel";
import { ImportantInfosPanel } from "../components/rail/ImportantInfosPanel";

const INFO = { id: 1, title: "设计规范", content: "**简洁优先**", sort_order: 1 };

const MEMO = { id: 1, title: "搁置的想法", content: "多行\n内容", task_type: "", sort_order: 1 };

function makeFetchMock(overrides: { memos?: unknown } = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/infos") {
      return new Response(JSON.stringify([INFO]), { status: 200 });
    }
    if (url === "/api/memos" && init?.method === "POST") {
      return new Response(JSON.stringify({ ...MEMO, ...JSON.parse(String(init.body)) }), { status: 201 });
    }
    if (url === "/api/memos") {
      return new Response(JSON.stringify(overrides.memos ?? [MEMO]), { status: 200 });
    }
    return new Response("not found", { status: 404 });
  });
}

function renderPanels() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <div className="flex h-96 flex-col">
        <ImportantInfosPanel />
        <MemosPanel />
      </div>
    </QueryClientProvider>
  );
}

describe("重要信息 / 随手备忘面板（计划管理页内展示）", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("完整显示标题与内容、提供新增与一键转为每日任务", async () => {
    vi.stubGlobal("fetch", makeFetchMock());
    renderPanels();
    expect(await screen.findByText("重要信息")).toBeInTheDocument();
    expect(screen.getByText("随手备忘")).toBeInTheDocument();
    // 重要信息内容经 Markdown 渲染（加粗）
    expect(await screen.findByText("简洁优先")).toBeInTheDocument();
    // 备忘标题与内容完整显示；任务类型徽标（存量空类型回退“日常”）
    expect(await screen.findByText("搁置的想法")).toBeInTheDocument();
    expect(screen.getByText(/多行/)).toBeInTheDocument();
    expect(screen.getByText("日常")).toBeInTheDocument();
    // 一键转换入口（不再弹窗选择时间/类型）
    expect(screen.getByRole("button", { name: "转为每日任务" })).toBeInTheDocument();
  });

  it("备忘展示具体任务类型徽标（与每日计划同配色）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/infos") return new Response(JSON.stringify([INFO]), { status: 200 });
        if (url === "/api/memos") {
          return new Response(JSON.stringify([{ ...MEMO, id: 2, title: "功能想法", task_type: "idea" }]), { status: 200 });
        }
        return new Response("not found", { status: 404 });
      })
    );
    renderPanels();
    expect(await screen.findByText("功能想法")).toBeInTheDocument();
    expect(screen.getByText("奇思妙想")).toBeInTheDocument();
  });

  it("随手备忘新增：POST /api/memos", async () => {
    const posts: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/infos") return new Response(JSON.stringify([INFO]), { status: 200 });
        if (url === "/api/memos" && init?.method === "POST") {
          posts.push(JSON.parse(String(init.body)));
          return new Response(JSON.stringify({ ...MEMO, ...(posts[0] as object) }), { status: 201 });
        }
        if (url === "/api/memos") return new Response(JSON.stringify([MEMO]), { status: 200 });
        return new Response("not found", { status: 404 });
      })
    );
    renderPanels();
    // 两个面板各有"新增"（重要信息在前、随手备忘在后），取第二个
    const addButtons = await screen.findAllByRole("button", { name: /新增/ });
    fireEvent.click(addButtons[addButtons.length - 1]);

    const emptyInputs = await screen.findAllByDisplayValue("");
    fireEvent.change(emptyInputs[0], { target: { value: "新备忘" } }); // 第一个为空的是标题
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect((posts[0] as { title: string }).title).toBe("新备忘");
  });

  it("一键转换：POST /api/memos/:id/to_task（空 body，无时间/类型选择弹窗）", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/infos") return new Response(JSON.stringify([INFO]), { status: 200 });
        if (url === "/api/memos/1/to_task" && init?.method === "POST") {
          calls.push(String(init.body));
          return new Response(JSON.stringify({ id: 9 }), { status: 200 });
        }
        if (url === "/api/memos") return new Response(JSON.stringify([MEMO]), { status: 200 });
        return new Response("not found", { status: 404 });
      })
    );
    renderPanels();
    fireEvent.click(await screen.findByRole("button", { name: "转为每日任务" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toBe("{}"); // 不要求选择或填写时间/类型
    // 无确认弹窗残留
    expect(screen.queryByText("执行日期")).not.toBeInTheDocument();
  });
});

describe("SafeMarkdown 安全渲染", () => {
  it("渲染标题/列表/粗体/行内代码，且 HTML 按纯文本处理（XSS 安全）", () => {
    render(
      <SafeMarkdown
        text={"# 标题\n- **要点** 与 `code`\n<script>alert(1)</script>"}
      />
    );
    expect(screen.getByText("标题")).toBeInTheDocument();
    expect(screen.getByText("要点")).toBeInTheDocument();
    expect(screen.getByText("code")).toBeInTheDocument();
    // 恶意标签按纯文本展示，不生成 script 元素
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
    expect(document.querySelector("script[src]")).toBeNull();
  });

  it("非 http/https 链接降级为纯文本", () => {
    render(<SafeMarkdown text={"[点我](javascript:alert(1))"} />);
    expect(screen.getByText("点我")).toBeInTheDocument();
    expect(document.querySelector('a[href^="javascript"]')).toBeNull();
  });
});
