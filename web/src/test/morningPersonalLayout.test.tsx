import { render, screen } from "@testing-library/react";
import { MorningReportBody } from "../components/MorningReportBody";

it("个人条目标题加粗放大，建议跨说明连续编号，非标题颜色为199灰色", () => {
  const { container } = render(<MorningReportBody text={`**一、开篇速览**
速览
## 二、重要资讯
新闻
## 三、我的昨日
- **已完成**：整理项目方案。补充具体完成情况。
- 跟进待办。尚待确认。
## 四、今日建议
1. **推进方案**
  - 依据：当前待办
  - 下一步：检查方案

2. 1. **确认安排**
  说明安排的依据。
## 五、信息说明
来源`} />);
  expect(screen.getByRole("heading", { name: "已完成：整理项目方案" })).toHaveClass("font-bold", "text-[20px]");
  expect(screen.getByRole("heading", { name: "推进方案" })).toHaveClass("text-[20px]");
  for (const title of ["一、开篇速览", "二、重要资讯", "三、我的昨日", "四、今日建议"]) {
    expect(screen.getByRole("heading", { name: title })).toHaveClass("text-[24px]");
  }
  const lists = container.querySelectorAll("[data-advice-list]");
  expect(lists).toHaveLength(1);
  expect(lists[0].children).toHaveLength(2);
  expect(screen.getByRole("heading", { name: "确认安排" })).toBeInTheDocument();
  expect(screen.getByText("补充具体完成情况。").parentElement).toHaveClass("text-[#c7c7c7]");
  expect(screen.getByText("说明安排的依据。").parentElement).toHaveClass("text-[#c7c7c7]");
});
