import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AppLayout } from "../components/layout/AppLayout";
import { SafeMarkdown } from "../components/SafeMarkdown";

const INFO = { id: 1, title: "设计规范", content: "**简洁优先**", sort_order: 1 };

function makeFetchMock(overrides: { memo?: string; putSpy?: (body: unknown) => void } = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/infos") {
      return new Response(JSON.stringify([INFO]), { status: 200 });
    }
    if (url === "/api/memo" && init?.method === "PUT") {
      overrides.putSpy?.(JSON.parse(String(init.body)));
      return new Response(JSON.stringify({ content: "ok" }), { status: 200 });
    }
    if (url === "/api/memo") {
      return new Response(JSON.stringify({ content: overrides.memo ?? "" }), { status: 200 });
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

  it("备忘自动保存：防抖后 PUT，状态显示已保存", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const puts: unknown[] = [];
      vi.stubGlobal("fetch", makeFetchMock({ putSpy: (body) => puts.push(body) }));
      renderLayout();
      const textarea = await screen.findByLabelText("随手备忘");

      fireEvent.change(textarea, { target: { value: "# 想法" } });
      expect(puts).toHaveLength(0); // 防抖未触发
      await vi.advanceTimersByTimeAsync(900);
      await waitFor(() => expect(puts).toHaveLength(1));
      expect((puts[0] as { content: string }).content).toBe("# 想法");
      expect(await screen.findByText("已保存")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
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
