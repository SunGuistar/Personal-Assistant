import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DailyQuestionsPanel } from "../components/rail/DailyQuestionsPanel";

afterEach(() => vi.unstubAllGlobals());
describe("每日一问", () => {
  it("默认隐藏答案，点击展开和收起，并可修改问答", async () => {
    let item = { id: 1, question: "测试问题", answer: "隐藏答案" };
    const fetchMock = vi.fn(async (_url: unknown, init?: RequestInit) => {
      if (init?.method === "PUT") {
        item = { ...item, ...JSON.parse(String(init.body)) };
        return new Response(JSON.stringify(item));
      }
      return new Response(JSON.stringify([item]));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><DailyQuestionsPanel /></QueryClientProvider>);
    const question = await screen.findByRole("button", { name: "测试问题" });
    expect(screen.queryByText("隐藏答案")).not.toBeInTheDocument();
    fireEvent.click(question);
    expect(screen.getByText("隐藏答案")).toBeInTheDocument();
    fireEvent.click(question);
    expect(screen.queryByText("隐藏答案")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("编辑问题：测试问题"));
    expect(screen.getByLabelText("答案")).toHaveValue("隐藏答案");
    fireEvent.change(screen.getByLabelText("问题"), { target: { value: "新问题" } });
    fireEvent.change(screen.getByLabelText("答案"), { target: { value: "新答案" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(item).toEqual({ id: 1, question: "新问题", answer: "新答案" }));
    expect(await screen.findByRole("button", { name: "新问题" })).toBeInTheDocument();
    expect(screen.queryByText("新答案")).not.toBeInTheDocument();
  });
});
