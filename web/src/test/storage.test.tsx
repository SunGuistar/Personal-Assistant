import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StoragePage } from "../pages/StoragePage";

const result = { checked_at: "2026-11-15T13:00:00+08:00", total_bytes: 3072, items: [
  { id: "hub", name: "主业务库", storage_type: "sql", engine: "SQLite", path: "X:/isolated/hub.db", retention: "长期保留", description: "由用户管理", size_basis: "包含 WAL", size_bytes: 2048, file_count: 2, note: "" },
  { id: "files", name: "阅读附件", storage_type: "file", engine: "文件", path: "X:/isolated/notes", retention: "随笔记保留", description: "无自动清理", size_basis: "文件大小", size_bytes: 1024, file_count: 1, note: "" },
  { id: "vector", name: "晨报向量库", storage_type: "vector", engine: "Qdrant", path: "http://127.0.0.1:6333", retention: "未定义", description: "历史保留", size_basis: "服务端", size_bytes: null, file_count: null, note: "大小未知" },
] };
beforeEach(() => vi.unstubAllGlobals());
function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><StoragePage /></QueryClientProvider>);
}
it("展示占比和排行，筛选明细并打开只读详情", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(result))));
  mount();
  expect(await screen.findByRole("img")).toHaveAccessibleName("类型占比，已知总占用 3.0 KiB");
  expect(screen.getByText("66.7%", { exact: false })).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "存储概览" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "存储明细" }));
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.getByText("未知", { exact: true })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("筛选存储类型"), { target: { value: "file" } });
  const table = screen.getByRole("table");
  expect(within(table).queryByText("主业务库")).not.toBeInTheDocument();
  expect(within(table).getByText("阅读附件")).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("查看阅读附件详情"));
  expect(within(screen.getByRole("dialog")).getByText("X:/isolated/notes")).toBeInTheDocument();
  expect(within(screen.getByRole("dialog")).queryByRole("button", { name: "删除" })).not.toBeInTheDocument();
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "关闭" }));
  fireEvent.click(screen.getByRole("button", { name: "存储概览" }));
  expect(screen.getByRole("img")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
it("刷新重新读取，失败时保留上次结果", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(result)))
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: "error", message: "读取失败" } }), { status: 500 }));
  vi.stubGlobal("fetch", fetcher);
  mount();
  await screen.findByRole("img");
  fireEvent.click(screen.getByRole("button", { name: "刷新" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("下方保留上次结果"));
  expect(screen.getByRole("img")).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(2);
});
it("全零数据不产生无效图表", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...result, total_bytes: 0, items: [] }))));
  mount();
  expect(await screen.findByText("暂无可展示的占用数据")).toBeInTheDocument();
  expect(screen.getByRole("img")).toHaveAccessibleName("类型占比，已知总占用 0 B");
});
