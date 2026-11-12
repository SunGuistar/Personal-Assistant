import { fireEvent, render, screen, within } from "@testing-library/react";
import { MorningReportBody } from "../components/MorningReportBody";

it("新闻直接按结构化字段与ID渲染，不受AI前沿标题、模型引语或链接变化影响", () => {
  const onMark = vi.fn();
  const item = { id: 7, category: "ai", title: "来源标题", url: "https://example.com/original", summary: "来源摘要", section_label: "模型发布/更新" };
  const newsContent = { version: 1, categories: { domestic: [], international: [], ai: [item] },
    overview: [{ ...item, display_type: "AI新闻" }], errors: { domestic: "来源 HTTP 503" } };
  const text = "# 今日晨报\n## 一、开篇速览\n旧速览\n## 二、重要资讯\n### AI 前沿\n模型未经核验的概述\n- [模型改写标题](https://example.com/wrong)\n## 三、我的昨日\n- 完成任务。个人正文保留。\n## 四、今日建议\n1. 继续推进。下一步。\n## 五、信息说明\n信息说明保留";
  render(<MorningReportBody text={text} newsContent={newsContent}
    newsItems={[{ id: 7, title: "当前标题变化", source_url: "https://example.com/changed", category: "ai", content_hash: "h", is_important: false }]}
    onImportanceChange={onMark} />);
  expect(screen.queryByText("模型未经核验的概述")).not.toBeInTheDocument();
  expect(screen.queryByText("模型改写标题")).not.toBeInTheDocument();
  const ai = screen.getByRole("region", { name: "ai资讯" });
  expect(within(ai).getByRole("link", { name: "来源标题" })).toHaveAttribute("href", "https://example.com/original");
  expect(within(ai).getByText("模型发布/更新")).toHaveClass("bg-violet-100");
  const stars = screen.getAllByRole("button", { name: "标记重要新闻：来源标题" });
  expect(stars).toHaveLength(2);
  fireEvent.click(stars[1]);
  expect(onMark).toHaveBeenCalledWith(7, true);
  expect(within(ai).getByText("来源摘要").closest("details")).not.toHaveAttribute("open");
  for (const summary of screen.getAllByText("来源摘要")) {
    expect(summary.closest("details")).not.toBeNull();
    expect(summary.closest("details")).not.toHaveAttribute("open");
  }
  expect(screen.getByText("资讯暂缺：来源 HTTP 503")).toBeInTheDocument();
  expect(screen.getByText("个人正文保留。")).toBeInTheDocument();
  expect(screen.getByText("五、信息说明").closest("details")).not.toHaveAttribute("open");
});

it("没有结构化字段的旧Markdown仍能识别AI前沿并显示类型", () => {
  render(<MorningReportBody text={"### AI 前沿\n- [AI标题](https://example.com/ai)"}
    newsSelection={{ ai: [{ title: "AI标题", url: "https://example.com/ai", section_label: "行业动态" }] }} />);
  expect(screen.getByText("行业动态")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "标记重要新闻：AI标题" })).toBeInTheDocument();
});
