import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ReadingPage } from "../pages/ReadingPage";

const BOOK_WITH_NOTES = {
  id: 1,
  title: "三体",
  title_cn: "",
  book_type: "book",
  author: "刘慈欣",
  note: "",
  status: "reading",
  is_important: false,
  note_count: 2,
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ReadingPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function stubBooksFetch(deleteSpy?: () => void) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/books")) {
        if (init?.method === "DELETE") {
          deleteSpy?.();
          return new Response(
            JSON.stringify({ detail: { code: "book_has_notes", message: "该书籍存在关联笔记，请先删除全部笔记后再删除书籍。" } }),
            { status: 409 }
          );
        }
        return new Response(JSON.stringify([BOOK_WITH_NOTES]), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    })
  );
}

describe("阅读管理页面", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("默认列表展示：渲染书籍行、类型/状态徽标与状态筛选", async () => {
    stubBooksFetch();
    renderPage();
    expect(await screen.findByText("三体")).toBeInTheDocument();
    expect(screen.getAllByText("正在读").length).toBeGreaterThan(0);
    expect(screen.getByText("未读")).toBeInTheDocument();
    expect(screen.getAllByText("书籍").length).toBeGreaterThan(0); // 类型徽标 + 类型筛选
    // 默认列表模式（行容器存在，卡片网格不存在）
    expect(document.querySelector("ul")?.textContent).toContain("三体");
  });

  it("类型筛选：点击类型按钮带 book_type 参数请求", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        urls.push(url);
        if (url.startsWith("/api/books")) {
          return new Response(JSON.stringify([BOOK_WITH_NOTES]), { status: 200 });
        }
        return new Response("not found", { status: 404 });
      })
    );
    renderPage();
    await screen.findByText("三体");
    fireEvent.click(screen.getByRole("button", { name: "文章" }));
    await waitFor(() => expect(urls.some((u) => u.includes("book_type=article"))).toBe(true));
    expect(urls.some((u) => u.includes("/api/books?"))).toBe(true);
  });

  it("列表/卡片切换：默认列表，切换持久化且不影响数据", async () => {
    stubBooksFetch();
    renderPage();
    expect(await screen.findByText("三体")).toBeInTheDocument();
    expect(localStorage.getItem("hub.reading.view")).not.toBe("card");

    fireEvent.click(screen.getByRole("button", { name: "卡片展示" }));
    await screen.findByText("笔记 2 份"); // 卡片视图渲染
    expect(localStorage.getItem("hub.reading.view")).toBe("card");

    fireEvent.click(screen.getByRole("button", { name: "列表展示" }));
    expect(localStorage.getItem("hub.reading.view")).toBe("list");
  });

  it("标题翻译单独展示；未填作者不显示作者占位", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith("/api/books")) {
          return new Response(
            JSON.stringify([
              { ...BOOK_WITH_NOTES, id: 2, title: "Deep Work", title_cn: "深度工作", author: "" },
            ]),
            { status: 200 }
          );
        }
        return new Response("not found", { status: 404 });
      })
    );
    renderPage();
    expect(await screen.findByText("Deep Work")).toBeInTheDocument();
    expect(screen.getByText("译：深度工作")).toBeInTheDocument();
    expect(screen.queryByText("未知作者")).not.toBeInTheDocument();
    expect(screen.queryByText(/^\s*刘慈欣\s*$/)).not.toBeInTheDocument();
  });

  it("有笔记的书籍禁止删除：前端预检直接提示且不发起 DELETE", async () => {
    const deleteSpy = vi.fn();
    stubBooksFetch(deleteSpy);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "删除书籍" }));
    expect(
      await screen.findByText("该书籍存在关联笔记，请先删除全部笔记后再删除书籍。")
    ).toBeInTheDocument();
    expect(deleteSpy).not.toHaveBeenCalled();
  });

  it("无笔记的书籍删除需确认后发起 DELETE", async () => {
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true)
    );
    const deletes: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/books" ) {
          return new Response(JSON.stringify([{ ...BOOK_WITH_NOTES, note_count: 0 }]), { status: 200 });
        }
        if (url === "/api/books/1" && init?.method === "DELETE") {
          deletes.push(url);
          return new Response(null, { status: 204 });
        }
        return new Response("not found", { status: 404 });
      })
    );
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "删除书籍" }));
    await waitFor(() => expect(deletes).toEqual(["/api/books/1"]));
  });
});


describe("读书笔记 Markdown 支持", () => {
  beforeEach(() => vi.unstubAllGlobals());

  function stubFetch(handler: (url: string, init?: RequestInit) => Promise<Response> | Response) {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init)));
  }

  async function openNotesDialog() {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "笔记" }));
  }

  it("在线写笔记：保存时 POST /notes/md 并提交文件名与内容", async () => {
    const posts: Array<{ url: string; body: unknown }> = [];
    stubFetch(async (url, init) => {
      if (url === "/api/books") return new Response(JSON.stringify([BOOK_WITH_NOTES]), { status: 200 });
      if (url === "/api/books/1/notes") return new Response(JSON.stringify([]), { status: 200 });
      if (url === "/api/books/1/notes/md" && init?.method === "POST") {
        posts.push({ url, body: JSON.parse(String(init.body)) });
        return new Response(
          JSON.stringify({ id: 9, book_id: 1, filename: "读后感.md", size: 10, uploaded_at: "2026-11-01T00:00:00" }),
          { status: 201 }
        );
      }
      return new Response("not found", { status: 404 });
    });

    await openNotesDialog();
    fireEvent.click(await screen.findByRole("button", { name: "在线写笔记" }));
    fireEvent.change(screen.getByLabelText(/笔记名称/), { target: { value: "读后感" } });
    fireEvent.change(screen.getByLabelText(/内容/), { target: { value: "# 标题\n\n要点" } });
    fireEvent.click(screen.getByRole("button", { name: "保存笔记" }));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].url).toBe("/api/books/1/notes/md");
    expect(posts[0].body).toEqual({ filename: "读后感", content: "# 标题\n\n要点" });
  });

  it("上传 .md 文件通过前端预检并提交 multipart", async () => {
    const uploads: string[] = [];
    stubFetch(async (url, init) => {
      if (url === "/api/books") return new Response(JSON.stringify([BOOK_WITH_NOTES]), { status: 200 });
      if (url === "/api/books/1/notes" && init?.method === "POST") {
        uploads.push(url);
        return new Response(
          JSON.stringify({ id: 10, book_id: 1, filename: "章节.md", size: 5, uploaded_at: "2026-11-01T00:00:00" }),
          { status: 201 }
        );
      }
      if (url === "/api/books/1/notes") return new Response(JSON.stringify([]), { status: 200 });
      return new Response("not found", { status: 404 });
    });

    await openNotesDialog();
    const input = await screen.findByTestId("note-file-input");
    const file = new File(["# md"], "章节.md", { type: "text/markdown" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(uploads).toEqual(["/api/books/1/notes"]));
    expect(screen.queryByText(/仅支持 PDF/)).not.toBeInTheDocument();
  });

  it("在线写笔记：内容为空时提示且不发起请求", async () => {
    const posts: string[] = [];
    stubFetch(async (url, init) => {
      if (url === "/api/books") return new Response(JSON.stringify([BOOK_WITH_NOTES]), { status: 200 });
      if (url === "/api/books/1/notes") return new Response(JSON.stringify([]), { status: 200 });
      if (url === "/api/books/1/notes/md" && init?.method === "POST") {
        posts.push(url);
        return new Response("{}", { status: 201 });
      }
      return new Response("not found", { status: 404 });
    });

    await openNotesDialog();
    fireEvent.click(await screen.findByRole("button", { name: "在线写笔记" }));
    fireEvent.click(screen.getByRole("button", { name: "保存笔记" }));

    expect(await screen.findByText("笔记内容不能为空")).toBeInTheDocument();
    expect(posts).toEqual([]);
  });
});


describe("笔记预览与下载", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const NOTE = { id: 5, book_id: 1, filename: "章节笔记.pdf", size: 10, uploaded_at: "2026-11-01T00:00:00" };

  function stubFetch() {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/books") return new Response(JSON.stringify([BOOK_WITH_NOTES]), { status: 200 });
        if (url === "/api/books/1/notes") return new Response(JSON.stringify([NOTE]), { status: 200 });
        return new Response("not found", { status: 404 });
      })
    );
  }

  it("预览弹窗展示下载按钮，链接指向 file?download=1 且带原始文件名", async () => {
    stubFetch();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ReadingPage />
        </MemoryRouter>
      </QueryClientProvider>
    );

    fireEvent.click(await screen.findByRole("button", { name: "笔记" }));
    fireEvent.click(await screen.findByRole("button", { name: /章节笔记\.pdf/ }));

    const download = await screen.findByRole("link", { name: "下载" });
    expect(download).toHaveAttribute("href", "/api/notes/5/file?download=1");
    expect(download).toHaveAttribute("download", "章节笔记.pdf");

    // 预览 iframe 仍指向无参数的 inline 地址
    expect(screen.getByTitle("章节笔记.pdf")).toHaveAttribute("src", "/api/notes/5/file");
  });
});
