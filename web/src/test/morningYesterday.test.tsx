import { render, screen, within } from "@testing-library/react";
import { MorningReportBody } from "../components/MorningReportBody";
const rows = (prefix: string, count: number, kind = "confirmed") => Array.from({ length: count }, (_, i) => ({ id: prefix + i, title: prefix + i, summary: "说明" + prefix + i, detail: "说明" + prefix + i, kind }));

it("昨日条目全部平铺展示，不分组、不折叠其余内容", () => {
  const content = { version: 1, completed: rows("完成", 6), goal_progress: rows("推进", 3), attention: rows("风险", 2), questions: rows("疑问", 1, "unknown"), additional: rows("补充", 1), notices: [] };
  render(<MorningReportBody text={"## 三、我的昨日\n旧正文\n## 四、今日建议\n1. **行动**"} yesterdayContent={content} />);
  const root = screen.getByTestId("yesterday-summary");
  expect(root.querySelectorAll("h4")).toHaveLength(13);
  expect(root.querySelector("details")).toBeNull();
  for (const name of ["昨日完成", "目标推进", "需要关注"]) expect(screen.queryByRole("heading", { name })).not.toBeInTheDocument();
  expect(screen.queryByText(/查看其余/)).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "行动" })).toBeInTheDocument();
});

it("标题和灰色注解同行，完成事实与AI分析使用两种类型", () => {
  render(<MorningReportBody text="## 三、我的昨日" yesterdayContent={{ version: 1, completed: rows("完成", 1), goal_progress: rows("推进", 1), attention: [], questions: rows("待确认", 1, "unknown"), additional: [], notices: [] }} />);
  const heading = screen.getByRole("heading", { name: "完成0" });
  expect(heading).toHaveClass("inline");
  expect(within(heading.parentElement!).getByText("说明完成0").tagName).toBe("SPAN");
  expect(within(heading.parentElement!).getByText("事实完成")).toBeInTheDocument();
  expect(screen.getAllByText("AI分析")).toHaveLength(2);
  expect(screen.queryByText("待确认", { exact: true })).not.toBeInTheDocument();
  expect(screen.getByText("说明待确认0")).toBeInTheDocument();
});
