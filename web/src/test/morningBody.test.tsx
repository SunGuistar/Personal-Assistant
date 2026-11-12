import { fireEvent, render, screen } from "@testing-library/react";
import { MorningReportBody } from "../components/MorningReportBody";

it("三类新闻摘要可展开，标题跳转与信息说明折叠保持有效", () => {
  render(<MorningReportBody text={`## 二、重要资讯
### 国内
- **[国内标题](https://example.com/china)**
  国内摘要不显示
  发布时间：2026-11-09 · 来源：中国新闻网
### 国际
- [国际标题](https://example.com/world)
  国际摘要不显示
### AI
- [AI标题](https://example.com/ai)
AI 内容保留
## 五、信息说明
来源与覆盖说明
## 其他内容
后续内容保留`} />);
  for (const [title, url] of [["国内标题", "https://example.com/china"], ["国际标题", "https://example.com/world"]]) {
    const link = screen.getByRole("link", { name: title });
    expect(link).toHaveAttribute("href", url);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  }
  for (const text of ["国内摘要不显示", "国际摘要不显示", "AI 内容保留"]) {
    const detail = screen.getByText(text, { exact: false }).closest("details");
    expect(detail).not.toBeNull();
    expect(detail).not.toHaveAttribute("open");
    fireEvent.click(detail!.querySelector("summary")!);
    expect(detail).toHaveAttribute("open");
  }
  expect(screen.getByText("后续内容保留")).toBeInTheDocument();
  const summary = screen.getByText("五、信息说明");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  fireEvent.click(summary);
  expect(summary.closest("details")).toHaveAttribute("open");
});

it("AI 标题列表从已保存的结构化新闻数据读取摘要", () => {
  render(<MorningReportBody text={"### AI\n- [模型发布](https://example.com/model)"}
    newsSelection={{ ai: [{ title: "模型发布", url: "https://example.com/model", summary: "原始新闻摘要" }] }} />);
  const detail = screen.getByText("原始新闻摘要").closest("details");
  expect(detail).not.toHaveAttribute("open");
  fireEvent.click(detail!.querySelector("summary")!);
  expect(detail).toHaveAttribute("open");
});

it("AI 标题后显示不同颜色的主题标签，无分类的旧条目不加标签", () => {
  render(<MorningReportBody text={"### AI\n- [模型](https://example.com/model)\n- [行业](https://example.com/industry)\n- [旧条目](https://example.com/old)"}
    newsSelection={{ ai: [
      { title: "模型", url: "https://example.com/model", section_label: "模型发布/更新" },
      { title: "行业", url: "https://example.com/industry", section_label: "行业动态" },
    ] }} />);
  const model = screen.getByText("模型发布/更新");
  const industry = screen.getByText("行业动态");
  expect(model).toHaveClass("bg-violet-100");
  expect(industry).toHaveClass("bg-amber-100");
  expect(model.parentElement).toContainElement(screen.getByRole("link", { name: "模型" }));
  expect(industry.parentElement).toContainElement(screen.getByRole("link", { name: "行业" }));
  expect(screen.queryByText("未分类")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "旧条目" })).toHaveAttribute("href", "https://example.com/old");
});

it("开篇速览直接展示摘要和四类标签，正文摘要仍默认折叠", () => {
  render(<MorningReportBody text={"## 一、开篇速览\n- [国内首条](https://example.com/d)【国内新闻】\n  速览国内摘要\n- [观点](https://example.com/v)【技巧与观点】\n  速览观点摘要\n## 二、重要资讯\n### 国内\n- [国内首条](https://example.com/d)\n  正文国内摘要"} />);
  expect(screen.getByText("国内新闻")).toBeInTheDocument();
  expect(screen.getByText("技巧与观点")).toBeInTheDocument();
  expect(screen.getByText("速览国内摘要").closest("details")).toBeNull();
  expect(screen.getByText("速览观点摘要").closest("details")).toBeNull();
  expect(screen.getByText("正文国内摘要").closest("details")).not.toHaveAttribute("open");
});

it("速览与正文共享星标，点击可标记、取消并保留标题链接", () => {
  const onChange = vi.fn();
  const text = "## 一、开篇速览\n- [同一新闻](https://example.com/news)【AI新闻】\n  摘要\n## 二、重要资讯\n### AI\n- [同一新闻](https://example.com/news)";
  const item = { id: 7, title: "同一新闻", source_url: "https://example.com/news", category: "ai", content_hash: "hash", is_important: false };
  const { rerender } = render(<MorningReportBody text={text} newsItems={[item]} onImportanceChange={onChange} />);
  const stars = screen.getAllByRole("button", { name: "标记重要新闻：同一新闻" });
  expect(stars).toHaveLength(2);
  fireEvent.click(stars[0]);
  expect(onChange).toHaveBeenLastCalledWith(7, true);
  rerender(<MorningReportBody text={text} newsItems={[{ ...item, is_important: true }]} onImportanceChange={onChange} />);
  const marked = screen.getAllByRole("button", { name: "取消重要新闻：同一新闻" });
  expect(marked.every((button) => button.getAttribute("aria-pressed") === "true")).toBe(true);
  fireEvent.click(marked[1]);
  expect(onChange).toHaveBeenLastCalledWith(7, false);
  expect(screen.getAllByRole("link", { name: "同一新闻" })[0]).toHaveAttribute("href", "https://example.com/news");
});
