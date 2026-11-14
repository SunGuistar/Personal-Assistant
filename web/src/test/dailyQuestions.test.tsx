import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DailyQuestionsPanel } from "../components/rail/DailyQuestionsPanel";
import { DailyQuestion, DailyQuestionRound } from "../api/dailyQuestions";

afterEach(() => vi.unstubAllGlobals());
const question = (id: number): DailyQuestion => ({ id, question: `问题${id}`, answer: `答案${id}`, due_at: null, review_count: 0, review_level: 0 });
function setup(total = 2, completed = 0) {
  const items = [question(1), question(2)];
  let state: DailyQuestionRound = { review_date: "2026-11-14", version: 0, total, completed, queue: items.slice(completed, total), has_questions: true };
  let fail = false;
  const requests: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: unknown, init?: RequestInit) => {
    if (String(url).endsWith("/today/review")) {
      const body = JSON.parse(String(init?.body));
      requests.push(body);
      if (fail) return new Response("{}", {status:500});
      state = {...state, version: state.version + 1, completed: state.completed + Number(body.remembered),
        queue: body.remembered ? state.queue.slice(1) : [...state.queue.slice(1), state.queue[0]]};
      return new Response(JSON.stringify(state));
    }
    if (String(url).endsWith("/review")) return new Response(JSON.stringify(items[0]));
    return new Response(JSON.stringify(String(url).endsWith("/today") ? state : items));
  }));
  const client = new QueryClient({defaultOptions:{queries:{retry:false}, mutations:{retry:false}}});
  const show = () => render(<QueryClientProvider client={client}><DailyQuestionsPanel /></QueryClientProvider>);
  return {show, client, requests, setFail: (value: boolean) => {fail = value;}, setDay: () => {state = {...state, review_date:"2026-11-15", completed:0, version:0, queue:items};}};
}
async function answer(id: number, remembered: boolean) {
  fireEvent.click(await screen.findByRole("button", {name:new RegExp(`问题${id}`)}));
  fireEvent.click(screen.getByRole("button", {name: remembered ? "记住了" : "没记住"}));
}
describe("每日一问固定题单", () => {
  it("展示服务端进度，答案折叠，次数仅在全部问答展示", async () => {
    const test = setup(2, 1); test.show();
    await screen.findByText("已完成 1/2");
    expect(screen.queryByText("答案2")).not.toBeInTheDocument();
    expect(screen.queryByText(/记住 \d+ 次/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", {name:"复习知识库"})).toHaveAttribute("href", "/knowledge");
    test.client.clear();
  });
  it("没记住移到队尾不计数，刷新重挂载恢复队列，记住后才完成", async () => {
    const test = setup(); const view = test.show();
    await answer(1, false);
    await screen.findByRole("button", {name:/问题2/});
    expect(screen.getByText("已完成 0/2")).toBeInTheDocument();
    view.unmount(); test.client.clear(); test.show();
    await answer(2, true);
    await screen.findByRole("button", {name:/问题1/});
    expect(screen.getByText("已完成 1/2")).toBeInTheDocument();
    await answer(1, true);
    await screen.findByText("今日题目全部记住了。");
    expect(screen.getByText("已完成 2/2")).toBeInTheDocument();
    expect(test.requests.map(q => q.version)).toEqual([0, 1, 2]);
    test.client.clear();
  });
  it("保存失败保留题目答案与进度", async () => {
    const test = setup(); test.setFail(true); test.show();
    await answer(1, true);
    await screen.findByRole("alert");
    expect(screen.getByText("已完成 0/2")).toBeInTheDocument();
    expect(screen.getByText("答案1")).toBeInTheDocument();
    test.setFail(false);
    fireEvent.click(screen.getByRole("button", {name:"记住了"}));
    await screen.findByText("已完成 1/2");
    test.client.clear();
  });
  it("额外练习不重置今日进度，跨天恢复新题单", async () => {
    const test = setup(2, 2); test.show();
    await screen.findByText("今日题目全部记住了。");
    fireEvent.click(screen.getByRole("button", {name:"再练一轮"}));
    await screen.findByText("额外练习");
    await answer(1, true);
    await screen.findByRole("button", {name:/问题2/});
    expect(screen.getByText("已完成 2/2")).toBeInTheDocument();
    test.setDay();
    await test.client.invalidateQueries({queryKey:["daily_question_round"]});
    await screen.findByText("已完成 0/2");
    expect(screen.queryByText("额外练习")).not.toBeInTheDocument();
    await screen.findByRole("button", {name:/问题1/});
    test.client.clear();
  });
  it("空题单不误报完成", async () => {
    const test = setup(0); test.show();
    await screen.findByText("今日暂无待复习或新题，新题明日纳入。");
    expect(screen.getByText("已完成 0/0")).toBeInTheDocument();
    test.client.clear();
  });
});
