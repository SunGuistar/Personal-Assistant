import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AppRoutes } from "../App";
import { AppLayout } from "../components/layout/AppLayout";
import { todayStr } from "../lib/api";

function stubGlobalFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/tasks/daily")) return new Response(JSON.stringify([]), { status: 200 });
      if (url === "/api/plans") return new Response(JSON.stringify([]), { status: 200 });
      if (url === "/api/infos") return new Response(JSON.stringify([]), { status: 200 });
      if (url === "/api/memos") return new Response(JSON.stringify([]), { status: 200 });
      if (url.includes("/api/cleanup/status")) {
        return new Response(JSON.stringify({ banner: null, reviews: [] }), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    })
  );
}

function renderApp(initialPath = "/") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <AppLayout>
          <AppRoutes />
        </AppLayout>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("App 骨架", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("渲染主导航（无首页入口），计划管理为默认入口", async () => {
    stubGlobalFetch();
    renderApp();
    expect(screen.getByText("个人助手")).toBeInTheDocument();
    // 无「首页」导航项
    expect(screen.queryByText("首页")).not.toBeInTheDocument();
    expect(screen.getByText("微信助手")).toBeInTheDocument();
    expect(screen.getByText("GitHub")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "今日晨报" })).toHaveAttribute("href", "/morning");
    expect(screen.queryByRole("link", { name: "技术资讯" })).not.toBeInTheDocument();
    expect(screen.getByText("阅读管理")).toBeInTheDocument();
    expect(screen.getByText("清理审核")).toBeInTheDocument();
    expect(screen.getByText("设置")).toBeInTheDocument();
    // 默认路由 = 计划管理（页面标题 + 每日任务面板）
    expect(await screen.findByRole("heading", { name: "计划管理" })).toBeInTheDocument();
    expect(screen.getByText(`每日计划 · ${todayStr()}`)).toBeInTheDocument();
  });

  it("重要信息与随手备忘整合进计划管理页（默认入口页可见）", async () => {
    stubGlobalFetch();
    renderApp();
    expect(await screen.findByText("重要信息")).toBeInTheDocument();
    expect(screen.getByText("随手备忘")).toBeInTheDocument();
  });

  it("晨报路由可访问且不恢复旧全局右栏", async () => {
    stubGlobalFetch();
    renderApp("/morning");
    expect(await screen.findByRole("heading", { name: "今日晨报" })).toBeInTheDocument();
    expect(screen.getByText("生成进度")).toBeInTheDocument();
    expect(screen.queryByText("重要信息")).not.toBeInTheDocument();
    expect(screen.queryByText("随手备忘")).not.toBeInTheDocument();
  });

  it("其他页面不展示重要信息与随手备忘", async () => {
    stubGlobalFetch();
    renderApp("/settings");
    expect(await screen.findByRole("heading", { name: "基础设置" })).toBeInTheDocument();
    expect(screen.queryByText("重要信息")).not.toBeInTheDocument();
    expect(screen.queryByText("随手备忘")).not.toBeInTheDocument();
  });
});
