import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AppLayout } from "../components/layout/AppLayout";
import { SafeMarkdown } from "../components/SafeMarkdown";

const INFO = { id: 1, title: "设计规范", content: "**简洁优先**", sort_order: 1 };

const MEMO = { id: 1, title: "搁置的想法", content: "多行\n内容", sort_order: 1 };

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

function renderLayout() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AppLayout>
          <div>业务区内容</div>
        </AppLayout>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("右侧常驻信息栏（PC 三栏工作台）", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("默认展开：重要信息与随手备忘常驻，中央区独立", async () => {
    vi.stubGlobal("fetch", makeFetchMock());
    renderLayout();
    expect(await screen.findByText("重要信息")).toBeInTheDocument();
    expect(screen.getByText("随手备忘")).toBeInTheDocument();
    expect(screen.getByText("业务区内容")).toBeInTheDocument();
    // 重要信息内容经 Markdown 渲染（加粗）
    expect(await screen.findByText("简洁优先")).toBeInTheDocument();
    // 折叠按钮存在
    expect(screen.getByRole("button", { name: "折叠右侧栏" })).toBeInTheDocument();
  });

  it("折叠与展开：状态存 localStorage，切换后内容仍在", async () => {
    vi.stubGlobal("fetch", makeFetchMock());
    renderLayout();
    await screen.findByText("重要信息");

    fireEvent.click(screen.getByRole("button", { name: "折叠右侧栏" }));
    // 折叠 = 容器加 hidden 类、组件保持挂载（内容不丢）
    const aside = (await screen.findByText("重要信息")).closest("aside");
    expect(aside?.className).toContain("hidden");
    expect(localStorage.getItem("hub.rightrail.collapsed")).toBe("1");

    fireEvent.click(screen.getByRole("button", { name: "展开右侧栏" }));
    expect((await screen.findByText("重要信息")).closest("aside")?.className).not.toContain("hidden");
    expect(localStorage.getItem("hub.rightrail.collapsed")).toBe("0");
  });

  it("默认从 localStorage 恢复折叠状态", async () => {
    localStorage.setItem("hub.rightrail.collapsed", "1");
    vi.stubGlobal("fetch", makeFetchMock());
    renderLayout();
    expect(screen.getByRole("button", { name: "展开右侧栏" })).toBeInTheDocument();
    // 折叠态：右栏容器 hidden（组件仍挂载，备忘草稿不丢）
    await waitFor(() => {
      expect((screen.getByText("随手备忘")).closest("aside")?.className).toContain("hidden");
    });
  });

  it("随手备忘：完整显示标题与内容、无展开收起按钮、提供转为每日任务", async () => {
    vi.stubGlobal("fetch", makeFetchMock());
    renderLayout();

    // 标题与内容完整显示（多行内容不换行截断）
    expect(await screen.findByText("搁置的想法")).toBeInTheDocument();
    expect(screen.getByText(/多行/)).toBeInTheDocument();
    // 无展开/收起按钮
    expect(screen.queryByRole("button", { name: /展开/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /收起/ })).not.toBeInTheDocument();
    // 转为每日任务入口
    expect(screen.getByRole("button", { name: "转为每日任务" })).toBeInTheDocument();
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
    renderLayout();
    // 右栏两个面板各有"新增"（重要信息在前、随手备忘在后），取第二个
    const addButtons = await screen.findAllByRole("button", { name: /新增/ });
    fireEvent.click(addButtons[addButtons.length - 1]);

    const emptyInputs = await screen.findAllByDisplayValue("");
    fireEvent.change(emptyInputs[0], { target: { value: "新备忘" } }); // 第一个为空的是标题
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect((posts[0] as { title: string }).title).toBe("新备忘");
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
