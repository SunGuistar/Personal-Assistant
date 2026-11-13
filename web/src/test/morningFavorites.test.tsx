import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FavoriteMorningNews } from "../components/FavoriteMorningNews";

it("收藏列表编辑笔记，重点星标独立置顶，取消重点仍保留收藏", async () => {
  const items = [1, 2].map(id => ({ id, title: `新闻${id}`, summary: id === 2 ? "新闻摘要内容" : null, category: "ai", content_hash: `h${id}`, is_important: true, note: "", is_highlighted: false }));
  let fail = false;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "PATCH") {
      if (fail) return new Response("{}", { status: 500 });
      const item = items.find(row => String(input).endsWith(`/${row.id}`))!;
      Object.assign(item, JSON.parse(String(init.body)));
      return new Response(JSON.stringify(item));
    }
    return new Response(JSON.stringify({ items: [...items].sort((a, b) => Number(b.is_highlighted) - Number(a.is_highlighted)) }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><FavoriteMorningNews /></QueryClientProvider>);
  await screen.findByText("新闻2");
  const row = () => screen.getByText("新闻2").closest("li")!;
  expect(screen.queryByText("暂无笔记")).not.toBeInTheDocument();
  const details = within(row()).getByText("摘要").closest("details")!;
  expect(details).not.toHaveAttribute("open");
  expect(within(details).getByText("新闻摘要内容")).toBeInTheDocument();
  fireEvent.click(within(details).getByText("摘要"));
  expect(details).toHaveAttribute("open");
  expect(within(screen.getByText("新闻1").closest("li")!).queryByText("摘要")).not.toBeInTheDocument();
  expect(within(row()).getByText("AI 新闻")).toBeInTheDocument();
  fireEvent.click(within(row()).getByRole("button", { name: "编辑笔记" }));
  fireEvent.change(screen.getByLabelText("笔记：新闻2"), { target: { value: "我的笔记" } });
  fail = true;
  fireEvent.click(screen.getByRole("button", { name: "保存笔记" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("笔记：新闻2")).toHaveValue("我的笔记");
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: "保存笔记" }));
  await within(row()).findByText("笔记：我的笔记");
  fireEvent.click(within(row()).getByRole("button", { name: "标记重要" }));
  await waitFor(() => expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("新闻2"));
  fireEvent.click(within(row()).getByRole("button", { name: "取消重要" }));
  await within(row()).findByRole("button", { name: "标记重要" });
  expect(items[1].is_important).toBe(true);
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
  client.clear();
});
