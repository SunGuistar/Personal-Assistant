import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { KnowledgePage } from "../pages/KnowledgePage";
import { reviewQueue, DailyQuestion } from "../api/dailyQuestions";
afterEach(() => vi.unstubAllGlobals());

it("全部问答经审核勾选后删除，取消不发送请求，成功刷新题库和今日题单", async () => {
  let items = [{ id: 1, question: "待删除题", answer: "待删除答案", review_count: 0, review_level: 0, due_at: null }];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "DELETE") {
      expect(String(input)).toBe("/api/daily_questions/1");
      expect(JSON.parse(String(init.body))).toEqual({ confirmed: true });
      items = [];
      return new Response(null, { status: 204 });
    }
    return new Response(JSON.stringify(String(input).endsWith("/today")
      ? { review_date: "2026-11-17", version: 0, total: items.length, completed: 0, queue: items, has_questions: items.length > 0 }
      : items));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<QueryClientProvider client={client}><KnowledgePage /></QueryClientProvider>);
  await screen.findByText(/总计 1/);
  fireEvent.click(screen.getByRole("button", { name: "全部问答" }));
  fireEvent.click(screen.getByRole("button", { name: "删除" }));
  let dialog = within(screen.getByRole("dialog", { name: "删除问答" }));
  expect(dialog.getByText("待删除题")).toBeInTheDocument();
  expect(dialog.getByRole("button", { name: "确认删除" })).toBeDisabled();
  fireEvent.click(dialog.getByRole("button", { name: "取消" }));
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
  expect(screen.getByText("待删除题")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "删除" }));
  dialog = within(screen.getByRole("dialog", { name: "删除问答" }));
  fireEvent.click(dialog.getByRole("checkbox"));
  fireEvent.click(dialog.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  await screen.findByText(/总计 0/);
  expect(screen.queryByText("待删除题")).not.toBeInTheDocument();
  expect(client.getQueryState(["daily_question_round"])?.isInvalidated).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "今日复习" }));
  await screen.findByText("还没有问答，前往问答复习记录问答。");
  client.clear();
});

it("问答删除失败保留题目和审核弹窗，可重试", async () => {
  const item = { id: 1, question: "保留题", answer: "保留答案", review_count: 0, review_level: 0, due_at: null };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => init?.method === "DELETE"
    ? new Response(JSON.stringify({ detail: { message: "失败" } }), { status: 500 })
    : new Response(JSON.stringify(String(input).endsWith("/today")
      ? { review_date: "2026-11-17", version: 0, total: 1, completed: 0, queue: [item], has_questions: true }
      : [item]))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><KnowledgePage /></QueryClientProvider>);
  await screen.findByText(/总计 1/);
  fireEvent.click(screen.getByRole("button", { name: "全部问答" }));
  fireEvent.click(screen.getByRole("button", { name: "删除" }));
  const dialog = within(screen.getByRole("dialog", { name: "删除问答" }));
  fireEvent.click(dialog.getByRole("checkbox"));
  fireEvent.click(dialog.getByRole("button", { name: "确认删除" }));
  await dialog.findByRole("alert");
  expect(dialog.getByRole("button", { name: "确认删除" })).toBeEnabled();
  expect(screen.getAllByText("保留题")).toHaveLength(2);
  client.clear();
});
it("先揭晓再反馈，失败可重试，刷新保持固定今日题单", async () => {
  let items = [{id:1, question:"第一题", answer:"答案一", tags:"", review_count:0, review_level:0, due_at:null as string|null}];
  let fail = true;
  let completed = 0;
  const today = () => ({review_date:"2026-11-14", version:completed, total:1, completed, queue:completed ? [] : [items[0]], has_questions:true});
  vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => {
    if(init?.method === "POST") {
      if(fail) return new Response(JSON.stringify({detail:{message:"失败"}}), {status:500});
      items[0] = {...items[0], review_count:1, due_at:"2099-01-01T00:00:00+08:00"};
      completed = 1;
      return new Response(JSON.stringify(today()));
    }
    return new Response(JSON.stringify(String(_url).endsWith("/today") ? today() : items));
  }));
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><KnowledgePage /></QueryClientProvider>);
  const practice = within(screen.getByRole("region", {name:"记忆练习"}));
  await practice.findByText("第一题");
  expect(practice.queryByText("答案一")).not.toBeInTheDocument();
  fireEvent.click(practice.getByRole("button", {name:/第一题/}));
  expect(practice.getByText("答案一")).toBeInTheDocument();
  fireEvent.click(practice.getByText("记住了"));
  await practice.findByRole("alert");
  fail = false;
  fireEvent.click(practice.getByText("记住了"));
  await practice.findByText("今日题目全部记住了。");
  expect(practice.getByText("已完成 1/1")).toBeInTheDocument();
  items.push({id:2, question:"新增题", answer:"答案二", tags:"",review_count:0,review_level:0,due_at:null});
  fireEvent.click(practice.getByText("刷新题库"));
  await screen.findByText(/总计 2/);
  expect(practice.queryByText("新增题")).not.toBeInTheDocument();
  expect(practice.getByText("已完成 1/1")).toBeInTheDocument();
  expect(practice.queryByText("答案二")).not.toBeInTheDocument();
});
it("到期优先、新题随后，已刷题不重复，自由练习可选未到期题", () => {
  const q = (id:number,due_at:string|null):DailyQuestion => ({id,question:"问",answer:"答",due_at,review_level:0,review_count:0});
  const items = [q(1,null),q(2,"2000-01-01T00:00:00Z"),q(3,"2099-01-01T00:00:00Z")];
  expect(reviewQueue(items,[]).map(q=>q.id)).toEqual([2,1]);
  expect(reviewQueue(items,[2]).map(q=>q.id)).toEqual([1]);
  expect(reviewQueue(items,[],true)).toHaveLength(3);
});
