import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { WechatPage } from "../pages/WechatPage";

const CHAT = {
  chat_id: "45843358543@chatroom",
  display_name: "馨馨子钻粉群",
  message_count: 7659,
  min_date: "2026-10-27",
  max_date: "2026-11-03",
};

function sseResponse(events: object[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const event of events) {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
        }
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } }
  );
}

function stubFetch(chatCalls: { message: string }[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/wechat/source/status")) {
        return new Response(JSON.stringify({ running: true, accounts: [] }), { status: 200 });
      }
      if (url.includes("/api/wechat/data-range")) {
        return new Response(JSON.stringify([CHAT]), { status: 200 });
      }
      if (url.includes("/api/wechat/chat") && init?.method === "POST") {
        chatCalls.push(JSON.parse(String(init.body)));
        return sseResponse([
          { type: "token", text: "你好" },
          { type: "token", text: "，世界" },
          { type: "done", session_id: 7 },
        ]);
      }
      return new Response("not found", { status: 404 });
    })
  );
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <WechatPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("微信聊天助手页面", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("渲染数据源状态、数据范围与快捷输入", async () => {
    stubFetch([]);
    renderPage();
    expect(await screen.findByText("WeChatDataAnalysis 运行中")).toBeInTheDocument();
    expect(await screen.findByText(/馨馨子钻粉群：7659 条/)).toBeInTheDocument();
    expect(screen.getByText("总结今天的馨馨子钻粉群的聊天记录")).toBeInTheDocument();
    expect(screen.getByText("列出今天说话最多的十个人")).toBeInTheDocument();
  });

  it("发送消息并流式渲染回复", async () => {
    const calls: { message: string }[] = [];
    stubFetch(calls);
    renderPage();

    const input = screen.getByPlaceholderText("输入你的问题，回车发送…");
    fireEvent.change(input, { target: { value: "这周谁最活跃" } });
    fireEvent.click(screen.getByRole("button", { name: /发送/ }));

    expect(await screen.findByText("这周谁最活跃")).toBeInTheDocument();
    expect(await screen.findByText("你好，世界")).toBeInTheDocument();
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].message).toBe("这周谁最活跃");
  });

  it("点击快捷输入以相同通道发送", async () => {
    const calls: { message: string }[] = [];
    stubFetch(calls);
    renderPage();

    fireEvent.click(await screen.findByText("列出今天说话最多的十个人"));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].message).toBe("列出今天说话最多的十个人");
  });
});
