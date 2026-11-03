/** 统一 API 客户端：处理 JSON、错误格式 {detail:{code,message}}、FormData。 */

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

type ApiOptions = RequestInit & { json?: unknown };

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const init: RequestInit = { method: options.method ?? "GET", headers: { ...options.headers } };
  if (options.json !== undefined) {
    init.body = JSON.stringify(options.json);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  } else if (options.body !== undefined) {
    init.body = options.body;
  }
  let response: Response;
  try {
    response = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, "network_error", "无法连接后端服务");
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = data?.detail ?? {};
    throw new ApiError(response.status, detail.code ?? "unknown_error", detail.message ?? "请求失败");
  }
  return data as T;
}

export function todayStr(offsetDays = 0): string {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}
