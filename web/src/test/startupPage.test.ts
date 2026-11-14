/// <reference types="vite/client" />
import html from "../../../launcher/startup.html?raw";
import { afterEach, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/react";

afterEach(() => { document.body.innerHTML = ""; });

function runPage(state: object) {
  const page = new DOMParser().parseFromString(html, "text/html");
  document.body.innerHTML = page.body.innerHTML;
  const location = { pathname: "/startup/test", replace: vi.fn() };
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ elapsed_s: 2, messages: ["phase complete"], ...state }), { status: 200 }));
  const timer = vi.fn();
  new Function("fetch", "location", "document", "setTimeout", page.querySelector("script")!.textContent!)(fetcher, location, document, timer);
  return { location, timer, fetcher };
}

it("首页就绪后替换当前启动标签页", async () => {
  const { location, fetcher } = runPage({ status: "ready", home_url: "http://127.0.0.1:18620/" });
  await waitFor(() => expect(location.replace).toHaveBeenCalledWith("http://127.0.0.1:18620/"));
  expect(fetcher).toHaveBeenCalledWith("/api/startup/test", { cache: "no-store" });
});

it("未就绪保留进度，失败显示错误且不跳转", async () => {
  const loading = runPage({ status: "loading" });
  await waitFor(() => expect(loading.timer).toHaveBeenCalled());
  expect(loading.location.replace).not.toHaveBeenCalled();
  expect(document.getElementById("logs")).toHaveTextContent("phase complete");
  const failed = runPage({ status: "failed", error: "test failure" });
  await waitFor(() => expect(document.getElementById("description")).toHaveTextContent("test failure"));
  expect(failed.location.replace).not.toHaveBeenCalled();
});
