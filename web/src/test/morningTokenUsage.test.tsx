import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MorningTokenUsage } from "../components/MorningTokenUsage";

it("按本轮与步骤累计多次调用，切换运行后不会混入上轮用量", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const second = String(input).includes("run_id=2");
    return new Response(JSON.stringify({ items: second ? [{ node: "editor", input_tokens: 7, output_tokens: null }] : [
      { node: "editor", input_tokens: 10, output_tokens: 2, cache_hit_tokens: 8, cache_miss_tokens: 2 },
      { node: "editor", input_tokens: 20, output_tokens: 3, cache_hit_tokens: 0, cache_miss_tokens: 20 },
      { node: "goal_analysis", input_tokens: 100, output_tokens: 5 },
    ] }), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const stages = [{ stage: "editor", title: "主编整合" }, { stage: "goal_analysis", title: "目标分析" },
                  { stage: "collect", title: "资讯采集" }];
  const view = (runId: number) => <QueryClientProvider client={client}>
    <MorningTokenUsage runId={runId} active={false} stages={stages} />
  </QueryClientProvider>;
  const { rerender } = render(view(1));
  const editor = (await screen.findByRole("rowheader", { name: "主编整合" })).closest("tr")!;
  expect(within(editor).getByText("30")).toBeInTheDocument();
  expect(within(editor).getByText("5")).toBeInTheDocument();
  expect(within(editor).getByText("35")).toBeInTheDocument();
  expect(screen.getByText("本轮总 Token").parentElement).toHaveTextContent("140");
  expect(screen.getByText("本轮总 Token").parentElement).toHaveTextContent("缓存命中 8（已记录） · 缓存未命中 22（已记录）");
  expect(screen.getByRole("rowheader", { name: "资讯采集" }).closest("tr")).toHaveTextContent("—");
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("run_id=1"))).toBe(true);
  rerender(view(2));
  await screen.findByText("部分调用用量缺失。", { exact: false });
  expect(screen.getByText("本轮总 Token").parentElement).toHaveTextContent("7（已记录）");
  expect(screen.queryByText("140")).not.toBeInTheDocument();
  expect(screen.getByText("本轮总 Token").parentElement).toHaveTextContent("缓存命中 — · 缓存未命中 —");
  client.clear();
});
