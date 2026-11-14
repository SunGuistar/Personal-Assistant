import { createContext, useContext, type ReactNode } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { api } from "../lib/api";

type ModuleName = "morning" | "wechat" | "reading" | "github";
type StartupStatus = {
  home_ready: boolean;
  modules: Record<ModuleName, { status: "loading" | "ready" | "failed"; duration_s: number; error: string | null }>;
};
const StartupContext = createContext<UseQueryResult<StartupStatus> | null>(null);
const LABELS = { morning: "今日晨报", wechat: "微信管理", reading: "阅读管理", github: "GitHub" };

export function StartupProvider({ children }: { children: ReactNode }) {
  const status = useQuery({
    queryKey: ["module_startup"], queryFn: () => api<StartupStatus>("/startup"), retry: false,
    staleTime: 0,
    refetchInterval: query => query.state.error ? false :
      !query.state.data || Object.values(query.state.data.modules).some(item => item.status === "loading") ? 1000 : false,
    refetchOnWindowFocus: true,
  });
  return <StartupContext.Provider value={status}>{children}</StartupContext.Provider>;
}

export function ModuleGate({ module, children, quiet = false }: { module: ModuleName; children: ReactNode; quiet?: boolean }) {
  const query = useContext(StartupContext);
  // 单页组件可独立挂载；应用路由统一提供真实就绪状态。
  if (!query) return <>{children}</>;
  const status = query.data?.modules[module];
  if (status?.status === "ready") return <>{children}</>;
  if (quiet) return null;
  if (query.isError || status?.status === "failed") return <section role="alert" className="rounded-xl border bg-white p-8">
    <h1 className="text-xl font-semibold">{LABELS[module]}暂时不可用</h1>
    <p className="mt-3 text-sm text-neutral-600">{status?.error ?? "无法获取模块状态，请检查后端连接。"}</p>
    <p className="mt-2 text-sm text-neutral-500">初始化失败时请重启应用后重试。</p>
    <button className="mt-4 text-sm text-blue-600" onClick={() => void query.refetch()}>重新检查</button>
  </section>;
  return <section role="status" aria-live="polite" className="rounded-xl border bg-white p-8">
    <div className="flex items-center gap-3">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-neutral-200 border-t-blue-600" aria-hidden="true" />
      <h1 className="text-xl font-semibold">{LABELS[module]}加载中…</h1>
    </div>
    <p className="mt-3 text-sm text-neutral-500">准备就绪后会自动显示，你也可以先使用计划管理。</p>
  </section>;
}
