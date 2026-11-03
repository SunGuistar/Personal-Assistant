import { useQuery } from "@tanstack/react-query";

type HealthResponse = {
  status: string;
  service: string;
  version: string;
};

async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch("/api/health");
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

export function HomePage() {
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, retry: 1 });

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">首页工作台</h1>
      <div className="rounded-lg border border-neutral-200 bg-white p-4 text-sm">
        <div className="font-medium">后端服务状态</div>
        <div className="mt-1 text-neutral-600">
          {health.isLoading && "检查中…"}
          {health.isError && "后端未连接（请先启动服务）"}
          {health.data &&
            `已连接 · ${health.data.service} v${health.data.version}`}
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {["今日计划", "最新资讯", "微信总结", "正在阅读"].map((title) => (
          <div
            key={title}
            className="rounded-lg border border-dashed border-neutral-300 bg-white p-4"
          >
            <div className="text-sm font-medium text-neutral-700">{title}</div>
            <div className="mt-1 text-xs text-neutral-400">阶段 2 起接入</div>
          </div>
        ))}
      </div>
    </div>
  );
}
