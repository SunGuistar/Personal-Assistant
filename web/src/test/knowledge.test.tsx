import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { KnowledgePage } from "../pages/KnowledgePage";
import { reviewQueue, DailyQuestion } from "../api/dailyQuestions";
afterEach(() => vi.unstubAllGlobals());
it("先揭晓再反馈，刷新获取刚新增的题，失败可重试", async () => {
  let items = [{id:1, question:"第一题", answer:"答案一", tags:"", review_count:0, review_level:0, due_at:null as string|null}];
  let fail = true;
  vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => {
    if(init?.method === "POST") {
      if(fail) return new Response(JSON.stringify({detail:{message:"失败"}}), {status:500});
      items[0] = {...items[0], review_count:1, due_at:"2099-01-01T00:00:00+08:00"};
      return new Response(JSON.stringify(items[0]));
    }
    return new Response(JSON.stringify(items));
  }));
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><KnowledgePage /></QueryClientProvider>);
  const practice = within(screen.getByRole("region", {name:"记忆练习"}));
  await practice.findByText("第一题");
  expect(practice.queryByText("答案一")).not.toBeInTheDocument();
  fireEvent.click(practice.getByText("查看答案"));
  expect(practice.getByText("答案一")).toBeInTheDocument();
  fireEvent.click(practice.getByText("记住了"));
  await practice.findByRole("alert");
  fail = false;
  fireEvent.click(practice.getByText("记住了"));
  await practice.findByText(/本轮已完成/);
  items.push({id:2, question:"新增题", answer:"答案二", tags:"",review_count:0,review_level:0,due_at:null});
  fireEvent.click(practice.getByText("刷新题库"));
  await practice.findByText("新增题");
  expect(practice.queryByText("答案二")).not.toBeInTheDocument();
});
it("到期优先、新题随后，已刷题不重复，自由练习可选未到期题", () => {
  const q = (id:number,due_at:string|null):DailyQuestion => ({id,question:"问",answer:"答",due_at,review_level:0,review_count:0});
  const items = [q(1,null),q(2,"2000-01-01T00:00:00Z"),q(3,"2099-01-01T00:00:00Z")];
  expect(reviewQueue(items,[]).map(q=>q.id)).toEqual([2,1]);
  expect(reviewQueue(items,[2]).map(q=>q.id)).toEqual([1]);
  expect(reviewQueue(items,[],true)).toHaveLength(3);
});
