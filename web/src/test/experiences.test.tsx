import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ExperiencesPage } from "../pages/ExperiencesPage";

const records = [{ id: 1, title: "数据库连接超时", problem: "使用 localhost 等待很久", solution: "使用 127.0.0.1", tags: "数据库，Windows", created_at: "2026-11-15T10:00:00+08:00", updated_at: "2026-11-15T10:00:00+08:00" },
  { id: 2, title: "构建失败", problem: "类型不匹配", solution: "修正类型声明", tags: "前端", created_at: "2026-11-15T09:00:00+08:00", updated_at: "2026-11-15T09:00:00+08:00" }];
function mount() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ExperiencesPage /></QueryClientProvider>);
}
describe("经验库", () => {
  beforeEach(() => vi.unstubAllGlobals());
  it("缺表时提示迁移，区别于没有记录的正常空状态", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: { code: "experiences_schema_missing", message: "经验库数据库尚未迁移，请先完成数据库迁移后重试。" } }), { status: 503 })));
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("数据库尚未迁移");
    expect(screen.queryByText(/还没有经验记录/)).not.toBeInTheDocument();
  });
  it("浏览详情，搜索解决方法，按完整标签筛选", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(records))));
    mount();
    expect(await screen.findByRole("heading", { name: "数据库连接超时" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("搜索经验"), { target: { value: "类型声明" } });
    expect(screen.getByRole("heading", { name: "构建失败" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("搜索经验"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("筛选经验标签"), { target: { value: "Windows" } });
    expect(screen.queryByRole("button", { name: /构建失败/ })).not.toBeInTheDocument();
  });
  it("保存失败保留输入，重试成功后展示新增记录", async () => {
    let fail = true;
    let saved: typeof records[number] | undefined;
    vi.stubGlobal("fetch", vi.fn(async (_url: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        if (fail) return new Response(JSON.stringify({detail:{code:"error",message:"失败"}}), { status: 500 });
        saved = { ...records[0], ...JSON.parse(options.body as string), id: 3 };
        return new Response(JSON.stringify(saved), { status: 201 });
      }
      return new Response(JSON.stringify(saved ? [saved] : []));
    }));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "记录经验" }));
    fireEvent.change(screen.getByLabelText("标题"), { target: { value: "新的问题" } });
    fireEvent.change(screen.getByLabelText("遇到的问题"), { target: { value: "新的现象" } });
    fireEvent.change(screen.getByLabelText("解决方法"), { target: { value: "处理步骤" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("内容已保留");
    expect(screen.getByLabelText("标题")).toHaveValue("新的问题");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "新的问题" })).toBeInTheDocument();
  });
});
