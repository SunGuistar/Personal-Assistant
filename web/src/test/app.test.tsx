import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AppRoutes } from "../App";
import { AppLayout } from "../components/layout/AppLayout";

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
  it("渲染主导航与首页", () => {
    renderApp();
    expect(screen.getByText("Personal Hub")).toBeInTheDocument();
    expect(screen.getByText("首页工作台")).toBeInTheDocument();
    expect(screen.getByText("微信助手")).toBeInTheDocument();
    expect(screen.getByText("技术资讯")).toBeInTheDocument();
    expect(screen.getByText("计划管理")).toBeInTheDocument();
    expect(screen.getByText("阅读管理")).toBeInTheDocument();
    expect(screen.getByText("清理审核")).toBeInTheDocument();
    expect(screen.getByText("设置")).toBeInTheDocument();
  });

  it("前端路由切换到占位页", () => {
    renderApp("/news");
    expect(screen.getByText(/资讯列表、筛选排序、收藏与已读/)).toBeInTheDocument();
  });
});
