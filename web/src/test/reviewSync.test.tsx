import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { KnowledgePage } from "../pages/KnowledgePage";
import { DailyQuestionsPanel } from "../components/rail/DailyQuestionsPanel";
import type { DailyQuestionRound } from "../api/dailyQuestions";
afterEach(() => vi.unstubAllGlobals());
it("两个入口共享今日队列和进度，没记住排队尾", async () => {
 const items=[1,2].map(id=>({id,question:`同步问题${id}`,answer:`同步答案${id}`,due_at:null,review_count:0,review_level:0}));
 let state:DailyQuestionRound={review_date:"2026-11-14",version:0,total:2,completed:0,queue:items,has_questions:true};
 vi.stubGlobal("fetch",vi.fn(async(url:unknown,init?:RequestInit)=>{
  if(String(url).endsWith("/today/review")){
   const b=JSON.parse(String(init?.body));expect(b.question_id).toBe(state.queue[0].id);
   state={...state,version:state.version+1,completed:state.completed+Number(b.remembered),queue:b.remembered?state.queue.slice(1):[...state.queue.slice(1),state.queue[0]]};
   return new Response(JSON.stringify(state));
  }
  return new Response(JSON.stringify(String(url).endsWith("/today")?state:items));
 }));
 const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});
 const view=render(<QueryClientProvider client={client}><KnowledgePage/><DailyQuestionsPanel/></QueryClientProvider>);
 const page=within(screen.getByRole("region",{name:"记忆练习"}));const panel=within(screen.getByRole("region",{name:"每日一问"}));
 await page.findByText("已完成 0/2");
 fireEvent.click(await page.findByRole("button",{name:/同步问题1/}));fireEvent.click(page.getByRole("button",{name:"没记住"}));
 await panel.findByRole("button",{name:/同步问题2/});expect(page.getByText("已完成 0/2")).toBeInTheDocument();
 fireEvent.click(panel.getByRole("button",{name:/同步问题2/}));fireEvent.click(panel.getByRole("button",{name:"记住了"}));
 await page.findByText("已完成 1/2");expect(page.getByRole("button",{name:/同步问题1/})).toHaveAttribute("aria-expanded","false");
 view.unmount();client.clear();
});
