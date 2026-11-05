/** SSE 流读取（POST 请求 + 手动解析 data: 事件；EventSource 只支持 GET）。 */

export interface SseEvent {
  type: string;
  [key: string]: unknown;
}

/** POST 到 SSE 端点并校验响应（失败抛错由调用方捕获）。 */
export async function postSse(path: string, body: unknown = {}): Promise<Response> {
  const response = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    let message = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      message = payload?.detail?.message ?? message;
    } catch {
      // 保留 HTTP 状态兜底
    }
    throw new Error(message);
  }
  return response;
}

export async function* readSseEvents(response: Response): AsyncGenerator<SseEvent> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const line = block.split("\n").find((l) => l.startsWith("data: "));
      if (line) yield JSON.parse(line.slice(6)) as SseEvent;
    }
  }
}
