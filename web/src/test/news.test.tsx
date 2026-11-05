import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { NewsPage } from "../pages/NewsPage";
import { HomePage } from "../pages/HomePage";
import { NEWS_NAV_SITES } from "../lib/newsNav";

const TOP = {
  items: Array.from({ length: 10 }, (_, i) => ({
    id: i + 1,
    title: `热门资讯第 ${i + 1} 条`,
    url: `https://example.com/news-${i + 1}`,
    source: i % 2 === 0 ? "Hacker News" : "GitHub Blog",
    topic: "ai",
    published_at: new Date(Date.now() - (i + 1) * 3600_000).toISOString(),
    raw_summary: `这是第 ${i + 1} 条的原始摘要。`,
    title_zh: "",
    summary_zh: "",
    translate_status: "",
    score: 0.9 - i * 0.05,
    effective_score: 1.0 - i * 0.05,
    rank: i + 1,
  })),
  total: 10,
  generated_at: new Date().toISOString(),
};

function makeFetchMock(overrides: { top?: unknown } = {}) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/news/top")) {
      const payload = overrides.top ?? TOP;
      return new Response(JSON.stringify(payload), { status: 200 });
    }
    if (url === "/api/news/status") {
      return new Response(
        JSON.stringify({
          last_refresh: { refreshed_at: new Date().toISOString(), new_items: 10, sources: 7, failures: [] },
          refresh_minutes: 30,
          stale: false,
        }),
        { status: 200 }
      );
    }
    if (url === "/api/tasks/daily") return new Response(JSON.stringify([]), { status: 200 });
    if (url.includes("/api/books")) return new Response(JSON.stringify([]), { status: 200 });
    if (url === "/api/health") {
      return new Response(JSON.stringify({ status: "ok", service: "personal-assistant", version: "0.1.0" }), { status: 200 });
    }
    return new Response("not found", { status: 404 });
  });
}

function renderPage(page: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{page}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe("技术资讯页 TOP 10 + 导航", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("渲染完整 TOP 10 与四个导航入口，且不含废弃 UI", async () => {
    vi.stubGlobal("fetch", makeFetchMock());
    renderPage(<NewsPage />);

    // TOP 10 完整（10 条，带排名）
    for (let i = 1; i <= 10; i++) {
      expect(await screen.findByText(`热门资讯第 ${i} 条`)).toBeInTheDocument();
    }
    expect(screen.getByText("1")).toBeInTheDocument();
    // 导航入口
    for (const site of NEWS_NAV_SITES) {
      expect(screen.getAllByText(site.name).length).toBeGreaterThanOrEqual(1);
    }
    expect(screen.getAllByRole("link", { name: /打开网站/ })).toHaveLength(NEWS_NAV_SITES.length);
    // 废弃 UI 不存在：收藏/已读/筛选
    expect(screen.queryByRole("button", { name: "收藏" })).not.toBeInTheDocument();
    expect(screen.queryByText("标记已读")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("主题筛选")).not.toBeInTheDocument();
  });

  it("中文标题与摘要默认直接展示，点击展开完整内容（需求三）", async () => {
    const topZh = {
      ...TOP,
      items: TOP.items.map((item, i) => ({
        ...item,
        title_zh: `中文标题 ${i + 1}`,
        summary_zh: `中文摘要 ${i + 1}。`,
        translate_status: "done",
      })),
    };
    vi.stubGlobal("fetch", makeFetchMock({ top: topZh }));
    renderPage(<NewsPage />);

    // 默认直接展示中文标题与摘要（无需点击）
    expect(await screen.findByText("中文标题 1")).toBeInTheDocument();
    expect(screen.getByText(/中文摘要 1。/)).toBeInTheDocument();

    // 点击标题可展开完整摘要
    const titleButton = screen.getByRole("button", { name: "中文标题 1" });
    expect(titleButton.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(titleButton);
    expect(titleButton.getAttribute("aria-expanded")).toBe("true");

    // 原文链接安全打开
    const original = screen.getAllByRole("link", { name: /查看原文/ })[0];
    expect(original.getAttribute("href")).toBe("https://example.com/news-1");
    expect(original.getAttribute("target")).toBe("_blank");
    expect(original.getAttribute("rel")).toContain("noopener");
  });

  it("翻译缺失/失败回退原文，且无摘要不编造（需求三）", async () => {
    const fallback = {
      ...TOP,
      items: [
        {
          ...TOP.items[0],
          title: "English Title Only",
          title_zh: "",
          raw_summary: "",
          summary_zh: "",
          translate_status: "failed",
        },
      ],
      total: 1,
    };
    vi.stubGlobal("fetch", makeFetchMock({ top: fallback }));
    renderPage(<NewsPage />);

    // 回退英文原文标题；无摘要默认不展示编造内容
    expect(await screen.findByText("English Title Only")).toBeInTheDocument();
    expect(screen.queryByText("来源未提供摘要")).not.toBeInTheDocument();

    // 展开后明确提示来源未提供摘要
    fireEvent.click(screen.getByRole("button", { name: /English Title Only/ }));
    expect(await screen.findByText("来源未提供摘要")).toBeInTheDocument();
  });

  it("XSS 防护：资讯内容按纯文本渲染（需求九）", async () => {
    const evil = {
      ...TOP,
      items: [
        {
          ...TOP.items[0],
          title_zh: '<img src=x onerror="alert(1)">',
          summary_zh: '<script>alert(2)</script>',
          translate_status: "done",
        },
      ],
      total: 1,
    };
    vi.stubGlobal("fetch", makeFetchMock({ top: evil }));
    renderPage(<NewsPage />);

    // 恶意内容以纯文本展示，不生成恶意 img/script 元素
    expect(await screen.findByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
    expect(screen.getByText("<script>alert(2)</script>")).toBeInTheDocument();
    expect(document.querySelector('img[src="x"]')).toBeNull();
    expect(document.querySelector("script[src]")).toBeNull();
  });

  it("榜单为空时显示空状态提示", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetchMock({ top: { items: [], total: 0, generated_at: new Date().toISOString() } })
    );
    renderPage(<NewsPage />);
    expect(await screen.findByText(/还没有资讯/)).toBeInTheDocument();
  });
});

describe("首页计划管理卡片", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const TASK = (id: number, done: boolean, taskDate: string, important = false) => ({
    id,
    task_date: taskDate,
    title: `任务${id}`,
    content: null,
    task_type: "daily",
    done,
    sort_order: id,
    is_important: important,
    completed_at: done ? new Date().toISOString() : null,
    moved_from_date: null,
  });

  it("显示今日计划小标题，X/Y 与今日视图口径一致（含逾期未完成）", async () => {
    const today = new Date().toISOString().slice(0, 10);
    const yesterday = new Date(Date.now() - 86400_000).toISOString().slice(0, 10);
    const rows = [
      TASK(1, true, today),
      TASK(2, true, today),
      TASK(3, false, today, true), // 未完成且重要 → 展示在卡片列表
      TASK(4, false, yesterday), // 逾期未完成 → 计入 Y，不计入 X
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/news/")) return new Response("boom", { status: 500 });
        if (url.includes("/api/tasks/daily")) return new Response(JSON.stringify(rows), { status: 200 });
        if (url.includes("/api/books")) return new Response(JSON.stringify([]), { status: 200 });
        if (url === "/api/health") {
          return new Response(JSON.stringify({ status: "ok", service: "personal-assistant", version: "0.1.0" }), { status: 200 });
        }
        return new Response("not found", { status: 404 });
      })
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <HomePage />
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByText("今日计划")).toBeInTheDocument();
    // 视图口径：完成 2 / 总数 4（含逾期未完成）；findByText 等待任务查询返回
    expect(await screen.findByText("2/4 已完成")).toBeInTheDocument();
    // 只展示未完成的重要任务（任务3），不展示普通任务（任务4）
    expect(screen.getByText(/任务3/)).toBeInTheDocument();
    expect(screen.queryByText(/任务4/)).not.toBeInTheDocument();
  });
});

describe("首页 TOP 10", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("首页完整展示与资讯页相同的 TOP 10", async () => {
    vi.stubGlobal("fetch", makeFetchMock());
    renderPage(<HomePage />);

    for (let i = 1; i <= 10; i++) {
      expect(await screen.findByText(`热门资讯第 ${i} 条`)).toBeInTheDocument();
    }
    expect(screen.getByText("近期热门资讯 TOP 10")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /查看资讯导航/ })).toHaveAttribute("href", "/news");
  });

  it("资讯接口失败不影响首页其他模块", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/news/")) return new Response("boom", { status: 500 });
        if (url === "/api/tasks/daily") return new Response(JSON.stringify([]), { status: 200 });
        if (url.includes("/api/books")) return new Response(JSON.stringify([]), { status: 200 });
        if (url === "/api/health") {
          return new Response(JSON.stringify({ status: "ok", service: "personal-assistant", version: "0.1.0" }), { status: 200 });
        }
        return new Response("not found", { status: 404 });
      })
    );
    renderPage(<HomePage />);
    // 资讯区显示错误提示，其他模块照常
    expect(await screen.findByText(/资讯暂不可用/)).toBeInTheDocument();
    expect(screen.getByText("计划管理")).toBeInTheDocument();
    expect(screen.getByText("正在阅读")).toBeInTheDocument();
    expect(screen.getByText(/已连接/)).toBeInTheDocument();
  });
});
