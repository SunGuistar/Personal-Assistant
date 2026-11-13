import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DailyQuestionsPanel } from "../components/rail/DailyQuestionsPanel";
import { DailyQuestion } from "../api/dailyQuestions";

afterEach(() => vi.unstubAllGlobals());
const question = (id: number, due_at: string | null): DailyQuestion => ({ id, question: `问题${id}`, answer: `答案${id}`, due_at, review_count: 0, review_level: 0 });
function show(items: DailyQuestion[]) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(items))));
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><DailyQuestionsPanel /></QueryClientProvider>);
}
describe("每日一问", () => {
  it("仅展示今日复习首题，到期优先且答案默认折叠", async () => {
    show([question(1, null), question(2, "2000-01-01T00:00:00Z"), question(3, "2099-01-01T00:00:00Z")]);
    const button = await screen.findByRole("button", { name: /问题2/ });
    expect(screen.queryByText("问题1")).not.toBeInTheDocument();
    expect(screen.queryByText("问题3")).not.toBeInTheDocument();
    expect(screen.queryByText("答案2")).not.toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    expect(screen.getByText("答案2")).toBeInTheDocument();
    fireEvent.click(button);
    expect(screen.queryByText("答案2")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /新增|编辑/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "复习知识库" })).toHaveAttribute("href", "/knowledge");
  });
  it("没有到期题时展示新题，已安排未来复习的题不出现", async () => {
    show([question(2, "2099-01-01T00:00:00Z"), question(1, null)]);
    await screen.findByText("问题1");
    expect(screen.queryByText("问题2")).not.toBeInTheDocument();
  });
  it("没有待复习或新题时显示完成提示", async () => {
    show([question(2, "2099-01-01T00:00:00Z")]);
    await screen.findByText(/本轮已完成/);
    expect(screen.queryByText("问题2")).not.toBeInTheDocument();
  });
  it("反馈失败保留题目可重试，成功后换题且答案重新折叠，本轮不重复", async () => {
    const items = [question(1, null), question(2, null)];
    let fail = true;
    const requests: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => {
      if (init?.method === "POST") {
        requests.push(JSON.parse(String(init.body)));
        return new Response(JSON.stringify(fail ? {} : items[0]), { status: fail ? 500 : 200 });
      }
      return new Response(JSON.stringify(items));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><DailyQuestionsPanel /></QueryClientProvider>);
    fireEvent.click(await screen.findByRole("button", { name: /问题1/ }));
    fireEvent.click(screen.getByRole("button", { name: "记住了" }));
    await screen.findByRole("alert");
    expect(screen.getByText("答案1")).toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "记住了" }));
    const next = await screen.findByRole("button", { name: /问题2/ });
    expect(screen.queryByText("答案2")).not.toBeInTheDocument();
    fireEvent.click(next);
    fireEvent.click(screen.getByRole("button", { name: "没记住" }));
    await screen.findByText(/本轮已完成/);
    expect(requests).toEqual([{ remembered: true }, { remembered: true }, { remembered: false }]);
    fireEvent.click(screen.getByRole("button", { name: "再练一轮" }));
    await screen.findByRole("button", { name: /问题1/ });
    expect(screen.queryByText("答案1")).not.toBeInTheDocument();
    client.clear();
  });
});
