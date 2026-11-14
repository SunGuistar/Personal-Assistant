import { afterEach, expect, it, vi } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ModuleGate, StartupProvider } from "../components/ModuleGate";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("未就绪不请求模块数据，就绪后自动显示页面", async () => {
  let state = "loading";
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ home_ready: true, modules: {
    morning: { status: state, error: null }, wechat: { status: "ready" }, reading: { status: "ready" }, github: { status: "ready" },
  } }), { status: 200 })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><StartupProvider>
    <ModuleGate module="morning"><div>晨报内容</div></ModuleGate>
    <div>计划管理可用</div>
  </StartupProvider></QueryClientProvider>);
  expect(screen.getByText("今日晨报加载中…")).toBeInTheDocument();
  expect(screen.queryByText("晨报内容")).not.toBeInTheDocument();
  expect(screen.getByText("计划管理可用")).toBeInTheDocument();
  await waitFor(() => expect(client.getQueryData(["module_startup"])).toBeDefined());
  state = "ready";
  await client.invalidateQueries({ queryKey: ["module_startup"] });
  await waitFor(() => expect(screen.getByText("晨报内容")).toBeInTheDocument());
  client.clear();
});

it("模块失败显示错误并允许重新检查", async () => {
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ home_ready: true, modules: {
    morning: { status: "failed", error: "初始化失败，请重启" },
  } }), { status: 200 }));
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><StartupProvider><ModuleGate module="morning">内容</ModuleGate></StartupProvider></QueryClientProvider>);
  expect(await screen.findByRole("alert")).toHaveTextContent("初始化失败，请重启");
  expect(screen.queryByText("内容")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("重新检查"));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  client.clear();
});
