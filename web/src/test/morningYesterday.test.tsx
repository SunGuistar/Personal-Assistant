import { render, screen, fireEvent } from "@testing-library/react";
import { MorningReportBody } from "../components/MorningReportBody";
const rows = (prefix: string, count: number) => Array.from({ length: count }, (_, i) => ({ id: prefix + i, title: prefix + i, summary: "说明" + prefix + i, detail: "说明" + prefix + i, kind: "confirmed" }));
it("我的昨日只展示八条，其余保留在默认折叠区", () => {
  const content = { version: 1, completed: rows("完成", 6), goal_progress: rows("推进", 3), attention: rows("风险", 2), questions: rows("疑问", 1), additional: [], notices: [] };
  const { container } = render(<MorningReportBody text={"## 三、我的昨日\n旧正文\n## 四、今日建议\n1. **行动**"} yesterdayContent={content} />);
  const root = screen.getByTestId("yesterday-summary");
  const headings = Array.from(root.querySelectorAll("h4"));
  expect(headings.filter(node => !node.closest("details"))).toHaveLength(8);
  expect(container.querySelectorAll("details[open]")).toHaveLength(0);
  const overflow = screen.getByText("查看其余 3 条");
  fireEvent.click(overflow);
  expect(overflow.closest("details")).toHaveAttribute("open");
  expect(screen.getByRole("heading", { name: "完成5" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "行动" })).toBeInTheDocument();
});
it("没有风险时省略需要关注分组", () => {
  render(<MorningReportBody text="## 三、我的昨日" yesterdayContent={{ version: 1, completed: rows("完成", 1), goal_progress: [], attention: [], questions: [], additional: [], notices: [] }} />);
  expect(screen.queryByRole("heading", { name: "需要关注" })).not.toBeInTheDocument();
});

it("组标题大于信息标题，疑问和更多分析收进需要关注且默认折叠", () => {
  render(<MorningReportBody text="## 三、我的昨日" yesterdayContent={{ version: 1, completed: rows("完成", 1), goal_progress: rows("推进", 1), attention: [], questions: rows("疑问", 1), additional: rows("补充", 1), notices: [] }} />);
  for (const name of ["昨日完成", "目标推进", "需要关注"]) {
    expect(screen.getByRole("heading", { name })).toHaveClass("text-[22px]");
  }
  expect(screen.getByRole("heading", { name: "完成0" })).toHaveClass("text-[18px]");
  expect(screen.queryByRole("heading", { name: "待确认与信息缺口" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "更多分析" })).not.toBeInTheDocument();
  const section = screen.getByRole("heading", { name: "需要关注" }).closest("section")!;
  expect(section).toHaveTextContent("疑问0");
  expect(section).toHaveTextContent("补充0");
  expect(section.querySelector("details")).not.toHaveAttribute("open");
});
