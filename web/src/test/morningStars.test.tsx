import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StarredMorningReport } from "../components/StarredMorningReport";
import { Report } from "../api/morning";

it("星标保存失败可重试，成功后速览和正文同步，重新加载仍保留", async () => {
  let important = false;
  let fail = true;
  const item = () => ({ id: 1, title: "新闻", source_url: "https://example.com/news", category: "ai", content_hash: "h", is_important: important });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith("/importance")) {
      if (fail) return new Response(JSON.stringify({ detail: { code: "failed", message: "test failure" } }), { status: 500 });
      important = JSON.parse(String(init?.body)).is_important;
      return new Response(JSON.stringify(item()), { status: 200 });
    }
    return new Response(JSON.stringify({ items: [item()] }), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const report = { id: 1, sections: {}, content_md: "## 一、开篇速览\n- [新闻](https://example.com/news)【AI新闻】\n  摘要\n## 二、重要资讯\n### AI\n- [新闻](https://example.com/news)" } as Report;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = () => <QueryClientProvider client={client}><StarredMorningReport report={report} /></QueryClientProvider>;
  const rendered = render(view());
  await waitFor(() => expect(screen.getAllByRole("button", { name: "标记重要新闻：新闻" })[0]).toBeEnabled());
  fireEvent.click(screen.getAllByRole("button", { name: "标记重要新闻：新闻" })[0]);
  expect(await screen.findByRole("alert")).toHaveTextContent("星标保存失败");
  expect(important).toBe(false);
  fail = false;
  fireEvent.click(screen.getAllByRole("button", { name: "标记重要新闻：新闻" })[1]);
  await waitFor(() => expect(screen.getAllByRole("button", { name: "取消重要新闻：新闻" })).toHaveLength(2));
  expect(important).toBe(true);
  rendered.unmount();
  client.clear();
  render(view());
  await waitFor(() => expect(screen.getAllByRole("button", { name: "取消重要新闻：新闻" })).toHaveLength(2));
  fireEvent.click(screen.getAllByRole("button", { name: "取消重要新闻：新闻" })[0]);
  await waitFor(() => expect(screen.getAllByRole("button", { name: "标记重要新闻：新闻" })).toHaveLength(2));
  expect(important).toBe(false);
  client.clear();
});
