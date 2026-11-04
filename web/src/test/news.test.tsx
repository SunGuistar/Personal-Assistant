import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { NewsPage } from "../pages/NewsPage";
import { HomePage } from "../pages/HomePage";
import { NEWS_NAV_SITES } from "../lib/newsNav";

function renderPage(page: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{page}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe("技术资讯导航页", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("渲染四个默认网站入口（名称、介绍、打开按钮）", () => {
    renderPage(<NewsPage />);
    for (const site of NEWS_NAV_SITES) {
      expect(screen.getAllByText(site.name).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(site.description)).toBeInTheDocument();
    }
    expect(screen.getAllByRole("link", { name: /打开网站/ })).toHaveLength(NEWS_NAV_SITES.length);
  });

  it("外部链接地址正确且在新标签页安全打开", () => {
    renderPage(<NewsPage />);
    const links = screen.getAllByRole("link", { name: /打开网站/ });
    const hrefs = links.map((link) => link.getAttribute("href"));
    expect(hrefs).toEqual(NEWS_NAV_SITES.map((s) => s.url));
    for (const link of links) {
      expect(link.getAttribute("target")).toBe("_blank");
      expect(link.getAttribute("rel")).toContain("noopener");
    }
  });

  it("无需新闻 API 即可渲染（零请求）", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderPage(<NewsPage />);
    expect(screen.getAllByText(NEWS_NAV_SITES[0].name).length).toBeGreaterThanOrEqual(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("首页技术资讯导航", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("展示主要入口且不影响其他模块请求", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/tasks/daily")) return new Response(JSON.stringify([]), { status: 200 });
        if (url.includes("/api/books")) return new Response(JSON.stringify([]), { status: 200 });
        if (url === "/api/health") {
          return new Response(JSON.stringify({ status: "ok", service: "personal-assistant", version: "0.1.0" }), { status: 200 });
        }
        return new Response("not found", { status: 404 });
      })
    );
    renderPage(<HomePage />);

    expect(await screen.findByText("技术资讯导航")).toBeInTheDocument();
    // 3-4 个入口，全部新标签页打开
    const links = screen.getAllByRole("link", { name: /daily\.dev|LLM Digest|HotAI\.news|Edition/ });
    expect(links.length).toBeGreaterThanOrEqual(3);
    expect(links.length).toBeLessThanOrEqual(4);
    for (const link of links) {
      expect(link.getAttribute("target")).toBe("_blank");
    }
    // 首页不应请求任何新闻抓取 API
    const requested = (vi.mocked(fetch).mock.calls.map((c) => String(c[0])) as string[]);
    expect(requested.some((u) => u.includes("/api/news/"))).toBe(false);
    // 其他模块照常
    expect(screen.getByText("今日计划")).toBeInTheDocument();
    expect(screen.getByText("正在阅读")).toBeInTheDocument();
  });
});
