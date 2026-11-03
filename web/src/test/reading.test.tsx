import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ReadingPage } from "../pages/ReadingPage";

const BOOK_WITH_NOTES = {
  id: 1,
  title: "三体",
  author: "刘慈欣",
  note: "",
  status: "reading",
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

  it("渲染书籍卡片与状态筛选", async () => {
    stubBooksFetch();
    renderPage();
    expect(await screen.findByText("三体")).toBeInTheDocument();
    expect(screen.getAllByText("正在读").length).toBeGreaterThan(0);
    expect(screen.getByText("待读")).toBeInTheDocument();
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
