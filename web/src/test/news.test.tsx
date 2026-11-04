import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { NewsPage } from "../pages/NewsPage";

const ITEMS = [
  {
    id: 1,
    title: "Python 3.14 released",
    url: "https://python.example/3.14",
    source: "Python Insider",
    source_id: 3,
    topic: "python",
    published_at: new Date(Date.now() - 3600_000).toISOString(),
    raw_summary: "What's new",
    norm_heat: 0.5,
    score: 0.42,
    is_favorite: false,
    is_read: false,
    fetched_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 2,
    title: "New agent framework",
    url: "https://acme.dev/agent",
    source: "Hacker News",
    source_id: 1,
    topic: "agent",
    published_at: new Date(Date.now() - 7200_000).toISOString(),
    raw_summary: "",
    norm_heat: 0.75,
    score: 0.6,
    is_favorite: true,
    is_read: true,
    fetched_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
];

const SOURCES = [{ id: 1, name: "Hacker News", kind: "hn", endpoint: "x", enabled: true, weight: 1, created_at: "", updated_at: "" }];

function makeFetchMock(patchSpy: (body: unknown, url: string) => void) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/news/items/") && init?.method === "PATCH") {
      patchSpy(JSON.parse(String(init.body)), url);
      const id = Number(url.split("/").pop());
      const item = ITEMS.find((i) => i.id === id)!;
      return new Response(JSON.stringify({ ...item, ...JSON.parse(String(init.body)) }), { status: 200 });
    }
    if (url.includes("/api/news/items")) {
      return new Response(JSON.stringify({ items: ITEMS, total: 2, page: 1, page_size: 50 }), { status: 200 });
    }
    if (url === "/api/news/sources") {
      return new Response(JSON.stringify(SOURCES), { status: 200 });
    }
    if (url === "/api/news/status") {
      return new Response(
        JSON.stringify({ last_refresh: { refreshed_at: new Date().toISOString(), new_items: 2, sources: 2, failures: [] }, refresh_minutes: 30, stale: false }),
        { status: 200 }
      );
    }
    return new Response("not found", { status: 404 });
  });
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <NewsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("技术资讯页面", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("渲染资讯列表与来源/主题信息", async () => {
    vi.stubGlobal("fetch", makeFetchMock(() => {}));
    renderPage();

    expect(await screen.findByText("Python 3.14 released")).toBeInTheDocument();
    expect(screen.getByText("New agent framework")).toBeInTheDocument();
    expect(screen.getByText("Python Insider")).toBeInTheDocument();
    expect(screen.getByText("综合热度")).toBeInTheDocument();
  });

  it("收藏与已读通过 PATCH 更新", async () => {
    const patches: unknown[] = [];
    vi.stubGlobal("fetch", makeFetchMock((body) => patches.push(body)));
    renderPage();

    const favButtons = await screen.findAllByRole("button", { name: "收藏" });
    fireEvent.click(favButtons[0]);
    await waitFor(() => expect(patches).toContainEqual({ is_favorite: true }));

    const unreadButton = screen.getByRole("button", { name: "标记未读" });
    fireEvent.click(unreadButton);
    await waitFor(() => expect(patches).toContainEqual({ is_read: false }));
  });

  it("主题筛选改变请求参数", async () => {
    const urls: string[] = [];
    const fetchMock = makeFetchMock(() => {});
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      urls.push(String(input));
      return fetchMock(input, init);
    }));
    renderPage();

    await screen.findByText("Python 3.14 released");
    fireEvent.change(screen.getByLabelText("主题筛选"), { target: { value: "python" } });
    await waitFor(() => expect(urls.some((u) => u.includes("topic=python"))).toBe(true));
  });

  it("空数据显示提示与手动刷新按钮", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/news/items")) {
          return new Response(JSON.stringify({ items: [], total: 0, page: 1, page_size: 50 }), { status: 200 });
        }
        if (url === "/api/news/sources") return new Response(JSON.stringify(SOURCES), { status: 200 });
        if (url === "/api/news/status") {
          return new Response(JSON.stringify({ last_refresh: null, refresh_minutes: 30, stale: false }), { status: 200 });
        }
        return new Response("not found", { status: 404 });
      })
    );
    renderPage();
    expect(await screen.findByText(/暂无资讯/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /刷新/ })).toBeInTheDocument();
  });

  it("后端未连接时显示错误提示", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("err", { status: 500 })));
    renderPage();
    expect(await screen.findByText(/后端未连接/)).toBeInTheDocument();
  });
});
