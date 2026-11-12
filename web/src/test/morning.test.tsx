import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { MorningReportPage } from "../pages/MorningReportPage";

const REPORT = {
  id: 1,
  report_date: "2026-11-10",
  version_no: 1,
  is_primary: true,
  status: "published",
  title: "今日晨报",
  sections: {},
  content_md: "# 今日晨报\n\n## 一、开篇速览\n\n今天值得关注的事。",
  window_start: "2026-11-09T08:00:00+08:00",
  window_end: "2026-11-10T08:00:00+08:00",
  snapshot_id: "snap-x",
  generation_mode: "auto",
  created_at: "2026-11-10T08:05:00+08:00",

};

function makeFetchMock() {
  return vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (/\/api\/morning\/report\/\d+\/news/.test(url)) {
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }
    if (url.includes("/api/morning/report")) {
      return new Response(JSON.stringify(REPORT), { status: 200 });
    }
    if (url.includes("/api/morning/status")) {
      return new Response(
        JSON.stringify({
          db_ok: true, mr_schema_version: 1, schedule_enabled: true, today: "2026-11-10",
          today_run: { id: 5, status: "success", error: null, started_at: null, finished_at: null },
          news_counts: { domestic: 100, international: 44, ai: 20 },
        }),
        { status: 200 },
      );
    }
    if (url.includes("/api/morning/usage")) {
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }
    if (url.includes("/api/morning/history")) {
      return new Response(JSON.stringify({ items: [
        { id: 1, report_date: "2026-11-10", version_no: 1, is_primary: true, status: "published",
          created_at: "2026-11-10T08:05:00+08:00", has_evaluation: true },
      ] }), { status: 200 });
    }
    if (url.includes("/api/morning/progress/active")) {
      return new Response(JSON.stringify({
        run: null, stages: [], recent: [], done_count: 0, total_count: 8,
        server_now: new Date().toISOString(), stall_seconds: 150, seq: 0, active: false,
      }), { status: 200 });
    }
    if (url.includes("/api/morning/progress")) {
      return new Response(JSON.stringify({
        run: null, stages: [], recent: [], done_count: 0, total_count: 8,
        server_now: new Date().toISOString(), stall_seconds: 150, seq: 0, active: false,
      }), { status: 200 });
    }
    return new Response(JSON.stringify({ detail: { code: "not_found", message: "not found" } }), { status: 404 });
  });
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <MorningReportPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MorningReportPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", makeFetchMock());
    localStorage.clear();
  });

  it("渲染晨报正文（五部分正文可见，标注主报告）", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("今天值得关注的事。")).toBeInTheDocument());
    expect(screen.getByText(/版本 v1（主报告）/)).toBeInTheDocument();
    expect(screen.getAllByText("今日晨报").length).toBeGreaterThan(0);
  });

  it("移除质量评价页，保留正文和历史入口", async () => {
    renderPage();
    await screen.findByText("晨报正文");
    expect(screen.queryByText("质量评价")).not.toBeInTheDocument();
    expect(screen.getByText("历史晨报")).toBeInTheDocument();
    expect(screen.queryByText(/综合分/)).not.toBeInTheDocument();
  });

  it("历史晨报在弹窗中独立展示，可关闭、可下载", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("历史晨报"));
    fireEvent.click(await screen.findByText("2026-11-10"));
    // 弹窗打开：包含下载按钮与正文内容，正文页签不被替换
    await waitFor(() => expect(screen.getByText("下载 Markdown")).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getAllByText("今天值得关注的事。").length).toBeGreaterThanOrEqual(1),
    ); // 弹窗内正文渲染完成
    // 关闭弹窗
    fireEvent.click(screen.getByLabelText("关闭"));
    await waitFor(() => expect(screen.queryByText("下载 Markdown")).not.toBeInTheDocument());
  });

  it("重新生成触发后端调用，提交后立即互斥（不等轮询）", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/morning/regenerate")) {
        return new Response(JSON.stringify({ run_id: 42, mode: "reuse", status: "pending" }),
          { status: 202 });
      }
      return makeFetchMock()(input as RequestInfo, _init);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    fireEvent.click(await screen.findByText("重新生成"));
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]));
      expect(calls.some((u) => u.includes("/api/morning/regenerate"))).toBe(true);
    });
    // 提交成功后两个按钮立即禁用（onSubmitted 置 active，不依赖 5s 轮询）
    await waitFor(() => {
      expect(screen.getByText("重新生成").closest("button")).toBeDisabled();
      expect(screen.getByText("重新组装").closest("button")).toBeDisabled();
    });
  });

  it("重新组装发送当前版本ID，与重新生成互斥且移除完整重算", async () => {
    const base = makeFetchMock();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/api/morning/reassemble")) return new Response(JSON.stringify({ run_id: 43 }), { status: 202 });
      return base(input as RequestInfo, init);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    await screen.findByText("今天值得关注的事。");
    expect(screen.queryByText("完整重算")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("重新组装"));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(call => String(call[0]).includes("/api/morning/reassemble"));
      expect(call).toBeDefined();
      expect(JSON.parse(String(call![1]?.body))).toEqual({ version_id: 1 });
      expect(screen.getByText("重新生成").closest("button")).toBeDisabled();
      expect(screen.getByText("重新组装").closest("button")).toBeDisabled();
    });
    expect(fetchMock.mock.calls.some(call => String(call[0]).includes("/api/morning/regenerate"))).toBe(false);
  });

  it("保留生成进度，移除晨报助手与 Memory 管理且不请求其接口", async () => {
    const fetchMock = makeFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    await screen.findByText("今天值得关注的事。");
    expect(screen.getByText("生成进度")).toBeInTheDocument();
    expect(screen.queryByText("晨报助手")).not.toBeInTheDocument();
    expect(screen.queryByText("Memory 管理")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("偏好 / Memory / 目标补充…")).not.toBeInTheDocument();
    const urls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(urls.some((url) => /\/morning\/(memory|assistant)/.test(url))).toBe(false);
  });

});

// ---------- 进度面板（生成进度） ----------

const STAGES = [
  { stage: "collect", title: "资讯采集", group: null, status: "success", summary: "窗口内 490 条",
    reason: "", started_at: "2026-11-11T12:00:00+08:00", finished_at: "2026-11-11T12:00:20+08:00",
    elapsed_ms: 20000, attempts: 1, last_event_at: "2026-11-11T12:00:20+08:00",
    data: { in_window: 490, by_category: { domestic: 320, international: 140, ai: 30 },
      raw_by_category: { domestic: 400, international: 200, ai: 40 },
      windowed_by_category: { domestic: 350, international: 160, ai: 35 },
      selected_by_category: { domestic: 10, international: 10, ai: 3 } } },
  { stage: "goal_analysis", title: "目标分析 Subagent", group: null, status: "running",
    summary: "", reason: "", started_at: "2026-11-11T12:01:00+08:00", finished_at: null,
    elapsed_ms: null, attempts: 1, last_event_at: new Date().toISOString(), data: null },
  { stage: "advice", title: "建议 Subagent", group: null, status: "pending", summary: "", reason: "",
    started_at: null, finished_at: null, elapsed_ms: null, attempts: 0,
    last_event_at: null, data: null },
];

function makeProgressFetchMock(overrides: { active?: boolean; status?: string } = {}) {
  const base = makeFetchMock();
  const snap = {
    run: { id: 9, run_date: "2026-11-11", kind: "generate",
           status: overrides.status ?? "running", error: null,
           started_at: "2026-11-11T12:00:00+08:00", finished_at: null },
    stages: STAGES,
    recent: [{ id: 1, at: "2026-11-11T12:00:20+08:00", stage: "collect", level: "info",
               message: "采集完成" }],
    done_count: 1, total_count: 8,
    server_now: new Date().toISOString(), stall_seconds: 150, seq: 5,
    active: overrides.active ?? true,
  };
  const fn = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/morning/progress")) {
      return new Response(JSON.stringify(snap), { status: 200 });
    }
    return base(input as RequestInfo, _init);
  });
  return fn;
}

describe("生成进度面板", () => {
  it("SSE 相同 seq 的终态快照也生效，并关闭连接", async () => {
    const connections: MockEventSource[] = [];
    class MockEventSource {
      onmessage: ((e: { data: string }) => void) | null = null;
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      close = vi.fn();
      constructor(_url: string) { connections.push(this); }
    }
    const originalEventSource = globalThis.EventSource;
    vi.stubGlobal("EventSource", MockEventSource);
    vi.stubGlobal("fetch", makeProgressFetchMock());
    const view = renderPage();
    try {
      await screen.findByText("进行中");
      await waitFor(() => expect(connections).toHaveLength(1));
      await act(async () => {
        connections[0].onmessage!({ data: JSON.stringify({
          run: { id: 9, status: "failed", error: "主编生成失败", started_at: null, finished_at: null },
          stages: [], recent: [], done_count: 0, total_count: 8, seq: 5,
          active: false, server_now: new Date().toISOString(), stall_seconds: 150,
        }) });
        connections[0].onmessage!({ data: JSON.stringify({ done: true, status: "failed", seq: 5 }) });
      });
      expect(screen.queryByText("进行中")).not.toBeInTheDocument();
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
      expect(connections[0].close).toHaveBeenCalled();
      expect(screen.getByText("重新生成").closest("button")).not.toBeDisabled();
    } finally {
      view.unmount();
      vi.stubGlobal("EventSource", originalEventSource);
    }
  });

  it("轮询收到生成失败后更新面板、提示并恢复按钮", async () => {
    let failed = false;
    let submitted = false;
    const polls = new Set<() => void>();
    const originalInterval = window.setInterval.bind(window);
    const intervalSpy = vi.spyOn(window, "setInterval").mockImplementation((handler, timeout, ...args) => {
      if (timeout === 5000) polls.add(handler as () => void);
      return originalInterval(handler, timeout, ...args);
    });
    const base = makeFetchMock();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/regenerate")) {
        submitted = true;
        return new Response(JSON.stringify({ run_id: 9, status: "pending" }), { status: 202 });
      }
      if (url.includes("/progress")) {
        if (!submitted) return base(input, init);
        return new Response(JSON.stringify({
          run: { id: 9, status: failed ? "failed" : "running", error: failed ? "主编生成失败" : null,
            started_at: new Date().toISOString(), finished_at: failed ? new Date().toISOString() : null },
          stages: [], recent: [], done_count: 0, total_count: 8, seq: 5,
          active: !failed, server_now: new Date().toISOString(), stall_seconds: 150,
        }));
      }
      return base(input, init);
    }));
    const view = renderPage();
    fireEvent.click(await screen.findByText("重新生成"));
    await screen.findByText("进行中");
    expect(screen.queryByText("已提交重新生成，生成中…")).not.toBeInTheDocument();
    try {
      failed = true;
      await act(async () => { for (const poll of polls) poll(); });
      expect(screen.queryByText("进行中")).not.toBeInTheDocument();
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
      expect(screen.getByText("重新生成").closest("button")).not.toBeDisabled();
      expect(screen.getByText("停止生成").closest("button")).toBeDisabled();
    } finally {
      view.unmount();
      intervalSpy.mockRestore();
    }
  });

  it("展示新阶段列表：已完成/进行中/未开始且没有技术研究与并行标识", async () => {
    vi.stubGlobal("fetch", makeProgressFetchMock());
    renderPage();
    await waitFor(() => expect(screen.getByRole("button", { name: /资讯采集/ })).toBeInTheDocument());
    expect(screen.queryByText("技术研究 Subagent")).not.toBeInTheDocument();
    expect(screen.getAllByText("目标分析 Subagent").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("button", { name: /建议 Subagent/ })).toBeInTheDocument();
    expect(screen.queryByText("并行执行")).not.toBeInTheDocument(); // 目标分析与建议顺序执行
    expect(screen.getByText("阶段 1/8")).toBeInTheDocument(); // 整体进度
    expect(screen.getByText("当前：")).toBeInTheDocument(); // 当前阶段行
    // 当前阶段高亮（目标分析 running）：阶段列表行带高亮底色
    const highlighted = screen.getAllByText("目标分析 Subagent")
      .some((el) => el.closest("button")?.className.includes("bg-sky-50"));
    expect(highlighted).toBe(true);
  });

  it("点击阶段打开悬浮详情，含执行详情与技术详情折叠", async () => {
    vi.stubGlobal("fetch", makeProgressFetchMock());
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /资讯采集/ }));
    await waitFor(() => expect(screen.getByText("尝试次数")).toBeInTheDocument());
    expect(screen.getByText("国内 320 条")).toBeInTheDocument();
    expect(screen.getByText("国际 140 条")).toBeInTheDocument();
    expect(screen.getByText("AI 30 条")).toBeInTheDocument();
    expect(screen.getByText("国内：400 → 350 → 320")).toBeInTheDocument();
    expect(screen.getByText("最终选用：国内 10 条、国际 10 条、AI 3 条")).toBeInTheDocument();
    expect(screen.getByText("中新网官方热点排行（顺序依据未公开）和 AIHOT 当期日报")).toBeInTheDocument(); // 阶段目的
    expect(screen.getByText("技术详情（已脱敏）")).toBeInTheDocument(); // 折叠区标题
    fireEvent.click(screen.getByLabelText("关闭详情"));
    await waitFor(() => expect(screen.queryByText("尝试次数")).not.toBeInTheDocument());
  });

  it("任务运行期间两个生成按钮同时禁用", async () => {
    vi.stubGlobal("fetch", makeProgressFetchMock({ active: true }));
    renderPage();
    await waitFor(() => expect(screen.getByText("生成进度")).toBeInTheDocument());
    const reuse = screen.getByText("重新生成").closest("button")!;
    const full = screen.getByText("重新组装").closest("button")!;
    expect(reuse).toBeDisabled();
    expect(full).toBeDisabled();
  });

  it("任务终态后按钮恢复可点击", async () => {
    vi.stubGlobal("fetch", makeProgressFetchMock({ active: false, status: "success" }));
    renderPage();
    await waitFor(() => expect(screen.getByText("生成进度")).toBeInTheDocument());
    await waitFor(() => {
      expect(screen.getByText("重新生成").closest("button")).not.toBeDisabled();
    });
    expect(screen.getByText("重新组装").closest("button")).not.toBeDisabled();
  });
});

describe("停止生成", () => {
  it("活动任务时停止按钮可用；确认后请求停止并进入正在停止；任务终态后复位", async () => {
    let stopCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/morning/runs/9/stop")) {
        stopCalls += 1;
        return new Response(JSON.stringify({ run_id: 9, status: "stopping" }), { status: 200 });
      }
      if (url.includes("/api/morning/progress")) {
        return new Response(JSON.stringify({
          run: { id: 9, run_date: "2026-11-11", kind: "generate", status: "running",
                 error: null, started_at: "2026-11-11T12:00:00+08:00", finished_at: null },
          stages: STAGES, recent: [], done_count: 1, total_count: 8,
          server_now: new Date().toISOString(), stall_seconds: 150, seq: 5, active: true,
        }), { status: 200 });
      }
      return makeFetchMock()(input as RequestInfo, _init);
    });
    vi.stubGlobal("fetch", fetchMock);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    const stopBtn = await screen.findByText("停止生成");
    expect(stopBtn.closest("button")).not.toBeDisabled(); // 活动任务 → 可用
    // 生成按钮保持禁用
    expect(screen.getByText("重新生成").closest("button")).toBeDisabled();
    fireEvent.click(stopBtn);
    await waitFor(() => expect(stopCalls).toBe(1));
    await waitFor(() => expect(screen.getByText("正在停止…")).toBeInTheDocument());
    expect(screen.getByText("正在停止…").closest("button")).toBeDisabled();
    expect(screen.getByText("重新生成").closest("button")).toBeDisabled(); // 停止期间仍禁用
    confirmSpy.mockRestore();
  });

  it("无活动任务时停止按钮禁用；用户取消确认则不发送请求", async () => {
    let stopCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/stop")) {
        stopCalls += 1;
        return new Response(JSON.stringify({ run_id: 1, status: "cancelled" }), { status: 200 });
      }
      return makeFetchMock()(input as RequestInfo, _init);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    await waitFor(() => expect(screen.getByText("重新生成")).toBeInTheDocument());
    // 默认 mock 无活动任务
    await waitFor(() => {
      expect(screen.getByText("重新生成").closest("button")).not.toBeDisabled();
    });
    expect(screen.getByText("停止生成").closest("button")).toBeDisabled();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(screen.getByText("停止生成"));
    expect(stopCalls).toBe(0); // 取消确认：不发请求（按钮本也禁用，双保险）
    confirmSpy.mockRestore();
  });
});

it("资讯缺失的采集步骤显示黄色感叹号", async () => {
  const base = makeProgressFetchMock();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const response = await base(input, init);
    if (!String(input).includes("/progress")) return response;
    const snap = await response.json();
    snap.stages = snap.stages.map((stage: typeof STAGES[number]) => stage.stage === "collect"
      ? { ...stage, status: "warning", summary: "AIHOT获取失败：日报日期不符" } : stage);
    return new Response(JSON.stringify(snap), { status: 200 });
  }));
  renderPage();
  const stage = (await screen.findByRole("button", { name: /资讯采集/ })).closest("button")!;
  expect(stage.querySelector("svg")).toHaveClass("text-amber-600");
});
